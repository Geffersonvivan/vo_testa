"""Testes do motor de conciliação (funções puras — sem banco, SimpleTestCase).

Definem o CONTRATO das duas conciliações antes da implementação (TDD):
  - casar_por_valor_data: extrato bancário (OFX) × registros do CRM.
  - casar_por_nsu: transações da adquirente (SafraPay) × recebimentos de cartão no caixa.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.conciliacao import services
from apps.conciliacao.matching import (
    ItemCaixaCartao,
    ItemCartao,
    ItemCrm,
    ItemExtrato,
    casar_por_nsu,
    casar_por_valor_data,
)
from apps.conciliacao.models import LancamentoExtrato, TransacaoCartao
from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    FormaPagamento,
    MovimentoCaixa,
    SessaoCaixa,
)

Usuario = get_user_model()

OFX_EXEMPLO = """OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260910<TRNAMT>150.00<FITID>ABC1<NAME>PIX RECEBIDO</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260911<TRNAMT>-80.00<FITID>ABC2<NAME>PAGTO FORNECEDOR</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

CSV_CARTAO = (
    "Data da venda;NSU;Bandeira;Valor bruto;Taxa;Valor líquido;Data da liquidação\n"
    "10/09/2026;NSU123;Visa;200,00;5,00;195,00;11/09/2026\n"
)


class CasarValorDataTests(SimpleTestCase):
    def test_casa_valor_e_mesma_data_marca_exata(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("150.00"))]
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("150.00"), entrada=True)]
        r = casar_por_valor_data(ext, crm)
        self.assertEqual(len(r.pares), 1)
        self.assertEqual(r.pares[0].extrato_id, "e1")
        self.assertEqual(r.pares[0].crm_id, "c1")
        self.assertEqual(r.pares[0].confianca, "exata")
        self.assertEqual(r.sem_par_extrato, [])
        self.assertEqual(r.sem_par_crm, [])

    def test_dentro_da_janela_marca_provavel(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 12), valor=Decimal("150.00"))]
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("150.00"), entrada=True)]
        r = casar_por_valor_data(ext, crm, janela_dias=2)
        self.assertEqual(len(r.pares), 1)
        self.assertEqual(r.pares[0].confianca, "provavel")

    def test_fora_da_janela_nao_casa(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 20), valor=Decimal("150.00"))]
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("150.00"), entrada=True)]
        r = casar_por_valor_data(ext, crm, janela_dias=2)
        self.assertEqual(r.pares, [])
        self.assertEqual(len(r.sem_par_extrato), 1)
        self.assertEqual(len(r.sem_par_crm), 1)

    def test_sentido_precisa_bater_credito_nao_casa_pagamento(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("150.00"))]  # crédito
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("150.00"), entrada=False)]
        r = casar_por_valor_data(ext, crm)
        self.assertEqual(r.pares, [])

    def test_debito_casa_com_pagamento(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("-80.00"))]  # débito
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("80.00"), entrada=False)]
        r = casar_por_valor_data(ext, crm)
        self.assertEqual(len(r.pares), 1)

    def test_valor_diferente_nao_casa(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("150.00"))]
        crm = [ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("149.99"), entrada=True)]
        r = casar_por_valor_data(ext, crm)
        self.assertEqual(r.pares, [])

    def test_um_pra_um_nao_casa_duas_vezes(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("100.00"))]
        crm = [
            ItemCrm(id="c1", data=date(2026, 9, 10), valor=Decimal("100.00"), entrada=True),
            ItemCrm(id="c2", data=date(2026, 9, 10), valor=Decimal("100.00"), entrada=True),
        ]
        r = casar_por_valor_data(ext, crm)
        self.assertEqual(len(r.pares), 1)
        self.assertEqual(len(r.sem_par_crm), 1)

    def test_prioriza_data_mais_proxima(self):
        ext = [ItemExtrato(id="e1", data=date(2026, 9, 10), valor=Decimal("100.00"))]
        crm = [
            ItemCrm(id="longe", data=date(2026, 9, 12), valor=Decimal("100.00"), entrada=True),
            ItemCrm(id="perto", data=date(2026, 9, 10), valor=Decimal("100.00"), entrada=True),
        ]
        r = casar_por_valor_data(ext, crm, janela_dias=3)
        self.assertEqual(r.pares[0].crm_id, "perto")


class CasarNsuTests(SimpleTestCase):
    def test_casa_por_nsu_sem_divergencia(self):
        cartao = [ItemCartao(id="t1", nsu="000123", bruto=Decimal("200.00"),
                             liquido=Decimal("195.00"), data_venda=date(2026, 9, 10))]
        caixa = [ItemCaixaCartao(id="k1", nsu="000123", valor=Decimal("200.00"))]
        r = casar_por_nsu(cartao, caixa)
        self.assertEqual(len(r.pares), 1)
        self.assertEqual(r.pares[0].cartao_id, "t1")
        self.assertEqual(r.pares[0].caixa_id, "k1")
        self.assertEqual(r.pares[0].divergencia_valor, Decimal("0.00"))
        self.assertEqual(r.sem_par_cartao, [])
        self.assertEqual(r.sem_par_caixa, [])

    def test_divergencia_de_valor_sinalizada(self):
        cartao = [ItemCartao(id="t1", nsu="000123", bruto=Decimal("200.00"),
                             liquido=Decimal("195.00"), data_venda=date(2026, 9, 10))]
        caixa = [ItemCaixaCartao(id="k1", nsu="000123", valor=Decimal("180.00"))]
        r = casar_por_nsu(cartao, caixa)
        self.assertEqual(r.pares[0].divergencia_valor, Decimal("20.00"))

    def test_nsu_sem_correspondente_vira_sobra_dos_dois_lados(self):
        cartao = [ItemCartao(id="t1", nsu="999", bruto=Decimal("50.00"),
                             liquido=Decimal("48.00"), data_venda=date(2026, 9, 10))]
        caixa = [ItemCaixaCartao(id="k1", nsu="111", valor=Decimal("50.00"))]
        r = casar_por_nsu(cartao, caixa)
        self.assertEqual(r.pares, [])
        self.assertEqual(len(r.sem_par_cartao), 1)
        self.assertEqual(len(r.sem_par_caixa), 1)

    def test_nsu_vazio_nunca_casa(self):
        cartao = [ItemCartao(id="t1", nsu="", bruto=Decimal("50.00"),
                             liquido=Decimal("48.00"), data_venda=date(2026, 9, 10))]
        caixa = [ItemCaixaCartao(id="k1", nsu="", valor=Decimal("50.00"))]
        r = casar_por_nsu(cartao, caixa)
        self.assertEqual(r.pares, [])


class ImportarOfxTests(TestCase):
    def test_importa_e_cria_linhas(self):
        r = services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")
        self.assertEqual(r["novos"], 2)
        self.assertEqual(LancamentoExtrato.objects.count(), 2)
        credito = LancamentoExtrato.objects.get(fitid="ABC1")
        self.assertEqual(credito.valor, Decimal("150.00"))
        self.assertTrue(credito.credito)

    def test_reimportar_mesma_conta_nao_duplica(self):
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")
        r2 = services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")
        self.assertEqual(r2["novos"], 0)
        self.assertEqual(r2["ignorados"], 2)
        self.assertEqual(LancamentoExtrato.objects.count(), 2)


class ImportarCartaoTests(TestCase):
    def test_importa_csv_safrapay(self):
        r = services.importar_cartao_csv(conteudo=CSV_CARTAO)
        self.assertEqual(r["novos"], 1)
        t = TransacaoCartao.objects.get()
        self.assertEqual(t.nsu, "NSU123")
        self.assertEqual(t.bruto, Decimal("200.00"))
        self.assertEqual(t.liquido, Decimal("195.00"))
        self.assertEqual(t.bandeira, "Visa")


class ConciliarBancoTests(TestCase):
    def setUp(self):
        self.cat = CategoriaFinanceira.objects.create(
            nome="Diárias", tipo=CategoriaFinanceira.Tipo.RECEITA)
        self.catd = CategoriaFinanceira.objects.create(
            nome="Fornecedores", tipo=CategoriaFinanceira.Tipo.DESPESA)
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")

    def test_casa_conta_receber_e_pagar_com_extrato(self):
        ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.RECEBER, categoria=self.cat,
            descricao="Diária", valor=Decimal("150.00"), vencimento=date(2026, 9, 10),
            status=ContaPagarReceber.Status.BAIXADA, baixada_em=date(2026, 9, 10))
        ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR, categoria=self.catd,
            descricao="Fornecedor", valor=Decimal("80.00"), vencimento=date(2026, 9, 11),
            status=ContaPagarReceber.Status.BAIXADA, baixada_em=date(2026, 9, 11))
        r = services.conciliar_banco()
        self.assertEqual(r["conciliados"], 2)
        self.assertEqual(
            LancamentoExtrato.objects.filter(status="conciliado").count(), 2)


class ConciliarCartaoTests(TestCase):
    def test_casa_por_nsu_e_lanca_taxa(self):
        user = Usuario.objects.create_user(username="op", password="x123456789")
        sessao = SessaoCaixa.objects.create(operador=user, modulo="reservas")
        forma = FormaPagamento.objects.create(
            nome="Crédito", tipo=FormaPagamento.Tipo.CARTAO_CREDITO)
        mc = MovimentoCaixa.objects.create(
            sessao=sessao, tipo=MovimentoCaixa.Tipo.RECEBIMENTO, forma_pagamento=forma,
            valor=Decimal("200.00"), autorizacao="NSU123", descricao="Venda cartão",
            criado_por=user)
        services.importar_cartao_csv(conteudo=CSV_CARTAO)
        r = services.conciliar_cartao(usuario=user)
        self.assertEqual(r["conciliados"], 1)
        t = TransacaoCartao.objects.get()
        self.assertEqual(t.movimento_caixa_id, mc.id)
        self.assertEqual(t.divergencia_valor, Decimal("0.00"))
        self.assertIsNotNone(t.lancamento_taxa)
        self.assertEqual(t.lancamento_taxa.valor, Decimal("5.00"))


class ConciliacaoManualTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="fin", password="x123456789")
        self.catr = CategoriaFinanceira.objects.create(
            nome="Diárias", tipo=CategoriaFinanceira.Tipo.RECEITA)
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")
        # crédito de 150 (ABC1) e débito de -80 (ABC2)
        self.credito = LancamentoExtrato.objects.get(fitid="ABC1")

    def _conta_receber(self, valor):
        return ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.RECEBER, categoria=self.catr,
            descricao="Diária", valor=valor, vencimento=date(2026, 9, 10),
            status=ContaPagarReceber.Status.BAIXADA, baixada_em=date(2026, 9, 10))

    def test_candidatos_poe_valor_exato_no_topo(self):
        self._conta_receber(Decimal("999.00"))          # não bate
        exata = self._conta_receber(Decimal("150.00"))  # bate
        cands = services.candidatos_para_extrato(self.credito)
        self.assertTrue(cands[0].exato)
        self.assertEqual((cands[0].origem, cands[0].id), ("cpr", exata.id))

    def test_conciliar_manual_liga_e_marca(self):
        conta = self._conta_receber(Decimal("150.00"))
        services.conciliar_manual_extrato(
            lancamento=self.credito, origem="cpr", pk=conta.id, usuario=self.user)
        self.credito.refresh_from_db()
        self.assertEqual(self.credito.status, "conciliado")
        self.assertEqual(self.credito.confianca, "manual")
        self.assertEqual(self.credito.conta_id, conta.id)

    def test_nao_deixa_conciliar_alvo_ja_usado(self):
        conta = self._conta_receber(Decimal("150.00"))
        services.conciliar_manual_extrato(
            lancamento=self.credito, origem="cpr", pk=conta.id, usuario=self.user)
        debito = LancamentoExtrato.objects.get(fitid="ABC2")
        with self.assertRaises(Exception):
            services.conciliar_manual_extrato(
                lancamento=debito, origem="cpr", pk=conta.id, usuario=self.user)

    def test_ignorar_e_desfazer(self):
        services.ignorar_extrato(lancamento=self.credito, usuario=self.user)
        self.credito.refresh_from_db()
        self.assertEqual(self.credito.status, "ignorado")
        services.desfazer_extrato(lancamento=self.credito, usuario=self.user)
        self.credito.refresh_from_db()
        self.assertEqual(self.credito.status, "pendente")

    def test_cartao_manual_com_taxa_e_desfazer_remove_taxa(self):
        from apps.conciliacao.models import LancamentoExtrato as _  # noqa
        from apps.nucleo.models.financeiro import LancamentoFinanceiro, SessaoCaixa
        sessao = SessaoCaixa.objects.create(operador=self.user, modulo="reservas")
        forma = FormaPagamento.objects.create(
            nome="Crédito", tipo=FormaPagamento.Tipo.CARTAO_CREDITO)
        mc = MovimentoCaixa.objects.create(
            sessao=sessao, tipo=MovimentoCaixa.Tipo.RECEBIMENTO, forma_pagamento=forma,
            valor=Decimal("200.00"), autorizacao="ZZZ", descricao="Venda", criado_por=self.user)
        services.importar_cartao_csv(conteudo=CSV_CARTAO)  # NSU123, bruto 200, liquido 195
        t = TransacaoCartao.objects.get()
        services.conciliar_manual_cartao(transacao=t, mc_id=mc.id, usuario=self.user)
        t.refresh_from_db()
        self.assertEqual(t.status, "conciliado")
        self.assertEqual(t.movimento_caixa_id, mc.id)
        self.assertIsNotNone(t.lancamento_taxa)
        lanc_id = t.lancamento_taxa_id
        services.desfazer_cartao(transacao=t, usuario=self.user)
        t.refresh_from_db()
        self.assertEqual(t.status, "pendente")
        self.assertIsNone(t.movimento_caixa_id)
        self.assertFalse(LancamentoFinanceiro.objects.filter(id=lanc_id).exists())


class ViewsRenderTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile  # noqa
        self.user = Usuario.objects.create_user(username="chefe", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_painel_renderiza(self):
        r = self.client.get("/crm/conciliacao/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conciliação")

    def test_manual_renderiza(self):
        r = self.client.get("/crm/conciliacao/manual/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conciliação manual")

    def test_importar_ofx_e_conciliar_pela_view(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        arq = SimpleUploadedFile("extrato.ofx", OFX_EXEMPLO.encode("latin-1"))
        r = self.client.post("/crm/conciliacao/importar-ofx/", {"arquivo": arq, "conta": "123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LancamentoExtrato.objects.count(), 2)
        r2 = self.client.post("/crm/conciliacao/conciliar/")
        self.assertEqual(r2.status_code, 302)


class FechamentoTests(TestCase):
    def test_agrega_o_periodo(self):
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")  # +150 e -80 em set/2026
        services.importar_cartao_csv(conteudo=CSV_CARTAO)          # bruto 200, liquido 195, venda 10/09
        r = services.fechamento(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(r["extrato"]["total"], 2)
        self.assertEqual(r["cartao"]["total"], 1)
        self.assertEqual(r["cartao"]["bruto"], Decimal("200.00"))
        self.assertEqual(r["cartao"]["taxa"], Decimal("5.00"))
        self.assertTrue(any("Taxa de cartão" in k[0] for k in r["kpis"]))

    def test_fora_do_periodo_zera(self):
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")
        r = services.fechamento(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(r["extrato"]["total"], 0)
        self.assertEqual(r["cartao"]["total"], 0)


class FechamentoViewTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="ger", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_fechamento_renderiza(self):
        r = self.client.get("/crm/conciliacao/fechamento/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fechamento de conciliação")

    def test_fechamento_csv(self):
        r = self.client.get("/crm/conciliacao/fechamento/?export=csv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Taxa de cartão", r.content.decode("utf-8"))


class FechamentoGraficoTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="viz", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_grafico_aparece_quando_ha_dados(self):
        services.importar_ofx(conteudo=OFX_EXEMPLO, conta="123")  # linhas em set/2026
        r = self.client.get("/crm/conciliacao/fechamento/?mes=9&ano=2026")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertIn('id="g-ext"', body)
        self.assertIn("chart.umd.min.js", body)

    def test_sem_dados_nao_injeta_chart(self):
        r = self.client.get("/crm/conciliacao/fechamento/?mes=1&ano=2020")
        self.assertNotIn("chart.umd.min.js", r.content.decode("utf-8"))

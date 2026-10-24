from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    ContaRecorrente,
    LancamentoFinanceiro,
    NaturezaFiscal,
)
from apps.nucleo.modulos import Modulo

from .models import ContaContabil, FechamentoMensal, MapeamentoContabil
from .services import plano_de_contas, resolver_conta


class PlanoDeContasTests(TestCase):
    """O seed do plano enxuto roda nas migrações."""

    def test_plano_seedado_com_hierarquia(self):
        c = ContaContabil.objects.get(classificacao="3.1.01.03")
        self.assertEqual(c.nome, "Prestação de Serviços")
        self.assertEqual(c.grupo, ContaContabil.Grupo.RECEITA)
        self.assertTrue(c.analitica)
        # pai amarrado
        self.assertEqual(c.conta_pai.classificacao, "3.1.01")
        self.assertEqual(c.conta_pai.tipo, ContaContabil.Tipo.SINTETICA)

    def test_codigo_contador_preservado_para_export(self):
        self.assertEqual(
            ContaContabil.objects.get(classificacao="3.1.01.03").codigo_contador, 1561
        )
        self.assertEqual(
            ContaContabil.objects.get(classificacao="4.5.01.01").codigo_contador, 3091
        )

    def test_plano_de_contas_service_ordena(self):
        classifs = [c.classificacao for c in plano_de_contas()]
        self.assertEqual(classifs, sorted(classifs))
        self.assertIn("5.1.03.02", classifs)


class ContaContabilCleanTests(TestCase):
    def test_pai_precisa_ser_sintetica(self):
        analitica = ContaContabil.objects.get(classificacao="3.1.01.03")
        nova = ContaContabil(
            classificacao="3.1.01.03.001", nome="Sub", grupo="receita",
            conta_pai=analitica,
        )
        with self.assertRaises(ValidationError):
            nova.clean()


class MapeamentoCleanTests(TestCase):
    def setUp(self):
        self.conta = ContaContabil.objects.get(classificacao="5.1.02.02")

    def test_exige_ao_menos_uma_origem(self):
        m = MapeamentoContabil(conta=self.conta)
        with self.assertRaises(ValidationError):
            m.clean()

    def test_centro_invalido_recusado(self):
        m = MapeamentoContabil(conta=self.conta, centro="inexistente")
        with self.assertRaises(ValidationError):
            m.clean()

    def test_centro_valido_aceito(self):
        m = MapeamentoContabil(conta=self.conta, centro=Modulo.RESTAURANTE)
        m.clean()  # não levanta


class ResolverContaTests(TestCase):
    def test_natureza_servico(self):
        c = resolver_conta(natureza_folio=NaturezaFiscal.SERVICO)
        self.assertEqual(c.classificacao, "3.1.01.03")

    def test_natureza_consumo(self):
        c = resolver_conta(natureza_folio=NaturezaFiscal.CONSUMO)
        self.assertEqual(c.classificacao, "3.1.01.01")

    def test_origem_sistema_cmv(self):
        self.assertEqual(resolver_conta(origem_sistema="cmv").classificacao, "4.5.01.01")

    def test_origem_sistema_taxa_cartao(self):
        self.assertEqual(
            resolver_conta(origem_sistema="pagamento_taxa").classificacao, "5.1.03.02"
        )

    def test_categoria_vence_por_prioridade(self):
        cat = CategoriaFinanceira.objects.create(
            nome="Internet", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        gastos_gerais = ContaContabil.objects.get(classificacao="4.2.01.03")
        MapeamentoContabil.objects.create(
            conta=gastos_gerais, categoria=cat, prioridade=10
        )
        # mesmo com um centro genérico, a regra por categoria (prio 10) vence
        c = resolver_conta(
            tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat, centro=Modulo.RESERVAS
        )
        self.assertEqual(c.classificacao, "4.2.01.03")

    def test_fallback_receita_quando_nada_casa(self):
        c = resolver_conta(tipo=CategoriaFinanceira.Tipo.RECEITA)
        self.assertEqual(c.classificacao, "3.1.01.03")

    def test_fallback_despesa_quando_nada_casa(self):
        c = resolver_conta(tipo=CategoriaFinanceira.Tipo.DESPESA)
        self.assertEqual(c.classificacao, "5.1.02.02")

    def test_sem_tipo_e_sem_regra_retorna_none(self):
        self.assertIsNone(resolver_conta())

    def test_especificidade_desempata(self):
        # na MESMA prioridade, a regra mais específica (categoria+natureza) vence
        # a genérica (só natureza). Removemos o de-para automático da categoria
        # (prio 10) para isolar o desempate por especificidade.
        cat = CategoriaFinanceira.objects.create(
            nome="Diárias", tipo=CategoriaFinanceira.Tipo.RECEITA
        )
        MapeamentoContabil.objects.filter(categoria=cat).delete()
        conta_serv = ContaContabil.objects.get(classificacao="3.1.01.03")
        # específica (esp. 2) aponta p/ serviços; a padrão de consumo (esp. 1) p/ mercadorias
        MapeamentoContabil.objects.create(
            conta=conta_serv, categoria=cat, natureza_folio=NaturezaFiscal.CONSUMO,
            prioridade=5,
        )
        c = resolver_conta(categoria=cat, natureza_folio=NaturezaFiscal.CONSUMO)
        self.assertEqual(c.classificacao, "3.1.01.03")


class DeParaCategoriasExistentesTests(TestCase):
    """A migração 0004 mapeia categorias que existiam; aqui garantimos o comportamento
    do heurístico para novas categorias replicando a mesma lógica via resolver."""

    def test_categoria_honorarios_mapeada_para_administrativo(self):
        # Simula o resultado esperado: criar o mapeamento como a migração faria.
        cat = CategoriaFinanceira.objects.create(
            nome="Honorários Contábeis", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        adm = ContaContabil.objects.get(classificacao="5.1.02.02")
        MapeamentoContabil.objects.filter(categoria=cat).delete()
        MapeamentoContabil.objects.create(conta=adm, categoria=cat, prioridade=10)
        c = resolver_conta(tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat)
        self.assertEqual(c.classificacao, "5.1.02.02")


# ===== Etapa 2 =====

class DeParaAutomaticoCategoriaTests(TestCase):
    def test_categoria_nova_ganha_depara(self):
        cat = CategoriaFinanceira.objects.create(
            nome="Energia Elétrica", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        m = MapeamentoContabil.objects.filter(categoria=cat).first()
        self.assertIsNotNone(m)
        self.assertEqual(m.conta.classificacao, "4.2.01.03")

    def test_categoria_receita_nova_cai_em_servicos(self):
        cat = CategoriaFinanceira.objects.create(
            nome="Hospedagem", tipo=CategoriaFinanceira.Tipo.RECEITA
        )
        m = MapeamentoContabil.objects.get(categoria=cat)
        self.assertEqual(m.conta.classificacao, "3.1.01.03")


class CarimboContaContabilTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="op", password="x" * 10
        )
        self.cat_desp = CategoriaFinanceira.objects.create(
            nome="Internet", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        self.cat_rec = CategoriaFinanceira.objects.create(
            nome="Diárias", tipo=CategoriaFinanceira.Tipo.RECEITA
        )

    def test_lancamento_recebe_conta_contabil(self):
        lanc = LancamentoFinanceiro.objects.create(
            tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=self.cat_desp,
            descricao="Mensalidade internet", valor=Decimal("200.00"),
            criado_por=self.user,
        )
        lanc.refresh_from_db()
        self.assertEqual(lanc.conta_contabil, "4.2.01.03")

    def test_conta_pagar_recebe_conta_contabil(self):
        conta = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR, categoria=self.cat_desp,
            descricao="Internet nov", valor=Decimal("200.00"),
            vencimento=date(2026, 11, 10),
        )
        conta.refresh_from_db()
        self.assertEqual(conta.conta_contabil, "4.2.01.03")

    def test_receita_cai_em_servicos(self):
        lanc = LancamentoFinanceiro.objects.create(
            tipo=CategoriaFinanceira.Tipo.RECEITA, categoria=self.cat_rec,
            descricao="Diária 101", valor=Decimal("620.00"), criado_por=self.user,
        )
        lanc.refresh_from_db()
        self.assertEqual(lanc.conta_contabil, "3.1.01.03")


class ContaRecorrenteTests(TestCase):
    def setUp(self):
        self.cat = CategoriaFinanceira.objects.create(
            nome="Aluguel", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        self.rec = ContaRecorrente.objects.create(
            categoria=self.cat, centro=Modulo.RESERVAS, descricao="Aluguel do imóvel",
            valor=Decimal("8000.00"), dia_vencimento=5,
        )

    def test_clean_recusa_categoria_de_tipo_errado(self):
        cat_rec = CategoriaFinanceira.objects.create(
            nome="Diária", tipo=CategoriaFinanceira.Tipo.RECEITA
        )
        r = ContaRecorrente(
            tipo=ContaPagarReceber.Tipo.PAGAR, categoria=cat_rec,
            centro=Modulo.RESERVAS, descricao="x", valor=Decimal("1.00"),
        )
        with self.assertRaises(ValidationError):
            r.clean()

    def test_gerar_cria_titulo_classificado(self):
        titulo = self.rec.gerar(2026, 11)
        self.assertEqual(titulo.competencia, "2026-11")
        self.assertEqual(titulo.vencimento, date(2026, 11, 5))
        self.assertEqual(titulo.valor, Decimal("8000.00"))
        titulo.refresh_from_db()
        self.assertEqual(titulo.conta_contabil, "5.1.02.02")  # aluguel → administrativo

    def test_gerar_e_idempotente(self):
        t1 = self.rec.gerar(2026, 11)
        t2 = self.rec.gerar(2026, 11)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(
            ContaPagarReceber.objects.filter(recorrencia=self.rec).count(), 1
        )

    def test_dia_vencimento_clampa_no_mes_curto(self):
        self.rec.dia_vencimento = 31
        self.rec.save()
        titulo = self.rec.gerar(2026, 2)  # fev não tem 31
        self.assertEqual(titulo.vencimento, date(2026, 2, 28))

    def test_command_gera_recorrentes(self):
        call_command("gerar_recorrentes", ano=2026, mes=12)
        self.assertEqual(
            ContaPagarReceber.objects.filter(
                recorrencia=self.rec, competencia="2026-12"
            ).count(),
            1,
        )
        # idempotente
        call_command("gerar_recorrentes", ano=2026, mes=12)
        self.assertEqual(
            ContaPagarReceber.objects.filter(recorrencia=self.rec).count(), 1
        )


# ===== Etapa 3 — capturas automáticas =====

from django.test import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.contabil.capturas import (  # noqa: E402
    capturar_cmv,
    capturar_comissoes_ota,
    capturar_mes,
    capturar_receita,
    capturar_taxas_cartao,
)
from apps.nucleo.models.estoque import (  # noqa: E402
    CategoriaProduto,
    LocalEstoque,
    MovimentoEstoque,
    Produto,
)
from apps.pagamentos.models import Cobranca  # noqa: E402


class CapturaTaxaCartaoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("op3", password="x" * 10)
        self.hoje = timezone.now()

    def _cobranca(self, taxa):
        return Cobranca.objects.create(
            valor=Decimal("1000.00"), metodo=Cobranca.Metodo.CARTAO,
            descricao="Reserva", status=Cobranca.Status.PAGO,
            pago_em=self.hoje, taxa=taxa, criado_por=self.user,
        )

    def test_captura_taxa_classificada(self):
        self._cobranca(Decimal("38.50"))
        n = capturar_taxas_cartao(self.hoje.year, self.hoje.month)
        self.assertEqual(n, 1)
        lanc = LancamentoFinanceiro.objects.get(origem="taxa_cartao")
        self.assertEqual(lanc.valor, Decimal("38.50"))
        self.assertEqual(lanc.conta_contabil, "5.1.03.02")
        self.assertEqual(lanc.tipo, CategoriaFinanceira.Tipo.DESPESA)

    def test_idempotente(self):
        self._cobranca(Decimal("38.50"))
        capturar_taxas_cartao(self.hoje.year, self.hoje.month)
        capturar_taxas_cartao(self.hoje.year, self.hoje.month)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(origem="taxa_cartao").count(), 1
        )

    def test_ignora_sem_taxa_e_pendente(self):
        self._cobranca(None)  # pago, sem taxa
        Cobranca.objects.create(
            valor=Decimal("500.00"), metodo=Cobranca.Metodo.PIX, descricao="x",
            status=Cobranca.Status.PENDENTE, taxa=Decimal("5.00"),
            pago_em=self.hoje, criado_por=self.user,
        )
        self.assertEqual(capturar_taxas_cartao(self.hoje.year, self.hoje.month), 0)


class CapturaCMVTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("op4", password="x" * 10)
        self.cat_prod = CategoriaProduto.objects.create(nome="Bebidas")
        self.prod = Produto.objects.create(nome="Refrigerante", categoria=self.cat_prod)
        self.local = LocalEstoque.objects.create(nome="Loja", modulo="loja")
        self.hoje = timezone.now()

    def _saida(self, qtd, custo):
        return MovimentoEstoque.objects.create(
            produto=self.prod, local=self.local,
            tipo=MovimentoEstoque.Tipo.SAIDA_VENDA,
            quantidade=Decimal(qtd), custo_unitario=Decimal(custo),
            criado_por=self.user,
        )

    def test_cmv_classificado_por_modulo(self):
        self._saida("-3", "10.00")
        self._saida("-2", "5.00")  # total custo = 30 + 10 = 40
        n = capturar_cmv(self.hoje.year, self.hoje.month)
        self.assertEqual(n, 1)
        lanc = LancamentoFinanceiro.objects.get(origem="cmv", centro="loja")
        self.assertEqual(lanc.valor, Decimal("40.00"))
        self.assertEqual(lanc.conta_contabil, "4.5.01.01")

    def test_cmv_recomputavel(self):
        self._saida("-3", "10.00")
        capturar_cmv(self.hoje.year, self.hoje.month)
        self._saida("-1", "10.00")  # mais uma venda no mesmo mês
        capturar_cmv(self.hoje.year, self.hoje.month)
        # continua 1 lançamento, com valor atualizado
        lancs = LancamentoFinanceiro.objects.filter(origem="cmv", centro="loja")
        self.assertEqual(lancs.count(), 1)
        self.assertEqual(lancs.first().valor, Decimal("40.00"))


class CapturaReceitaTests(TestCase):
    """Receita vem do folio/vendas — nunca digitada. Sem dupla contagem."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("opr", password="x" * 10)
        self.hoje = timezone.localdate()

    def test_diarias_viram_servico(self):
        from unittest.mock import patch
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("108400.00")):
            n = capturar_receita(self.hoje.year, self.hoje.month)
        lanc = LancamentoFinanceiro.objects.get(origem="receita", centro="reservas")
        self.assertEqual(lanc.conta_contabil, "3.1.01.03")
        self.assertEqual(lanc.valor, Decimal("108400.00"))
        self.assertEqual(lanc.tipo, CategoriaFinanceira.Tipo.RECEITA)
        self.assertTrue(n >= 1)

    def test_loja_soma_caixa_mais_quarto_em_mercadoria(self):
        from unittest.mock import patch
        with patch("apps.loja.services.faturamento_periodo",
                   return_value={"caixa": Decimal("5000"), "quarto": Decimal("3000")}):
            capturar_receita(self.hoje.year, self.hoje.month)
        lanc = LancamentoFinanceiro.objects.get(origem="receita", centro="loja")
        self.assertEqual(lanc.conta_contabil, "3.1.01.01")
        self.assertEqual(lanc.valor, Decimal("8000"))  # caixa + quarto, 1 vez só

    def test_categoria_de_receita_fica_automatica(self):
        from unittest.mock import patch
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("100")):
            capturar_receita(self.hoje.year, self.hoje.month)
        cat = CategoriaFinanceira.objects.get(nome="Hospedagem", tipo="receita")
        self.assertTrue(cat.automatica)

    def test_recomputavel(self):
        from unittest.mock import patch
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("100")):
            capturar_receita(self.hoje.year, self.hoje.month)
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("250")):
            capturar_receita(self.hoje.year, self.hoje.month)
        lancs = LancamentoFinanceiro.objects.filter(origem="receita", centro="reservas")
        self.assertEqual(lancs.count(), 1)
        self.assertEqual(lancs.first().valor, Decimal("250"))


class CronCapturarTests(TestCase):
    URL = "/crm/contabil/cron/capturar/"

    def test_desativado_sem_token_404(self):
        # default CONTABIL_CRON_TOKEN = "" → endpoint desligado
        resp = self.client.post(self.URL)
        self.assertEqual(resp.status_code, 404)

    @override_settings(CONTABIL_CRON_TOKEN="segredo123")
    def test_token_errado_403(self):
        resp = self.client.post(self.URL, HTTP_X_CRON_TOKEN="errado")
        self.assertEqual(resp.status_code, 403)

    @override_settings(CONTABIL_CRON_TOKEN="segredo123")
    def test_token_certo_roda_captura(self):
        resp = self.client.post(self.URL, HTTP_X_CRON_TOKEN="segredo123")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertIn("capturas", resp.json())

    @override_settings(CONTABIL_CRON_TOKEN="segredo123")
    def test_sem_login_funciona_por_token(self):
        # autentica por token, não por sessão
        resp = self.client.post(self.URL + "?token=segredo123")
        self.assertEqual(resp.status_code, 200)

    @override_settings(CONTABIL_CRON_TOKEN="segredo123")
    def test_tambem_gera_recorrentes_do_mes(self):
        cat = CategoriaFinanceira.objects.create(
            nome="Aluguel cron", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        rec = ContaRecorrente.objects.create(
            categoria=cat, centro=Modulo.RESERVAS, descricao="Aluguel",
            valor=Decimal("8000"), dia_vencimento=5,
        )
        hoje = timezone.localdate()
        resp = self.client.post(self.URL, HTTP_X_CRON_TOKEN="segredo123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["recorrentes_criadas"], 1)
        self.assertTrue(
            rec.titulos.filter(competencia=f"{hoje.year:04d}-{hoje.month:02d}").exists()
        )
        # idempotente: 2ª chamada não recria
        resp2 = self.client.post(self.URL, HTTP_X_CRON_TOKEN="segredo123")
        self.assertEqual(resp2.json()["recorrentes_criadas"], 0)


class FolhaDoCadastroTests(TestCase):
    def test_folha_base_soma_ativos(self):
        from apps.nucleo.models import Pessoa
        from apps.nucleo.models.cadastros import Funcionario, folha_base
        p1 = Pessoa.objects.create(nome="A", ativo=True)
        p2 = Pessoa.objects.create(nome="B", ativo=True)
        p3 = Pessoa.objects.create(nome="C (inativo)", ativo=False)
        Funcionario.objects.create(pessoa=p1, cargo="Recepção", salario=Decimal("2000"))
        Funcionario.objects.create(pessoa=p2, cargo="Governança", salario=Decimal("1800"))
        Funcionario.objects.create(pessoa=p3, cargo="Ex", salario=Decimal("9999"))
        r = folha_base()
        self.assertEqual(r["total"], Decimal("3800"))  # ignora inativo
        self.assertEqual(r["qtd"], 2)

    def test_folha_base_sem_salario_zera(self):
        from apps.nucleo.models import Pessoa
        from apps.nucleo.models.cadastros import Funcionario, folha_base
        p = Pessoa.objects.create(nome="SemSalario", ativo=True)
        Funcionario.objects.create(pessoa=p, cargo="X", salario=None)
        self.assertEqual(folha_base()["total"], Decimal("0.00"))


class ReceitaFuturaTests(TestCase):
    def _reserva(self, status, checkin_delta, diaria, noites):
        from datetime import timedelta

        from apps.nucleo.models import UH, Pessoa, TipoUH
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        tipo = TipoUH.objects.create(nome=f"T{checkin_delta}{diaria}", tarifa_base=Decimal("300"))
        uh = UH.objects.create(numero=f"F{Reserva.objects.count()+1}", tipo=tipo)
        p = Pessoa.objects.create(nome="Hóspede fut")
        ci = hoje + timedelta(days=checkin_delta)
        return Reserva.objects.create(
            uh=uh, hospede=p, checkin=ci, checkout=ci + timedelta(days=noites),
            status=status, valor_diaria=Decimal(diaria),
            criado_por=get_user_model().objects.create_user(
                f"u{Reserva.objects.count()}", password="x"*10),
        )

    def test_soma_so_confirmadas_futuras(self):
        from apps.reservas.models import Reserva
        from apps.reservas.services import receita_contratada_futura
        self._reserva(Reserva.Status.CONFIRMADA, 10, "500", 2)   # futura ✓ = 1000
        self._reserva(Reserva.Status.PRE_RESERVA, 12, "999", 3)  # pré → ignora
        self._reserva(Reserva.Status.CONFIRMADA, -5, "400", 2)   # passada → ignora
        r = receita_contratada_futura()
        self.assertEqual(r["total"], Decimal("1000"))
        self.assertEqual(r["qtd"], 1)
        self.assertEqual(len(r["por_mes"]), 1)

    def test_painel_mostra_receita_futura(self):
        from apps.reservas.models import Reserva
        self._reserva(Reserva.Status.CONFIRMADA, 15, "600", 3)  # 1800
        admin = get_user_model().objects.create_superuser("chefe2", "c2@x.com", "x"*10)
        self.client.force_login(admin)
        resp = self.client.get("/crm/contabil/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Receita contratada a entrar")


class FormExcluiCategoriasAutomaticasTests(TestCase):
    def test_categoria_automatica_fora_do_lancamento_manual(self):
        from apps.nucleo.forms import LancamentoFinanceiroForm
        auto = CategoriaFinanceira.objects.create(
            nome="Hospedagem auto", tipo="receita", automatica=True
        )
        manual = CategoriaFinanceira.objects.create(
            nome="Ajuste avulso", tipo="receita", automatica=False
        )
        form = LancamentoFinanceiroForm()
        qs = form.fields["categoria"].queryset
        self.assertNotIn(auto, qs)
        self.assertIn(manual, qs)


class CapturaComissaoOtaTests(TestCase):
    def test_noop_por_padrao(self):
        self.assertEqual(capturar_comissoes_ota(2026, 9), 0)

    @override_settings(CONTABIL_COMISSAO_OTA_PCT=15)
    def test_stub_sem_dado_ainda(self):
        # mecanismo pronto, mas sem fonte de comissão ainda → 0
        self.assertEqual(capturar_comissoes_ota(2026, 9), 0)


class CapturarMesCommandTests(TestCase):
    def test_orquestrador_e_comando(self):
        user = get_user_model().objects.create_user("op5", password="x" * 10)
        agora = timezone.now()
        Cobranca.objects.create(
            valor=Decimal("800.00"), metodo=Cobranca.Metodo.CARTAO, descricao="x",
            status=Cobranca.Status.PAGO, pago_em=agora, taxa=Decimal("20.00"),
            criado_por=user,
        )
        r = capturar_mes(agora.year, agora.month)
        self.assertEqual(r["taxa_cartao"], 1)
        call_command("capturar_lancamentos", ano=agora.year, mes=agora.month)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(origem="taxa_cartao").count(), 1
        )


# ===== Etapa 4 — fechamento mensal guiado =====

class FechamentoMensalTests(TestCase):
    def _fm(self, **kw):
        base = dict(ano=2026, mes=9, folha=Decimal("42000.00"),
                    encargos=Decimal("12600.00"), pro_labore=Decimal("8000.00"),
                    das=Decimal("8892.00"))
        base.update(kw)
        return FechamentoMensal.objects.create(**base)

    def test_aplicar_gera_lancamentos_classificados(self):
        self._fm().aplicar()
        por_ref = {
            lanc.referencia: lanc for lanc in
            LancamentoFinanceiro.objects.filter(origem="fechamento")
        }
        self.assertEqual(len(por_ref), 4)
        self.assertEqual(por_ref["fechamento:2026-09:folha"].conta_contabil, "4.2.01.01")
        self.assertEqual(por_ref["fechamento:2026-09:folha"].valor, Decimal("42000.00"))
        self.assertEqual(por_ref["fechamento:2026-09:encargos"].conta_contabil, "4.2.01.01")
        self.assertEqual(por_ref["fechamento:2026-09:pro_labore"].conta_contabil, "5.1.02.02")
        # DAS cai na dedução de receita, mesmo sendo lançamento de despesa
        self.assertEqual(por_ref["fechamento:2026-09:das"].conta_contabil, "3.1.02.01")

    def test_data_na_competencia(self):
        self._fm().aplicar()
        lanc = LancamentoFinanceiro.objects.filter(origem="fechamento").first()
        self.assertEqual(lanc.data, date(2026, 9, 30))

    def test_recomputavel_e_idempotente(self):
        fm = self._fm()
        fm.aplicar()
        fm.folha = Decimal("45000.00")
        fm.save()
        fm.aplicar()
        lancs = LancamentoFinanceiro.objects.filter(origem="fechamento")
        self.assertEqual(lancs.count(), 4)  # não duplicou
        self.assertEqual(
            lancs.get(referencia="fechamento:2026-09:folha").valor, Decimal("45000.00")
        )

    def test_valor_zero_apaga(self):
        fm = self._fm()
        fm.aplicar()
        self.assertEqual(LancamentoFinanceiro.objects.filter(origem="fechamento").count(), 4)
        fm.pro_labore = Decimal("0")
        fm.save()
        fm.aplicar()
        self.assertEqual(LancamentoFinanceiro.objects.filter(origem="fechamento").count(), 3)
        self.assertFalse(
            LancamentoFinanceiro.objects.filter(
                referencia="fechamento:2026-09:pro_labore"
            ).exists()
        )

    def test_unico_por_mes(self):
        self._fm()
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FechamentoMensal.objects.create(ano=2026, mes=9)

    def test_command_aplica(self):
        self._fm()
        call_command("aplicar_fechamento", ano=2026, mes=9)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(origem="fechamento").count(), 4
        )

    def test_command_sem_fechamento_erro(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("aplicar_fechamento", ano=2099, mes=1)


# ===== Etapa 5 — relatórios + telas =====

from apps.contabil import relatorios as rel  # noqa: E402


class DRETests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("op6", password="x" * 10)

    def _lanc(self, tipo, conta, valor, data):
        cat = CategoriaFinanceira.objects.create(
            nome=f"c{conta}-{valor}", tipo=tipo
        )
        lanc = LancamentoFinanceiro.objects.create(
            tipo=tipo, categoria=cat, descricao="x", valor=Decimal(valor),
            data=data, criado_por=self.user,
        )
        # força a conta (independe do heurístico da categoria)
        LancamentoFinanceiro.objects.filter(pk=lanc.pk).update(conta_contabil=conta)
        return lanc

    def test_dre_soma_e_resultado(self):
        d = date(2026, 9, 10)
        self._lanc(CategoriaFinanceira.Tipo.RECEITA, "3.1.01.03", "100000", d)
        self._lanc(CategoriaFinanceira.Tipo.RECEITA, "3.1.01.01", "20000", d)
        self._lanc(CategoriaFinanceira.Tipo.DESPESA, "3.1.02.01", "7200", d)  # dedução
        self._lanc(CategoriaFinanceira.Tipo.DESPESA, "4.2.01.01", "40000", d)  # custo
        self._lanc(CategoriaFinanceira.Tipo.DESPESA, "5.1.02.02", "10000", d)  # despesa
        self._lanc(CategoriaFinanceira.Tipo.RECEITA, "5.1.03.01", "500", d)  # rec. financeira
        dre = rel.dre(2026, 9)
        self.assertEqual(dre["receita_bruta"], Decimal("120000"))
        self.assertEqual(dre["receita_liquida"], Decimal("112800"))  # 120000 - 7200
        self.assertEqual(dre["lucro_bruto"], Decimal("72800"))       # 112800 - 40000
        # resultado = 72800 - 10000 + 500
        self.assertEqual(dre["resultado"], Decimal("63300"))

    def test_dre_ignora_outro_mes(self):
        self._lanc(CategoriaFinanceira.Tipo.RECEITA, "3.1.01.03", "999", date(2026, 8, 10))
        dre = rel.dre(2026, 9)
        self.assertEqual(dre["receita_bruta"], Decimal("0.00"))


class FluxoCaixaTests(TestCase):
    def test_ignora_reforco_e_sangria(self):
        from apps.nucleo.models.financeiro import (
            FormaPagamento,
            MovimentoCaixa,
            SessaoCaixa,
        )
        user = get_user_model().objects.create_user("opfx", password="x" * 10)
        forma = FormaPagamento.objects.filter(
            tipo=FormaPagamento.Tipo.DINHEIRO
        ).first() or FormaPagamento.objects.create(nome="Dinheiro", tipo="dinheiro")
        sessao = SessaoCaixa.objects.create(operador=user, modulo="reservas")

        def mov(tipo, valor, origem=None, motivo=""):
            return MovimentoCaixa.objects.create(
                sessao=sessao, forma_pagamento=forma, tipo=tipo,
                valor=Decimal(valor), descricao="x", criado_por=user,
                movimento_origem=origem, motivo=motivo,
            )
        rec = mov(MovimentoCaixa.Tipo.RECEBIMENTO, "1000")
        mov(MovimentoCaixa.Tipo.ESTORNO, "100", origem=rec, motivo="devolução")
        mov(MovimentoCaixa.Tipo.REFORCO, "50")     # interno → ignora
        mov(MovimentoCaixa.Tipo.SANGRIA, "300")    # interno → ignora
        hoje = timezone.localdate()
        f = rel.fluxo_caixa(hoje.year, hoje.month)
        self.assertEqual(f["entradas"], Decimal("1000"))   # só recebimento
        self.assertEqual(f["saidas"], Decimal("100"))      # só estorno
        self.assertEqual(f["liquido"], Decimal("900"))


class OrfaosTests(TestCase):
    def test_categoria_sem_depara_aparece(self):
        # cria categoria e remove o de-para automático → vira órfã
        cat = CategoriaFinanceira.objects.create(
            nome="Teste", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        MapeamentoContabil.objects.filter(categoria=cat).delete()
        orf = rel.orfaos()
        self.assertIn(cat, list(orf["categorias"]))


class PainelViewTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "chefe", "c@x.com", "x" * 10
        )
        self.client.force_login(self.admin)

    def test_painel_200(self):
        resp = self.client.get("/crm/contabil/?ano=2026&mes=9")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Painel Contábil")
        self.assertContains(resp, "DRE Gerencial")

    def test_fechar_aplica_e_redireciona(self):
        resp = self.client.post("/crm/contabil/fechar/", {
            "ano": 2026, "mes": 9, "folha": "42000", "encargos": "12600",
            "pro_labore": "8000", "das": "8892",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(origem="fechamento").count(), 4
        )

    def test_export_resumo_csv(self):
        resp = self.client.get("/crm/contabil/export/resumo/?ano=2026&mes=9")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8-sig")

    def test_export_tipo_invalido_404(self):
        resp = self.client.get("/crm/contabil/export/xpto/?ano=2026&mes=9")
        self.assertEqual(resp.status_code, 404)

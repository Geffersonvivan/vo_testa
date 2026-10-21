from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, Prospecto, TipoUH

from . import services
from .models import (
    AnaliseLead, AtividadeComercial, EtapaFunil, MotivoPerda, Oportunidade, PaginaCaptacao,
)

Usuario = get_user_model()


class FunilServiceTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead Teste")
        self.etapa_novo = EtapaFunil.objects.get(nome="Novo lead")

    def test_seed_criou_etapas_e_motivos(self):
        self.assertEqual(EtapaFunil.objects.filter(tipo="ganho").count(), 1)
        self.assertEqual(EtapaFunil.objects.filter(tipo="perdido").count(), 1)
        self.assertTrue(MotivoPerda.objects.exists())

    def test_criar_oportunidade_usa_primeira_etapa(self):
        op = services.criar_oportunidade(
            usuario=self.op, pessoa=self.pessoa, titulo="Reserva grupo",
            valor_estimado=Decimal("1000"),
        )
        self.assertEqual(op.etapa, self.etapa_novo)
        self.assertEqual(op.responsavel, self.op)
        self.assertTrue(op.permanencias.exists())

    def test_mover_para_ganho_sem_reserva_bloqueia(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        ganho = EtapaFunil.objects.get(tipo="ganho")
        with self.assertRaises(ValidationError):
            services.mover_etapa(op, ganho, self.op)

    def test_mover_para_perdido_exige_motivo(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        perdido = EtapaFunil.objects.get(tipo="perdido")
        with self.assertRaises(ValidationError):
            services.mover_etapa(op, perdido, self.op, motivo=None)
        motivo = MotivoPerda.objects.first()
        services.mover_etapa(op, perdido, self.op, motivo=motivo)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)

    def test_valor_ponderado(self):
        etapa = EtapaFunil.objects.get(nome="Negociação")
        op = services.criar_oportunidade(
            usuario=self.op, pessoa=self.pessoa, titulo="X", etapa=etapa,
            valor_estimado=Decimal("1000"),
        )
        self.assertEqual(op.valor_ponderado, Decimal("700.00"))

    def test_marcar_perdida_exige_motivo(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        with self.assertRaises(ValidationError):
            services.marcar_perdida(op, None, self.op)
        motivo = MotivoPerda.objects.first()
        services.marcar_perdida(op, motivo, self.op)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)
        self.assertEqual(op.motivo_perda, motivo)

    def test_pendencia_sem_tarefa(self):
        services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Sem follow")
        tipos = {a["tipo"] for a in services.pendencias_auditoria()}
        self.assertIn("oportunidade_sem_tarefa", tipos)

    def test_kanban_mostra_perdida_recente_e_nao_some(self):
        """Bug: ao marcar perdido, o card sumia do quadro. Deve aparecer na coluna Perdido."""
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        colunas = services.dados_kanban()
        perdido = next(c for c in colunas if c["etapa"].tipo == "perdido")
        self.assertIn(op.id, [o.id for o in perdido["itens"]])  # não some
        abertos = [o.id for c in colunas if c["etapa"].tipo == "aberta" for o in c["itens"]]
        self.assertNotIn(op.id, abertos)  # e não fica nas colunas abertas

    def test_kanban_periodo_padrao_mes_corrente_e_todos(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        # fechado no mês passado → fora do padrão (mês corrente)
        Oportunidade.objects.filter(pk=op.pk).update(
            fechado_em=timezone.now() - timedelta(days=40))
        perdido = next(c for c in services.dados_kanban() if c["etapa"].tipo == "perdido")
        self.assertNotIn(op.id, [o.id for o in perdido["itens"]])  # não aparece
        # mas com todos=True aparece (histórico inteiro)
        perdido = next(c for c in services.dados_kanban(todos=True)
                       if c["etapa"].tipo == "perdido")
        self.assertIn(op.id, [o.id for o in perdido["itens"]])

    def test_reabrir_lead_perdido_volta_para_novo_e_registra_timeline(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        motivo = MotivoPerda.objects.first()
        services.marcar_perdida(op, motivo, self.op, detalhe="foi em outro lugar")
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)

        services.reabrir_oportunidade(op, self.op)
        op.refresh_from_db()
        # Voltou para aberto, na etapa inicial, sem motivo e com selo de reativação.
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)
        self.assertEqual(op.etapa, self.etapa_novo)
        self.assertIsNone(op.motivo_perda)
        self.assertEqual(op.motivo_perda_detalhe, "")
        self.assertIsNone(op.fechado_em)
        self.assertIsNotNone(op.reativada_em)
        # Linha do tempo guarda o motivo da perda anterior.
        nota = op.atividades.filter(tipo=AtividadeComercial.Tipo.SISTEMA,
                                    descricao__icontains="Reaberto").first()
        self.assertIsNotNone(nota)
        self.assertIn(motivo.nome, nota.descricao)

    def test_reabrir_so_vale_para_lead_perdido(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="X")
        with self.assertRaises(ValidationError):
            services.reabrir_oportunidade(op, self.op)


class CapturaSiteTests(TestCase):
    def test_capturar_lead_cria_oportunidade_e_tarefa(self):
        op = services.capturar_lead_site(
            nome="Maria Site", email="maria@ex.com", telefone="49999990000",
            mensagem="Grupo de 8", checkin=timezone.localdate() + timedelta(days=10),
            checkout=timezone.localdate() + timedelta(days=12), hospedes=4,
        )
        self.assertIsNotNone(op)
        self.assertEqual(op.origem, Oportunidade.Origem.SITE)
        self.assertTrue(Prospecto.objects.filter(pessoa=op.pessoa).exists())
        self.assertTrue(op.atividades.filter(concluida=False).exists())

    def test_capturar_idempotente_mesmo_email_datas(self):
        ci = timezone.localdate() + timedelta(days=20)
        co = ci + timedelta(days=2)
        a = services.capturar_lead_site(
            nome="João", email="joao@ex.com", telefone="11", checkin=ci, checkout=co,
        )
        b = services.capturar_lead_site(
            nome="João", email="joao@ex.com", telefone="11", checkin=ci, checkout=co,
            mensagem="Atualizei",
        )
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Oportunidade.objects.filter(origem="site").count(), 1)

    def test_mesmo_email_nome_diferente_cria_pessoa_nova(self):
        """E-mail compartilhado (agência/engano) + nome diferente = pessoa distinta."""
        a = services.capturar_lead_site(nome="Daniela", email="mesmo@ex.com")
        b = services.capturar_lead_site(nome="Flávio Calgaro", email="mesmo@ex.com")
        self.assertNotEqual(a.pessoa_id, b.pessoa_id)
        self.assertEqual(a.pessoa.nome, "Daniela")
        self.assertEqual(b.pessoa.nome, "Flávio Calgaro")

    def test_mesmo_email_nome_compativel_atualiza_para_o_mais_completo(self):
        a = services.capturar_lead_site(nome="Flavio", email="flavio@ex.com")
        b = services.capturar_lead_site(nome="Flávio Calgaro", email="flavio@ex.com")
        self.assertEqual(a.pessoa_id, b.pessoa_id)          # mesma pessoa
        b.pessoa.refresh_from_db()
        self.assertEqual(b.pessoa.nome, "Flávio Calgaro")   # nome completo vence

    def test_dedupe_por_telefone_sem_email(self):
        """LP manda só nome + WhatsApp: o mesmo número não pode virar contato novo."""
        a = services.capturar_lead_site(nome="Gefferson Vivan", telefone="49991338813")
        b = services.capturar_lead_site(nome="Gefferson Vivan", telefone="49991338813")
        self.assertEqual(a.pessoa_id, b.pessoa_id)
        self.assertEqual(Pessoa.objects.filter(nome__icontains="Gefferson").count(), 1)

    def test_dedupe_por_telefone_tolera_mascara_e_ddi(self):
        """Mesmo número gravado com máscara/+55 casa com o enviado só em dígitos."""
        a = services.capturar_lead_site(nome="Ana Paula", telefone="(49) 99999-1234")
        b = services.capturar_lead_site(nome="Ana Paula", telefone="5549999991234")
        self.assertEqual(a.pessoa_id, b.pessoa_id)

    def test_mesmo_telefone_nome_diferente_cria_pessoa_nova(self):
        """Número compartilhado (recado/engano) + nome claramente outro = pessoa distinta."""
        a = services.capturar_lead_site(nome="Maria", telefone="49988887777")
        b = services.capturar_lead_site(nome="Carlos Souza", telefone="49988887777")
        self.assertNotEqual(a.pessoa_id, b.pessoa_id)


class LeadRepetidoCampanhaTests(TestCase):
    """Dedup por campanha (LP): mesma campanha aberta → anota (não duplica);
    histórico anterior → reabre o card em 'Novo lead' p/ a campanha (mantém conversa)."""

    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="lr", password="senha-forte-123")
        self.campA = PaginaCaptacao.objects.create(
            nome="Camp A", slug="camp-a", status=PaginaCaptacao.Status.PUBLICADA,
            criado_por=self.user)
        self.campB = PaginaCaptacao.objects.create(
            nome="Camp B", slug="camp-b", status=PaginaCaptacao.Status.PUBLICADA,
            criado_por=self.user)

    def _cap(self, pagina, msg=""):
        return services.capturar_lead_site(
            nome="Carlos Lead", telefone="49999001122", pagina=pagina, mensagem=msg)

    def test_mesma_campanha_aberta_nao_duplica_so_anota(self):
        a = self._cap(self.campA, "Primeira")
        b = self._cap(self.campA, "De novo")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Oportunidade.objects.filter(pessoa=a.pessoa).count(), 1)
        b.refresh_from_db()
        self.assertIn("Lead repetido", b.observacao)
        self.assertEqual(b.status, Oportunidade.Status.ABERTA)

    def test_mesma_campanha_fechada_reabre_novo_lead(self):
        a = self._cap(self.campA)
        motivo = MotivoPerda.objects.create(nome="Teste perda")
        services.marcar_perdida(a, motivo, self.user)
        a.refresh_from_db()
        self.assertEqual(a.status, Oportunidade.Status.PERDIDA)
        b = self._cap(self.campA, "Voltei")
        self.assertEqual(a.pk, b.pk)  # mesmo card reaberto
        b.refresh_from_db()
        self.assertEqual(b.status, Oportunidade.Status.ABERTA)
        self.assertIsNotNone(b.reativada_em)
        self.assertEqual(b.etapa, services.etapas().first())  # Novo lead

    def test_campanha_diferente_reaproveita_e_retag(self):
        a = self._cap(self.campA)
        b = services.capturar_lead_site(
            nome="Carlos Lead", telefone="49999001122", pagina=self.campB, mensagem="Outra LP")
        self.assertEqual(a.pk, b.pk)  # reaproveita o card (mantém a conversa)
        self.assertEqual(Oportunidade.objects.filter(pessoa=a.pessoa).count(), 1)
        b.refresh_from_db()
        self.assertEqual(b.pagina_captacao_id, self.campB.id)  # retag p/ nova campanha
        self.assertIsNotNone(b.reativada_em)
        self.assertEqual(b.etapa, services.etapas().first())  # Novo lead

    def test_pessoa_nova_cria_card(self):
        op = services.capturar_lead_site(
            nome="Novato Silva", telefone="49988112233", pagina=self.campA)
        self.assertIsNotNone(op)
        self.assertEqual(op.pagina_captacao_id, self.campA.id)
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)

    def test_motivo_lead_repetido_no_catalogo(self):
        self.assertTrue(MotivoPerda.objects.filter(
            nome="Lead repetido (mesma campanha)", ativo=True).exists())


class JevSombraTests(TestCase):
    """Fase 0 (sombra) do piloto Jev — grava a previsão sem afetar o oficial."""

    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="jv", password="senha-forte-1")
        self.pessoa = Pessoa.objects.create(nome="Lead Jev", telefone="49999990000")

    def test_gateway_simulado_deterministico_e_formato(self):
        from apps.comercial.decisao_gateway import get_decisao_gateway
        gw = get_decisao_gateway()
        self.assertEqual(gw.nome, "simulado")
        feats = {"origem": "site", "valor_estimado": 1500, "tem_datas": True,
                 "n_atividades": 1, "tem_telefone": True}
        a = gw.avaliar_lead(feats)
        self.assertEqual(a, gw.avaliar_lead(dict(feats)))       # determinístico
        self.assertTrue(0 <= a["score"] <= 100)
        self.assertIn(a["canal"], ("whatsapp", "ligacao", "email"))
        self.assertEqual(a["modelo"], "simulado-v1")

    def test_analisar_grava_sombra_sem_mexer_no_oficial(self):
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=self.pessoa, titulo="X",
            valor_estimado=Decimal("1500"))
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertIsNotNone(analise.score_jev)                 # sombra gravada
        self.assertEqual(analise.jev_modelo, "simulado-v1")
        self.assertIsNotNone(analise.jev_avaliado_em)
        # score/temperatura OFICIAIS seguem sendo os heurísticos
        self.assertEqual(op.score, services.calcular_score(op))

    @override_settings(DECISAO_GATEWAY="jev")  # sem JEV_API_URL → gateway falha → fallback
    def test_fallback_gracioso_quando_gateway_indisponivel(self):
        op = services.criar_oportunidade(usuario=self.user, pessoa=self.pessoa, titulo="Y")
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertIsNone(analise.score_jev)                    # sombra vazia, sem quebrar
        self.assertTrue(analise.temperatura)                    # análise normal seguiu


class MetaCrmEventoTests(TestCase):
    """Integração 'leads qualificados' — evento de estágio do CRM → Meta (CAPI)."""

    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="mc", password="senha-forte-1")
        self.pessoa = Pessoa.objects.create(nome="Lead CAPI", telefone="49999990000",
                                            email="lead@ex.com")

    def test_estagio_key_normaliza(self):
        e = EtapaFunil.objects.get(nome="Novo lead")
        self.assertEqual(services._estagio_key(e), "novo_lead")

    def test_gateway_simulado_evento_crm(self):
        from apps.comercial.midia_gateways import get_midia_gateway
        res = get_midia_gateway().enviar_evento_crm(
            {"estagio": "novo_lead", "ref": 1, "event_time": 1, "email_hash": "x"})
        self.assertTrue(res["ok"])

    def test_criar_oportunidade_dispara_evento_estagio(self):
        with self.captureOnCommitCallbacks(execute=True) as cbs:
            services.criar_oportunidade(usuario=self.user, pessoa=self.pessoa, titulo="X")
        self.assertTrue(cbs)  # houve on_commit (o envio do evento de estágio)

    @override_settings(MIDIA_GATEWAY="meta", META_CAPI_TOKEN="tok", META_PIXEL_ID="123",
                       META_CRM_NOME="Pousada Vô Testa CRM")
    def test_payload_meta_no_formato_do_guia(self):
        from unittest.mock import patch

        from apps.comercial.midia_gateways import get_midia_gateway
        with patch("apps.comercial.midia_gateways._post_json",
                   return_value={"ok": True}) as m:
            get_midia_gateway().enviar_evento_crm({
                "estagio": "ganho", "ref": 5, "event_time": 100,
                "email_hash": "EMH", "telefone_hash": "PHH",
                "crm_nome": "Pousada Vô Testa CRM"})
        url, payload = m.call_args[0]
        self.assertIn("/123/events", url)
        d = payload["data"][0]
        self.assertEqual(d["action_source"], "system_generated")
        self.assertEqual(d["event_name"], "ganho")
        self.assertEqual(d["custom_data"], {"event_source": "crm",
                                            "lead_event_source": "Pousada Vô Testa CRM"})
        self.assertEqual(d["user_data"]["em"], ["EMH"])
        self.assertEqual(d["user_data"]["ph"], ["PHH"])


class CacadorTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="cac", password="senha-forte-123")

    def test_capturar_lead_gera_analise(self):
        ci = timezone.localdate() + timedelta(days=10)
        op = services.capturar_lead_site(
            nome="Ana Lead", email="ana@ex.com", telefone="4899",
            checkin=ci, checkout=ci + timedelta(days=3), hospedes=2,
        )
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertIn(analise.temperatura, AnaliseLead.Temperatura.values)
        self.assertTrue(analise.rascunho)
        self.assertTrue(analise.motivos)
        self.assertTrue(analise.sinais["tem_datas"])

    def test_analise_sem_datas_pede_datas(self):
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Sem Data"),
            titulo="Lead sem datas",
        )
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertFalse(analise.sinais["tem_datas"])
        self.assertIn("as datas", analise.sinais["faltando"])

    def test_rascunho_por_tipo_de_interesse(self):
        ci = timezone.localdate() + timedelta(days=8)
        co = ci + timedelta(days=1)
        ev = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Ev"), titulo="e",
            tipo_interesse=Oportunidade.TipoInteresse.EVENTO,
            checkin_previsto=ci, checkout_previsto=co,
        )
        du = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Du"), titulo="d",
            tipo_interesse=Oportunidade.TipoInteresse.DAY_USE,
            checkin_previsto=ci, checkout_previsto=co,
        )
        hosp = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Ho"), titulo="h",
            tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM,
            checkin_previsto=ci, checkout_previsto=co,
        )
        self.assertIn("evento", ev.analise.rascunho.lower())
        self.assertIn("dia na pousada", du.analise.rascunho.lower())
        self.assertIn("hospedagem", hosp.analise.rascunho.lower())

    def test_lead_quente_pela_analise(self):
        # Motor de score: lead de alto valor + indicação + datas → temperatura quente.
        ci = timezone.localdate() + timedelta(days=5)
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Bem Quente"),
            titulo="q", valor_estimado=Decimal("5000"),
            origem=Oportunidade.Origem.INDICACAO,
            checkin_previsto=ci, checkout_previsto=ci + timedelta(days=2),
        )
        self.assertEqual(op.analise.temperatura, AnaliseLead.Temperatura.QUENTE)


class CotacaoTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead Cotação")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))

    def test_registrar_cotacao_atualiza_valor_e_etapa(self):
        op = services.criar_oportunidade(usuario=self.user, pessoa=self.pessoa, titulo="Cota")
        hoje = timezone.localdate()
        cot = services.registrar_cotacao(
            oportunidade=op, usuario=self.user, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
            valor_diaria=Decimal("250"),
        )
        op.refresh_from_db()
        self.assertEqual(cot.valor_total, Decimal("500.00"))
        self.assertEqual(op.valor_estimado, Decimal("500.00"))
        self.assertEqual(op.etapa.nome, "Cotação enviada")
        self.assertTrue(op.atividades.filter(tipo="cotacao").exists())

    @override_settings(PRECO_ISS_ALIQUOTA="4.0", PRECO_TAXA_TURISMO_DIARIA="4.00",
                       PRECO_SINGLE_FATOR="0.70")
    def test_cotacao_pela_motor_com_crianca_e_taxas(self):
        # Fase 6: cotação do funil pela motor — pessoa adicional + criança 6-15 + taxas.
        self.tipo.pessoa_adicional = Decimal("100.00")
        self.tipo.capacidade = 6
        self.tipo.save(update_fields=["pessoa_adicional", "capacidade"])
        op = services.criar_oportunidade(usuario=self.user, pessoa=self.pessoa, titulo="Cota2")
        op.adultos, op.criancas, op.idades_criancas = 3, 1, [10]  # 3 ad + 1 criança 6-15
        op.save(update_fields=["adultos", "criancas", "idades_criancas"])
        hoje = timezone.localdate()
        cot = services.registrar_cotacao(
            oportunidade=op, usuario=self.user, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),  # 2 noites
        )
        # diária = 200 + (3−2)×100 + 1×(100/2) = 350.
        self.assertEqual(cot.valor_diaria, Decimal("350.00"))
        # total c/ taxas: hospedagem 700 + ISS 28 + turismo 8 = 736.
        self.assertEqual(cot.valor_total, Decimal("736.00"))


class ConversaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead Conversão")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)

    def test_converter_cria_reserva_e_vincula(self):
        from apps.reservas.models import Reserva
        oport = services.criar_oportunidade(
            usuario=self.op, pessoa=self.pessoa, titulo="Vira reserva",
        )
        hoje = timezone.localdate()
        reserva = services.converter_em_reserva(
            oport, usuario=self.op, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
        )
        oport.refresh_from_db()
        self.assertEqual(oport.status, Oportunidade.Status.GANHA)
        self.assertEqual(oport.reserva_id, reserva.pk)
        self.assertEqual(reserva.status, Reserva.Status.PRE_RESERVA)
        self.assertEqual(reserva.hospede, self.pessoa)

    def test_prospecto_limpo_ao_ganhar(self):
        Prospecto.objects.create(pessoa=self.pessoa)
        oport = services.criar_oportunidade(
            usuario=self.op, pessoa=self.pessoa, titulo="Lead em prospecção",
        )
        hoje = timezone.localdate()
        services.converter_em_reserva(
            oport, usuario=self.op, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
        )
        self.pessoa.refresh_from_db()
        self.assertTrue(hasattr(self.pessoa, "hospede"))
        self.assertFalse(Prospecto.objects.filter(pessoa=self.pessoa).exists())

    def test_nao_converte_duas_vezes(self):
        oport = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Y")
        hoje = timezone.localdate()
        services.converter_em_reserva(
            oport, usuario=self.op, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
        )
        with self.assertRaises(ValidationError):
            services.converter_em_reserva(
                oport, usuario=self.op, tipo_uh=self.tipo,
                checkin=hoje + timedelta(days=8), checkout=hoje + timedelta(days=9),
            )

    def test_cancelamento_anota_oportunidade(self):
        oport = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Canc")
        hoje = timezone.localdate()
        reserva = services.converter_em_reserva(
            oport, usuario=self.op, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
        )
        reserva.cancelar(self.op, "Desistiu")
        self.assertTrue(
            oport.atividades.filter(descricao__icontains="cancelada").exists()
        )
        self.assertTrue(
            oport.atividades.filter(concluida=False, descricao__icontains="Reabordar").exists()
        )


class GestaoLeadFechadoTests(TestCase):
    """Reabrir/mover leads já fechados (área `comercial_fechados`): cancela a reserva
    do ganho, exige motivo, e loga data+motivo do fechamento anterior."""

    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead Fechado")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)

    def _ganho_com_reserva(self):
        oport = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="G")
        hoje = timezone.localdate()
        reserva = services.converter_em_reserva(
            oport, usuario=self.op, tipo_uh=self.tipo,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7))
        oport.refresh_from_db()
        return oport, reserva

    def test_mover_ganho_para_perdido_cancela_reserva_e_loga(self):
        from apps.reservas.models import Reserva
        op, reserva = self._ganho_com_reserva()
        perdido = EtapaFunil.objects.get(tipo="perdido")
        motivo = MotivoPerda.objects.first()
        services.mover_lead_fechado(op, perdido, self.op,
                                    justificativa="cliente desistiu", motivo_perda=motivo)
        op.refresh_from_db(); reserva.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)
        self.assertEqual(op.motivo_perda, motivo)
        self.assertEqual(reserva.status, Reserva.Status.CANCELADA)
        self.assertTrue(op.atividades.filter(
            descricao__icontains="Movido para perdido").exists())
        self.assertTrue(op.atividades.filter(descricao__icontains="cancelada").exists())

    def test_mover_ganho_para_aberto_reabre_e_cancela_reserva(self):
        from apps.reservas.models import Reserva
        op, reserva = self._ganho_com_reserva()
        novo = EtapaFunil.objects.get(nome="Novo lead")
        services.mover_lead_fechado(op, novo, self.op, justificativa="voltou a negociar")
        op.refresh_from_db(); reserva.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)
        self.assertEqual(op.etapa, novo)
        self.assertIsNotNone(op.reativada_em)
        self.assertEqual(reserva.status, Reserva.Status.CANCELADA)

    def _ganho_com_adiantamento(self, valor="100.00"):
        from apps.nucleo.models import FormaPagamento, SessaoCaixa
        from apps.nucleo.modulos import Modulo
        from apps.reservas.services import receber_adiantamento
        op, reserva = self._ganho_com_reserva()
        SessaoCaixa.objects.create(operador=self.op, modulo=Modulo.RESERVAS,
                                   fundo_troco=Decimal("0.00"))
        forma = FormaPagamento.objects.get(tipo="dinheiro")
        receber_adiantamento(reserva, self.op, forma, Decimal(valor))
        return op, reserva

    def test_mover_ganho_com_adiantamento_estorna_no_caixa(self):
        from apps.nucleo.models import MovimentoCaixa
        from apps.reservas.models import Reserva
        op, reserva = self._ganho_com_adiantamento("150.00")
        novo = EtapaFunil.objects.get(nome="Novo lead")
        services.mover_lead_fechado(op, novo, self.op, justificativa="reabrir c/ estorno")
        op.refresh_from_db(); reserva.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)
        self.assertEqual(reserva.status, Reserva.Status.CANCELADA)
        # Movimento inverso (estorno) criado no caixa, mesmo valor do adiantamento.
        self.assertTrue(MovimentoCaixa.objects.filter(
            tipo=MovimentoCaixa.Tipo.ESTORNO, valor=Decimal("150.00")).exists())
        self.assertTrue(op.atividades.filter(
            descricao__icontains="estornado no Caixa").exists())

    def test_adiantamento_sem_caixa_aberto_bloqueia(self):
        from apps.nucleo.models import SessaoCaixa
        op, reserva = self._ganho_com_adiantamento("100.00")
        # fecha a sessão de Reservas → não dá para estornar
        SessaoCaixa.objects.filter(
            operador=self.op, status=SessaoCaixa.Status.ABERTA).update(
            status=SessaoCaixa.Status.FECHADA)
        novo = EtapaFunil.objects.get(nome="Novo lead")
        with self.assertRaises(ValidationError):
            services.mover_lead_fechado(op, novo, self.op, justificativa="x")
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.GANHA)  # intacto

    def test_mover_perdido_para_ganho_sem_reserva_bloqueia(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="P")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        ganho = EtapaFunil.objects.get(tipo="ganho")
        with self.assertRaises(ValidationError):
            services.mover_lead_fechado(op, ganho, self.op, justificativa="x")

    def test_justificativa_obrigatoria(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="J")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        novo = EtapaFunil.objects.get(nome="Novo lead")
        with self.assertRaises(ValidationError):
            services.mover_lead_fechado(op, novo, self.op, justificativa="   ")

    def test_mover_para_perdido_exige_motivo_de_perda(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="M")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        perdido = EtapaFunil.objects.get(tipo="perdido")
        with self.assertRaises(ValidationError):
            services.mover_lead_fechado(op, perdido, self.op, justificativa="x",
                                        motivo_perda=None)

    def test_reserva_nao_cancelavel_bloqueia_e_nao_mexe_no_lead(self):
        from apps.reservas.models import Reserva
        op, reserva = self._ganho_com_reserva()
        Reserva.objects.filter(pk=reserva.pk).update(status=Reserva.Status.HOSPEDADA)
        novo = EtapaFunil.objects.get(nome="Novo lead")
        with self.assertRaises(ValidationError):
            services.mover_lead_fechado(op, novo, self.op, justificativa="x")
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.GANHA)  # intacto

    def test_detalhe_mostra_card_gestao_para_lead_fechado(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="D")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        self.client.login(username="com", password="senha-forte-123")
        r = self.client.get(reverse("comercial:oportunidade", args=[op.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "reabrir / mover lead fechado")

    def test_detalhe_ganho_com_reserva_renderiza_avisos(self):
        op, reserva = self._ganho_com_adiantamento("120.00")
        self.client.login(username="com", password="senha-forte-123")
        r = self.client.get(reverse("comercial:oportunidade", args=[op.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "reabrir / mover lead fechado")
        self.assertContains(r, "estornado")   # aviso do adiantamento
        self.assertContains(r, "cancelar")    # aviso de cancelamento da reserva

    def test_view_mover_fechado_exige_area(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        vera = Usuario.objects.create_user(username="vera", password="senha-forte-123")
        vera.modulos.add(ModuloContratado.objects.get(codigo=Modulo.COMERCIAL))
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="V")
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.op)
        novo = EtapaFunil.objects.get(nome="Novo lead")
        self.client.login(username="vera", password="senha-forte-123")
        # sem a flag → 403
        r = self.client.post(reverse("comercial:mover_fechado", args=[op.pk]),
                             {"etapa": novo.pk, "justificativa": "reabrir"})
        self.assertEqual(r.status_code, 403)
        # com a flag → move
        vera.areas = ["comercial_fechados"]
        vera.save(update_fields=["areas"])
        r = self.client.post(reverse("comercial:mover_fechado", args=[op.pk]),
                             {"etapa": novo.pk, "justificativa": "reabrir"})
        self.assertRedirects(r, reverse("comercial:oportunidade", args=[op.pk]))
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)


class CotacaoConversaoPorQuartoTests(TestCase):
    """Dropdown por quarto real (24 UHs 'Quarto NN — tipo') + pré-atribuição na
    conversão (fallback se ocupado); leads de day use mantêm a seleção por tipo."""

    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="pq", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead Quarto", telefone="49999002233")
        self.tipo = TipoUH.objects.create(nome="Padrão", tarifa_base=Decimal("200"))
        self.uh1 = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.uh2 = UH.objects.create(numero="Quarto 02", tipo=self.tipo)

    def _op(self, tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM):
        return services.criar_oportunidade(
            usuario=self.user, pessoa=self.pessoa, titulo="Quarto",
            tipo_interesse=tipo_interesse)

    # ---- form adaptativo ----
    def test_form_hospedagem_lista_quartos(self):
        from .forms import CotacaoForm
        form = CotacaoForm(oportunidade=self._op())
        self.assertIn("uh", form.fields)
        self.assertNotIn("tipo_uh", form.fields)
        self.assertIn(self.uh1, list(form.fields["uh"].queryset))
        self.assertEqual(
            form.fields["uh"].label_from_instance(self.uh1),
            "Quarto 01 — Embaixo da Recepção")

    def test_form_day_use_mantem_tipo(self):
        from .forms import CotacaoForm
        dtipo = TipoUH.objects.create(
            nome="Day", tarifa_base=Decimal("100"), modalidade=TipoUH.Modalidade.DAY_USE)
        form = CotacaoForm(oportunidade=self._op(Oportunidade.TipoInteresse.DAY_USE))
        self.assertIn("tipo_uh", form.fields)
        self.assertNotIn("uh", form.fields)
        self.assertIn(dtipo, list(form.fields["tipo_uh"].queryset))
        self.assertNotIn(self.tipo, list(form.fields["tipo_uh"].queryset))

    def test_quartos_excluem_day_use(self):
        from .forms import CotacaoForm
        dtipo = TipoUH.objects.create(
            nome="Day2", tarifa_base=Decimal("100"), modalidade=TipoUH.Modalidade.DAY_USE)
        duh = UH.objects.create(numero="Day 01", tipo=dtipo)
        form = CotacaoForm(oportunidade=self._op())
        self.assertNotIn(duh, list(form.fields["uh"].queryset))

    # ---- cotação ----
    def test_registrar_cotacao_com_uh_deriva_tipo(self):
        hoje = timezone.localdate()
        cot = services.registrar_cotacao(
            oportunidade=self._op(), usuario=self.user, uh=self.uh1,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
            valor_diaria=Decimal("200"))
        self.assertEqual(cot.uh_id, self.uh1.id)
        self.assertEqual(cot.tipo_uh_id, self.tipo.id)

    # ---- conversão ----
    def test_converter_com_uh_pre_atribui_o_quarto(self):
        hoje = timezone.localdate()
        reserva = services.converter_em_reserva(
            self._op(), usuario=self.user, uh=self.uh1,
            checkin=hoje + timedelta(days=5), checkout=hoje + timedelta(days=7),
            valor_diaria=Decimal("200"))
        self.assertEqual(reserva.uh_id, self.uh1.id)

    def test_converter_uh_ocupado_cai_para_outro_do_tipo(self):
        from apps.nucleo.models import Hospede
        from apps.reservas.services import criar_prereserva
        hoje = timezone.localdate()
        ci, co = hoje + timedelta(days=5), hoje + timedelta(days=7)
        outro = Pessoa.objects.create(nome="Outro Hospede", telefone="49900000000")
        Hospede.objects.get_or_create(pessoa=outro)
        criar_prereserva(uh=self.uh1, checkin=ci, checkout=co, hospede=outro,
                         usuario=self.user, valor_diaria=Decimal("200"))
        reserva = services.converter_em_reserva(
            self._op(), usuario=self.user, uh=self.uh1, checkin=ci, checkout=co,
            valor_diaria=Decimal("200"))
        self.assertNotEqual(reserva.uh_id, self.uh1.id)    # quarto 01 ocupado → outro
        self.assertEqual(reserva.uh.tipo_id, self.tipo.id)  # mas do mesmo tipo

    # ---- só os livres pela data ----
    def _ocupa_uh1(self, ci, co):
        from apps.nucleo.models import Hospede
        from apps.reservas.services import criar_prereserva
        outro = Pessoa.objects.create(nome="Ocupa", telefone="49900001111")
        Hospede.objects.get_or_create(pessoa=outro)
        criar_prereserva(uh=self.uh1, checkin=ci, checkout=co, hospede=outro,
                         usuario=self.user, valor_diaria=Decimal("200"))

    def test_quartos_para_cotacao_filtra_por_data(self):
        hoje = timezone.localdate()
        ci, co = hoje + timedelta(days=5), hoje + timedelta(days=7)
        self._ocupa_uh1(ci, co)
        livres = list(services.quartos_para_cotacao(ci, co))
        self.assertNotIn(self.uh1, livres)   # ocupado fica fora
        self.assertIn(self.uh2, livres)      # livre entra
        self.assertIn(self.uh1, list(services.quartos_para_cotacao()))  # sem data → todos

    def test_endpoint_json_combo_filtra_por_data(self):
        hoje = timezone.localdate()
        ci, co = hoje + timedelta(days=5), hoje + timedelta(days=7)
        self._ocupa_uh1(ci, co)
        self.client.force_login(self.user)
        r = self.client.get(reverse("comercial:quartos_disponiveis"),
                             {"checkin": ci.isoformat(), "checkout": co.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/json")
        ids = [d["id"] for d in r.json()]
        self.assertIn(self.uh2.pk, ids)        # livre aparece
        self.assertNotIn(self.uh1.pk, ids)     # ocupado não aparece

    def test_quartos_combo_dados_nome_grupo_pcd(self):
        u4 = UH.objects.create(numero="Quarto 04", tipo=self.tipo, pcd=True)
        dados = {d["id"]: d for d in services.quartos_combo_dados(
            services.quartos_para_cotacao())}
        self.assertEqual(dados[self.uh1.pk],
                         {"id": self.uh1.pk, "nome": "Quarto 01", "grupo": "Embaixo da Recepção"})
        self.assertEqual(dados[u4.pk]["nome"], "Quarto 04 · PCD")
        self.assertEqual(dados[u4.pk]["grupo"], "Corredor Engenhocas")

    def test_form_bound_valida_contra_todos_os_24(self):
        from .forms import CotacaoForm
        hoje = timezone.localdate()
        form = CotacaoForm(
            {"uh": self.uh1.pk, "checkin": (hoje + timedelta(days=5)).isoformat(),
             "checkout": (hoje + timedelta(days=7)).isoformat()},
            oportunidade=self._op())
        # no POST o queryset não é filtrado por data → o quarto escolhido valida
        self.assertIn(self.uh1, list(form.fields["uh"].queryset))
        self.assertTrue(form.is_valid(), form.errors.as_json())

    # ---- ala oficial dos quartos ----
    def test_uh_ala_pelo_numero(self):
        self.assertEqual(self.uh1.ala, "Embaixo da Recepção")  # Quarto 01
        u5 = UH.objects.create(numero="Quarto 05", tipo=self.tipo)
        u12 = UH.objects.create(numero="Quarto 12", tipo=self.tipo)
        u20 = UH.objects.create(numero="Quarto 20", tipo=self.tipo)
        self.assertEqual(u5.ala, "Corredor Engenhocas")
        self.assertEqual(u12.ala, "Corredor Histórias")
        self.assertEqual(u20.ala, "Condado dos Hobbits")
        # day use (ex.: DAY-01 parsearia p/ 1, mas o guard por modalidade devolve vazio)
        day = UH.objects.filter(tipo__modalidade=TipoUH.Modalidade.DAY_USE).first()
        self.assertEqual(day.ala, "")

    def test_rotulo_quarto_com_ala_e_pcd(self):
        from apps.comercial.services import rotulo_quarto
        self.assertEqual(rotulo_quarto(self.uh1), "Quarto 01 — Embaixo da Recepção")
        u4 = UH.objects.create(numero="Quarto 04", tipo=self.tipo, pcd=True)
        self.assertEqual(rotulo_quarto(u4), "Quarto 04 — Corredor Engenhocas PCD")


class TemplatesScoreMetaTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Ana", telefone="49999", email="a@a.com")

    def test_templates_mensagem(self):
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=self.pessoa, titulo="T",
            valor_estimado=Decimal("900"),
            checkin_previsto=timezone.localdate() + timedelta(days=3),
            checkout_previsto=timezone.localdate() + timedelta(days=5),
        )
        t = services.templates_mensagem(op)
        self.assertIn("Ana", t["whatsapp_proposta"])
        self.assertIn("obrigado", t["whatsapp_obrigado"].lower())

    def test_score_e_gestao(self):
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=self.pessoa, titulo="Score",
            valor_estimado=Decimal("2500"), origem="indicacao",
            checkin_previsto=timezone.localdate() + timedelta(days=1),
            checkout_previsto=timezone.localdate() + timedelta(days=3),
        )
        self.assertGreaterEqual(op.score, 50)
        hoje = timezone.localdate()
        services.definir_meta(mes=hoje, valor_meta=Decimal("10000"), oportunidades_meta=5)
        gestao = services.dados_gestao(hoje.replace(day=1), hoje)
        self.assertEqual(gestao["meta"], Decimal("10000.00"))
        self.assertIn("forecast", gestao)


class LeadRapidoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.client.login(username="com", password="senha-forte-123")

    def test_lead_novo_cria_pessoa_em_prospeccao(self):
        r = self.client.post(reverse("comercial:lead_novo"), {"nome": "Novo Lead X"})
        self.assertEqual(r.status_code, 200)
        dado = r.json()
        self.assertEqual(dado["grupo"], "Prospecção")
        pessoa = Pessoa.objects.get(pk=dado["id"])
        self.assertTrue(Prospecto.objects.filter(pessoa=pessoa).exists())
        self.assertFalse(hasattr(pessoa, "hospede"))

    def test_lead_novo_exige_nome(self):
        r = self.client.post(reverse("comercial:lead_novo"), {"nome": "  "})
        self.assertEqual(r.status_code, 400)


class ViewTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")
        self.client.login(username="com", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Lead View")

    def test_funil_e_painel_ok(self):
        self.assertEqual(self.client.get(reverse("comercial:funil")).status_code, 200)
        self.assertEqual(self.client.get(reverse("comercial:painel")).status_code, 200)
        self.assertEqual(self.client.get(reverse("comercial:tarefas")).status_code, 200)

    def test_nova_via_post(self):
        r = self.client.post(reverse("comercial:nova"), {
            "pessoa": self.pessoa.pk, "titulo": "Nova op", "valor_estimado": "1.500,00",
            "faturamento": "particular", "origem": "site", "quartos": "1", "hospedes": "2",
        })
        self.assertEqual(Oportunidade.objects.count(), 1)
        op = Oportunidade.objects.first()
        self.assertEqual(op.valor_estimado, Decimal("1500.00"))
        self.assertRedirects(r, reverse("comercial:oportunidade", args=[op.pk]))

    def test_detalhe_renderiza(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Detalhe")
        r = self.client.get(reverse("comercial:oportunidade", args=[op.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Linha do tempo")
        self.assertContains(r, "Registrar cotação")
        self.assertContains(r, "WhatsApp")

    def test_registrar_atividade_via_form(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Coment")
        r = self.client.post(reverse("comercial:atividade", args=[op.pk]), {
            "tipo": "ligacao", "descricao": "Liguei para o casal, retornam amanhã.",
            "concluida": "1",
        })
        self.assertRedirects(r, reverse("comercial:oportunidade", args=[op.pk]))
        self.assertEqual(op.atividades.count(), 1)

    def test_agendar_tarefa_fica_pendente(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Tarefa")
        self.client.post(reverse("comercial:atividade", args=[op.pk]), {
            "tipo": "tarefa", "descricao": "Enviar proposta", "concluida": "0",
        })
        atividade = op.atividades.first()
        self.assertFalse(atividade.concluida)

    def test_mover_ganho_via_view_bloqueia(self):
        op = services.criar_oportunidade(usuario=self.op, pessoa=self.pessoa, titulo="Drag")
        ganho = EtapaFunil.objects.get(tipo="ganho")
        r = self.client.post(reverse("comercial:mover", args=[op.pk]), {"etapa": ganho.pk})
        self.assertRedirects(r, reverse("comercial:funil"))
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("comercial:funil")).status_code, 403)


class LPFundadorTests(TestCase):
    """LP Fundador servida do HTML oficial + captura religada ao funil."""

    def setUp(self):
        from django.core.cache import cache

        from .models import PaginaCaptacao
        cache.clear()  # isola o rate-limit por IP (acumula entre testes no full suite)
        self.u = Usuario.objects.create_superuser(username="lp", password="forte-123-abc")
        self.pag = PaginaCaptacao.objects.create(
            nome="Inauguração — Fundador", slug="fundador",
            status=PaginaCaptacao.Status.PUBLICADA, hero_titulo="Oi", criado_por=self.u)

    def test_lp_serve_html_com_form_e_endpoint(self):
        r = self.client.get(reverse("lp:fundador"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"form-lista", r.content)
        self.assertIn(b"/lp/fundador/lead/", r.content)  # endpoint religado

    def test_raiz_serve_lp_com_flag(self):
        with self.settings(HOME_MODO="lp_fundador"):
            r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"form-lista", r.content)

    def test_captacao_antiga_redireciona(self):
        r = self.client.get("/captacao/fundador/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/lp/fundador/")

    def test_lead_cai_no_funil_com_optin_e_pagina(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_lead"),
            data=json.dumps({"nome": "Fulano LP", "email": "flp@ex.com",
                             "whatsapp": "49999887766", "consent": True,
                             "rastreio": {"utm_source": "instagram"}}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        op = Oportunidade.objects.get(pessoa__email="flp@ex.com")
        self.assertEqual(op.pagina_captacao, self.pag)
        self.assertEqual(op.origem_rastreio.get("utm_source"), "instagram")
        self.assertTrue(op.pessoa.aceita_email)
        self.assertTrue(op.pessoa.aceita_whatsapp)  # o consent da LP concede os dois

    def test_lead_incompleto_400(self):
        import json
        r = self.client.post(reverse("lp:fundador_lead"),
                             data=json.dumps({"nome": ""}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_lead_telefone_incompleto_rejeitado(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_lead"),
            data=json.dumps({"nome": "Tel Curto", "whatsapp": "4999988"}),  # dígitos a menos
            content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("incompleto", r.json()["erro"].lower())
        self.assertFalse(Oportunidade.objects.filter(pessoa__nome="Tel Curto").exists())

    def test_privacidade_publica(self):
        r = self.client.get(reverse("privacidade"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Política de Privacidade")

    def test_capi_dorme_sem_token_e_hasheia_com_token(self):
        # Sem token → no-op (só o Pixel do navegador roda).
        self.assertIsNone(services.enviar_capi_lead(email="a@b.com", assincrono=False))
        with self.settings(META_CAPI_TOKEN="TESTE", META_PIXEL_ID="999"):
            ev = services.enviar_capi_lead(
                email="A@B.com ", telefone="(48) 99999-0000",
                event_id="e1", assincrono=False)
        self.assertEqual(ev["event_name"], "Lead")
        self.assertEqual(ev["event_id"], "e1")
        self.assertEqual(len(ev["user_data"]["em"][0]), 64)      # SHA-256
        self.assertNotIn("@", ev["user_data"]["em"][0])          # nunca em claro

    def test_honeypot_descarta_bot_silenciosamente(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_lead"),
            data=json.dumps({"nome": "Bot", "email": "bot@ex.com",
                             "whatsapp": "49999887766", "empresa": "Spam LTDA"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)          # finge sucesso
        self.assertFalse(Oportunidade.objects.filter(pessoa__email="bot@ex.com").exists())

    def test_envio_instantaneo_descarta(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_lead"),
            data=json.dumps({"nome": "Rapido", "email": "rapido@ex.com",
                             "whatsapp": "49999887766", "ms": 200}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Oportunidade.objects.filter(pessoa__email="rapido@ex.com").exists())

    def test_rate_limit_corta_flood_por_ip(self):
        import json

        from django.core.cache import cache
        cache.clear()
        criados = 0
        for i in range(10):
            self.client.post(
                reverse("lp:fundador_lead"),
                data=json.dumps({"nome": f"Lead {i}", "email": f"l{i}@ex.com",
                                 "whatsapp": "49999887766", "ms": 5000}),
                content_type="application/json", REMOTE_ADDR="203.0.113.9")
        criados = Oportunidade.objects.filter(pessoa__email__endswith="@ex.com").count()
        self.assertLessEqual(criados, 6)              # _RATE_MAX
        self.assertGreater(criados, 0)

    def test_visita_conta_uma_vez_por_navegador(self):
        ua = "Mozilla/5.0 (Macintosh)"
        self.client.get(reverse("lp:fundador"), HTTP_USER_AGENT=ua)
        self.client.get(reverse("lp:fundador"), HTTP_USER_AGENT=ua)  # 2º hit já traz o cookie
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.visitas, 1)

    def test_visita_pula_bot_por_user_agent(self):
        self.client.get(reverse("lp:fundador"), HTTP_USER_AGENT="facebookexternalhit/1.1")
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.visitas, 0)

    @override_settings(EMAIL_ENVIO_ASSINCRONO=False, LEADS_ALERTA_EMAILS="time@ex.com")
    def test_lead_dispara_alerta_e_boas_vindas(self):
        import json

        from django.core import mail
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("lp:fundador_lead"),
                data=json.dumps({"nome": "Maria LP", "email": "maria@ex.com",
                                 "whatsapp": "49999887766", "consent": True}),
                content_type="application/json")
        destinatarios = [to for m in mail.outbox for to in m.to]
        self.assertIn("time@ex.com", destinatarios)     # alerta p/ a equipe
        self.assertIn("maria@ex.com", destinatarios)     # boas-vindas p/ o lead
        assuntos = " ".join(m.subject for m in mail.outbox)
        self.assertIn("Novo lead", assuntos)
        self.assertIn("fundadores", assuntos.lower())


class LPFundador2Tests(TestCase):
    """Fundador II — nova campanha em paralelo (/lp/fundador-2/), sem tocar na LP no ar."""

    def setUp(self):
        from .models import Campanha, PaginaCaptacao
        self.u = Usuario.objects.create_superuser(username="lp2", password="forte-123-abc")
        self.pag = PaginaCaptacao.objects.create(
            nome="Fundador II — 13/09/2026", slug="fundador-2",
            status=PaginaCaptacao.Status.PUBLICADA, hero_titulo="Oi", criado_por=self.u)
        self.camp = Campanha.objects.create(
            nome="Fundador II — 13/09/2026", codigo="fundador-2",
            provedor=Campanha.Provedor.OUTRO, pagina_captacao=self.pag, criado_por=self.u)

    def test_serve_html_com_form_endpoint_e_static_webp(self):
        r = self.client.get(reverse("lp:fundador_2"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"form-lista", r.content)
        self.assertIn(b"/lp/fundador-2/lead/", r.content)          # endpoint próprio
        self.assertIn(b"/static/lp/fundador-2/inventor.webp", r.content)
        self.assertNotIn(b"Fotos/", r.content)                      # nada de caminho relativo
        self.assertNotIn(b"com.br../..", r.content)                 # og corrigido

    def test_nao_referencia_endpoint_da_lp_no_ar(self):
        r = self.client.get(reverse("lp:fundador_2"))
        self.assertNotIn(b"/lp/fundador/lead/", r.content)

    def test_link_do_crm_redireciona_para_a_lp(self):
        r = self.client.get("/captacao/fundador-2/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/lp/fundador-2/")

    def test_lead_so_whatsapp_cai_no_funil_ligado_a_campanha(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_2_lead"),
            data=json.dumps({"nome": "Fulano II", "whatsapp": "49999887766",
                             "consent": True, "ms": 5000,
                             "rastreio": {"utm_campaign": "fundador-2"}}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        op = Oportunidade.objects.get(pagina_captacao=self.pag)
        self.assertTrue(op.pessoa.aceita_whatsapp)
        self.assertEqual(op.origem_rastreio.get("utm_campaign"), "fundador-2")

    def test_honeypot_descarta_sem_criar_lead(self):
        import json
        r = self.client.post(
            reverse("lp:fundador_2_lead"),
            data=json.dumps({"nome": "Bot", "whatsapp": "49999880000",
                             "empresa": "x", "ms": 5000}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)          # finge sucesso
        self.assertFalse(Oportunidade.objects.exists())

    def test_lead_incompleto_400(self):
        import json
        r = self.client.post(reverse("lp:fundador_2_lead"),
                             data=json.dumps({"nome": "Só nome"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)


class LPInauguracaoTests(TestCase):
    """LP Inauguração 31/10 (/lp/inauguracao_31_10_2026/) — HTML bespoke + RSVP no funil."""

    def setUp(self):
        from .models import PaginaCaptacao
        self.u = Usuario.objects.create_superuser(
            username="lpinaug", password="forte-123-abc")
        # O seed (migração 0030) no-opa no banco de teste (sem usuário na migração);
        # cria aqui a página que o endpoint de lead usa p/ etiquetar.
        self.pag = PaginaCaptacao.objects.create(
            nome="Inauguração 31/10 (LP)", slug="inauguracao_31_10_2026",
            status=PaginaCaptacao.Status.PUBLICADA, hero_titulo="Oi", criado_por=self.u)

    def test_serve_html_com_form_e_endpoint_proprio(self):
        r = self.client.get(reverse("lp:inauguracao"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'id="formInaug"', r.content)
        self.assertIn(b"/lp/inauguracao_31_10_2026/lead/", r.content)  # rota própria
        self.assertNotIn(b"/lp/fundador-2/lead/", r.content)           # não reusa a outra

    def test_link_do_crm_redireciona_para_a_lp(self):
        r = self.client.get("/captacao/inauguracao_31_10_2026/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/lp/inauguracao_31_10_2026/")

    def test_rsvp_cai_no_funil_ligado_a_pagina(self):
        import json
        r = self.client.post(
            reverse("lp:inauguracao_lead"),
            data=json.dumps({"nome": "Convidado Inaug", "whatsapp": "49999887766",
                             "pessoas": 2, "origem": "lp-inauguracao-31-10",
                             "consent": True, "ms": 5000,
                             "rastreio": {"utm_campaign": "inauguracao_31_10_2026"}}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        op = Oportunidade.objects.get(pagina_captacao=self.pag)
        self.assertTrue(op.pessoa.aceita_whatsapp)
        self.assertEqual(op.origem_rastreio.get("utm_campaign"), "inauguracao_31_10_2026")

    def test_honeypot_descarta_sem_criar_lead(self):
        import json
        r = self.client.post(
            reverse("lp:inauguracao_lead"),
            data=json.dumps({"nome": "Bot", "whatsapp": "49999880000",
                             "empresa": "x", "ms": 5000}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)          # finge sucesso
        self.assertFalse(Oportunidade.objects.exists())

    def test_rsvp_incompleto_400(self):
        import json
        r = self.client.post(reverse("lp:inauguracao_lead"),
                             data=json.dumps({"nome": "Só nome"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)


class EnriquecimentoLeadTests(TestCase):
    """Sinais estimados do lead (sexo/UF/dispositivo/navegador) — offline."""

    def test_sexo_por_nome(self):
        from .enriquecimento import sexo_por_nome
        self.assertEqual(sexo_por_nome("Maria Silva"), "F")
        self.assertEqual(sexo_por_nome("João Pedro"), "M")
        self.assertEqual(sexo_por_nome("Isabel"), "F")     # exceção termina-em-A
        self.assertEqual(sexo_por_nome("Josué"), "M")      # exceção termina-em-E→M list
        self.assertEqual(sexo_por_nome(""), "")

    def test_uf_por_telefone_varios_formatos(self):
        from .enriquecimento import uf_por_telefone
        self.assertEqual(uf_por_telefone("(49) 99999-0000"), "SC")
        self.assertEqual(uf_por_telefone("5549999990000"), "SC")   # com país
        self.assertEqual(uf_por_telefone("11988887777"), "SP")
        self.assertEqual(uf_por_telefone("21999990000"), "RJ")
        self.assertEqual(uf_por_telefone("999"), "")               # sem DDD válido

    def test_dispositivo_e_navegador(self):
        from .enriquecimento import dispositivo_por_ua, navegador_app
        ig = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605 Instagram 300.0")
        self.assertEqual(dispositivo_por_ua(ig), "iPhone")
        self.assertEqual(navegador_app(ig), "Instagram")
        self.assertEqual(dispositivo_por_ua("Mozilla/5.0 (Linux; Android 13; Mobile)"),
                         "Android (celular)")
        self.assertEqual(navegador_app("Mozilla/5.0 (Windows NT 10.0)"), "")

    def test_geoip_no_op_sem_base(self):
        from .enriquecimento import cidade_uf_por_ip
        self.assertEqual(cidade_uf_por_ip("8.8.8.8"), ("", ""))    # sem GEOIP_CITY_DB
        self.assertEqual(cidade_uf_por_ip("127.0.0.1"), ("", ""))  # IP privado ignorado

    def test_lead_da_lp_grava_sinais_no_rastreio(self):
        import json

        from .models import PaginaCaptacao
        u = Usuario.objects.create_superuser(username="enr", password="forte-123-abc")
        pag = PaginaCaptacao.objects.create(
            nome="F2", slug="fundador-2", status=PaginaCaptacao.Status.PUBLICADA,
            hero_titulo="Oi", criado_por=u)
        r = self.client.post(
            reverse("lp:fundador_2_lead"),
            data=json.dumps({"nome": "Mariana Rossi", "whatsapp": "(49) 99123-4567",
                             "consent": True, "ms": 5000}),
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Instagram 300.0")
        self.assertEqual(r.status_code, 200)
        op = Oportunidade.objects.get(pagina_captacao=pag)
        self.assertEqual(op.origem_rastreio.get("sexo_estimado"), "F")
        self.assertEqual(op.origem_rastreio.get("uf_estimada"), "SC")
        self.assertEqual(op.origem_rastreio.get("dispositivo"), "iPhone")
        self.assertEqual(op.origem_rastreio.get("navegador"), "Instagram")


class WhatsAppCloudTests(TestCase):
    """Envio real (template/texto), janela de 24h, webhook e disparo em lote."""

    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="wa", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(
            nome="Maria Silva", telefone="49999887766",
            aceita_email=True, aceita_whatsapp=True)
        self.op = services.criar_oportunidade(
            usuario=self.user, pessoa=self.pessoa, titulo="Lead WA")

    # ---- envio ----
    def test_enviar_template_registra_saida(self):
        msg = services.enviar_template_whatsapp(
            oportunidade=self.op, template="boas_vindas_fundador",
            variaveis=["Maria"], usuario=self.user)
        self.assertEqual(msg.direcao, "saida")
        self.assertEqual(msg.status, "enviada")  # gateway simulado
        self.assertIn("boas_vindas_fundador", msg.texto)

    def test_reabrir_conversa_dispara_template_de_retomada(self):
        # Fora da janela (cliente nunca falou): o botão "Reabrir conversa" usa o
        # template configurado com o primeiro nome do lead.
        with override_settings(WHATSAPP_TEMPLATE_RETOMADA="retomada_lead"):
            msg = services.reabrir_conversa_whatsapp(
                oportunidade=self.op, usuario=self.user)
        self.assertEqual(msg.direcao, "saida")
        self.assertEqual(msg.status, "enviada")  # simulado
        self.assertIn("retomada_lead", msg.texto)
        self.assertIn("Maria", msg.texto)  # primeiro nome, não "Maria Silva"

    def test_template_aceita_variavel_nomeada_no_payload(self):
        # Variável nomeada ({{nome_cliente}}) → payload leva parameter_name (Cloud API).
        from unittest.mock import patch
        with patch("apps.comercial.whatsapp_gateways._api_post",
                   return_value={"ok": True, "id": "x"}) as pm, \
                override_settings(WHATSAPP_GATEWAY="cloud"):
            services.enviar_template_whatsapp(
                oportunidade=self.op, template="retomada_lead",
                variaveis={"nome_cliente": "Maria"}, usuario=self.user)
        payload = pm.call_args.args[0]
        param = payload["template"]["components"][0]["parameters"][0]
        self.assertEqual(param["parameter_name"], "nome_cliente")
        self.assertEqual(param["text"], "Maria")

    def test_erro_do_gateway_fica_gravado_na_mensagem(self):
        # Meta recusa (ex.: template não aprovado) → o motivo é guardado p/ diagnóstico.
        from unittest.mock import patch
        recusa = {"ok": False, "erro": "HTTP 400: template não aprovado"}
        with patch("apps.comercial.whatsapp_gateways._api_post", return_value=recusa), \
                override_settings(WHATSAPP_GATEWAY="cloud"):
            msg = services.enviar_template_whatsapp(
                oportunidade=self.op, template="retomada_lead",
                variaveis={"nome_cliente": "Maria"}, usuario=self.user)
        self.assertEqual(msg.status, "erro")
        self.assertIn("template não aprovado", msg.erro_detalhe)

    def test_reabrir_conversa_pela_view(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("comercial:whatsapp_reabrir", args=[self.op.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    @override_settings(WHATSAPP_GATEWAY="cloud")
    def test_texto_livre_fora_da_janela_bloqueia(self):
        conv = services.abrir_conversa_whatsapp(self.op)  # cliente nunca falou → fechada
        with self.assertRaises(ValidationError):
            services.enviar_mensagem_whatsapp(
                conversa=conv, texto="Oi", usuario=self.user)

    def test_texto_livre_simulado_sempre_ok(self):
        conv = services.abrir_conversa_whatsapp(self.op)
        msg = services.enviar_mensagem_whatsapp(
            conversa=conv, texto="Oi", usuario=self.user)
        self.assertEqual(msg.status, "enviada")

    # ---- webhook ----
    def _payload_msg(self, texto="Oi, tenho interesse", wamid="wamid.IN1"):
        agora = str(int(timezone.now().timestamp()))
        return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
            "field": "messages", "value": {"messaging_product": "whatsapp", "messages": [{
                "from": "5549999887766", "id": wamid, "timestamp": agora,
                "type": "text", "text": {"body": texto}}]}}]}]}

    def test_webhook_verificacao_ok(self):
        with self.settings(WHATSAPP_VERIFY_TOKEN="segredo"):
            r = self.client.get(reverse("whatsapp:webhook"), {
                "hub.mode": "subscribe", "hub.verify_token": "segredo",
                "hub.challenge": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"123")

    def test_webhook_verificacao_token_errado(self):
        with self.settings(WHATSAPP_VERIFY_TOKEN="segredo"):
            r = self.client.get(reverse("whatsapp:webhook"), {
                "hub.mode": "subscribe", "hub.verify_token": "errado",
                "hub.challenge": "123"})
        self.assertEqual(r.status_code, 403)

    def test_webhook_recebe_mensagem_e_abre_janela(self):
        import json
        r = self.client.post(reverse("whatsapp:webhook"),
                             data=json.dumps(self._payload_msg()),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        conv = self.op.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)
        self.assertTrue(conv.janela_aberta)

    def test_webhook_idempotente(self):
        import json
        for _ in range(2):
            self.client.post(reverse("whatsapp:webhook"),
                             data=json.dumps(self._payload_msg(wamid="wamid.SAME")),
                             content_type="application/json")
        self.assertEqual(self.op.conversa_whatsapp.mensagens.count(), 1)

    def test_webhook_status_failed_marca_erro(self):
        import json

        from .models import MensagemWhatsApp
        conv = services.abrir_conversa_whatsapp(self.op)
        m = MensagemWhatsApp.objects.create(
            conversa=conv, direcao="saida", texto="x", status="enviada",
            id_externo="wamid.OUT1", horario=timezone.now())
        payload = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.OUT1", "status": "failed", "timestamp": "1757000000"}]}}]}]}
        self.client.post(reverse("whatsapp:webhook"), data=json.dumps(payload),
                         content_type="application/json")
        m.refresh_from_db()
        self.assertEqual(m.status, "erro")

    def test_webhook_opt_out_desliga_so_whatsapp(self):
        import json
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(texto="Sair", wamid="wamid.OUT")),
                         content_type="application/json")
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.aceita_whatsapp)   # WhatsApp desligado
        self.assertTrue(self.pessoa.aceita_email)       # e-mail intacto (canal à parte)

    def test_reply_de_lead_ganho_abre_janela(self):
        import json
        # lead já convertido (GANHA): a resposta não se perde — vira recompra (nova op),
        # com a janela de 24h aberta na nova oportunidade.
        self.op.status = Oportunidade.Status.GANHA
        self.op.save(update_fields=["status"])
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(wamid="wamid.GANHO")),
                         content_type="application/json")
        nova = Oportunidade.objects.filter(pessoa=self.pessoa).latest("id")
        self.assertNotEqual(nova.id, self.op.id)
        conv = nova.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)
        self.assertTrue(conv.janela_aberta)

    # ---- número novo (desconhecido) vira lead ----
    def _payload_novo(self, texto="Olá, quero reservar", wamid="wamid.NOVO",
                      numero="5549988776655", nome_perfil="João Turista"):
        agora = str(int(timezone.now().timestamp()))
        val = {"messaging_product": "whatsapp", "messages": [{
            "from": numero, "id": wamid, "timestamp": agora,
            "type": "text", "text": {"body": texto}}]}
        if nome_perfil is not None:
            val["contacts"] = [{"wa_id": numero, "profile": {"name": nome_perfil}}]
        return {"object": "whatsapp_business_account", "entry": [{"id": "WABA",
                "changes": [{"field": "messages", "value": val}]}]}

    def test_webhook_numero_novo_cria_lead(self):
        import json
        antes = Oportunidade.objects.count()
        r = self.client.post(reverse("whatsapp:webhook"),
                             data=json.dumps(self._payload_novo()),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Oportunidade.objects.count(), antes + 1)
        op = Oportunidade.objects.latest("id")
        self.assertEqual(op.origem, Oportunidade.Origem.WHATSAPP)
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)
        self.assertEqual(op.pessoa.nome, "João Turista")  # nome do perfil do WhatsApp
        conv = op.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)
        self.assertTrue(conv.janela_aberta)

    def test_webhook_numero_novo_sem_perfil_usa_telefone(self):
        import json
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_novo(
                             nome_perfil=None, wamid="wamid.SEMNOME",
                             numero="5549911112222")),
                         content_type="application/json")
        op = Oportunidade.objects.latest("id")
        self.assertEqual(op.origem, Oportunidade.Origem.WHATSAPP)
        # nome = "WhatsApp " + número formatado (prova a formatação, não só o dígito cru)
        self.assertEqual(op.pessoa.nome, "WhatsApp (49) 91111-2222")

    def test_webhook_numero_novo_idempotente_nao_duplica_lead(self):
        import json
        antes = Oportunidade.objects.count()
        for _ in range(2):   # Meta reentrega o mesmo wamid → não pode criar 2 leads
            self.client.post(reverse("whatsapp:webhook"),
                             data=json.dumps(self._payload_novo(
                                 wamid="wamid.DUP", numero="5549933334444",
                                 nome_perfil="Lead Repetido")),
                             content_type="application/json")
        self.assertEqual(Oportunidade.objects.count(), antes + 1)
        op = Oportunidade.objects.latest("id")
        self.assertEqual(op.conversa_whatsapp.mensagens.count(), 1)

    def _payload_reacao(self, numero, wamid="wamid.REACT", nome_perfil=None):
        agora = str(int(timezone.now().timestamp()))
        val = {"messaging_product": "whatsapp", "messages": [{
            "from": numero, "id": wamid, "timestamp": agora, "type": "reaction",
            "reaction": {"emoji": "👍", "message_id": "wamid.ALVO"}}]}
        if nome_perfil is not None:
            val["contacts"] = [{"wa_id": numero, "profile": {"name": nome_perfil}}]
        return {"object": "whatsapp_business_account", "entry": [{"id": "WABA",
                "changes": [{"field": "messages", "value": val}]}]}

    def test_webhook_tipo_sem_conteudo_de_numero_novo_nao_cria_lead(self):
        import json
        antes = Oportunidade.objects.count()
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_reacao(
                             "5549955556666", nome_perfil="Reagente")),
                         content_type="application/json")
        self.assertEqual(Oportunidade.objects.count(), antes)  # reação não vira lead

    def test_webhook_tipo_sem_conteudo_de_conhecido_anexa(self):
        import json
        # reação de um número JÁ conhecido (Maria) → anexa à conversa dela (não é lixo)
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_reacao("5549999887766")),
                         content_type="application/json")
        conv = self.op.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)

    # ---- reativação / recompra ----
    def test_webhook_perdida_reabre_mesmo_card(self):
        import json
        # Maria com lead PERDIDO volta a falar → reabre o MESMO card no funil ativo
        self.op.status = Oportunidade.Status.PERDIDA
        self.op.save(update_fields=["status"])
        antes = Oportunidade.objects.count()
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(
                             texto="Oi, voltei!", wamid="wamid.REATIVA")),
                         content_type="application/json")
        self.assertEqual(Oportunidade.objects.count(), antes)  # não cria novo card
        self.op.refresh_from_db()
        self.assertEqual(self.op.status, Oportunidade.Status.ABERTA)   # reaberto
        self.assertEqual(self.op.etapa_id, services.etapas().first().id)  # "Novo lead"
        self.assertIsNotNone(self.op.reativada_em)                     # carimbado
        conv = self.op.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)
        self.assertTrue(self.op.atividades.filter(
            descricao__icontains="Reativado").exists())               # timeline

    def test_webhook_ganha_abre_nova_oportunidade_recompra(self):
        import json
        # Maria com lead GANHO volta a falar → NOVA oportunidade de recompra (carimbada)
        self.op.status = Oportunidade.Status.GANHA
        self.op.save(update_fields=["status"])
        antes = Oportunidade.objects.count()
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(
                             texto="Quero reservar de novo", wamid="wamid.RECOMPRA")),
                         content_type="application/json")
        self.assertEqual(Oportunidade.objects.count(), antes + 1)  # nova oportunidade
        self.op.refresh_from_db()
        self.assertEqual(self.op.status, Oportunidade.Status.GANHA)  # a ganha fica intacta
        nova = Oportunidade.objects.filter(pessoa=self.pessoa).latest("id")
        self.assertNotEqual(nova.id, self.op.id)
        self.assertEqual(nova.status, Oportunidade.Status.ABERTA)
        self.assertEqual(nova.origem, Oportunidade.Origem.WHATSAPP)
        self.assertIsNotNone(nova.reativada_em)

    def test_webhook_reacao_de_perdida_nao_reabre(self):
        import json
        # reação (sem conteúdo) de um lead PERDIDO NÃO deve reabrir o card
        self.op.status = Oportunidade.Status.PERDIDA
        self.op.save(update_fields=["status"])
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_reacao(
                             "5549999887766", wamid="wamid.REACTP")),
                         content_type="application/json")
        self.op.refresh_from_db()
        self.assertEqual(self.op.status, Oportunidade.Status.PERDIDA)  # segue perdida
        self.assertIsNone(self.op.reativada_em)

    # ---- áudio (recebimento) ----
    def _payload_audio(self, numero="5549955557777", wamid="wamid.AUDIO",
                       nome_perfil="Audio Lead", media_id="MEDIA123"):
        agora = str(int(timezone.now().timestamp()))
        val = {"messaging_product": "whatsapp", "messages": [{
            "from": numero, "id": wamid, "timestamp": agora, "type": "audio",
            "audio": {"id": media_id, "mime_type": "audio/ogg", "voice": True}}]}
        if nome_perfil is not None:
            val["contacts"] = [{"wa_id": numero, "profile": {"name": nome_perfil}}]
        return {"object": "whatsapp_business_account", "entry": [{"id": "WABA",
                "changes": [{"field": "messages", "value": val}]}]}

    def test_webhook_audio_cria_lead_e_grava_metadados(self):
        import json
        from .models import MensagemWhatsApp
        antes = Oportunidade.objects.count()
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_audio()),
                         content_type="application/json")
        self.assertEqual(Oportunidade.objects.count(), antes + 1)  # áudio abre lead
        m = MensagemWhatsApp.objects.get(id_externo="wamid.AUDIO")
        self.assertEqual(m.tipo, "audio")
        self.assertEqual(m.midia_id_externo, "MEDIA123")
        self.assertTrue(m.midia_voz)
        self.assertFalse(bool(m.midia_arquivo))  # simulado não baixa → sem arquivo

    def test_webhook_audio_baixa_e_salva_arquivo(self):
        import json
        import tempfile
        from unittest.mock import patch

        from django.test import override_settings

        from .models import MensagemWhatsApp
        from .whatsapp_gateways import GatewaySimulado
        with tempfile.TemporaryDirectory() as tmp, \
             override_settings(MEDIA_ROOT=tmp), \
             patch.object(GatewaySimulado, "baixar_midia",
                          return_value=(b"OggS-fake-audio", "audio/ogg")):
            self.client.post(reverse("whatsapp:webhook"),
                             data=json.dumps(self._payload_audio(wamid="wamid.AUDIO2")),
                             content_type="application/json")
            m = MensagemWhatsApp.objects.get(id_externo="wamid.AUDIO2")
            self.assertTrue(bool(m.midia_arquivo))
            self.assertEqual(m.midia_arquivo.read(), b"OggS-fake-audio")

    # ---- áudio (envio) ----
    def test_enviar_audio_cria_saida(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        self.client.force_login(self.user)
        conv = services.abrir_conversa_whatsapp(self.op)
        audio = SimpleUploadedFile("v.ogg", b"OggS-fake", content_type="audio/ogg")
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            r = self.client.post(
                reverse("comercial:whatsapp_enviar_audio", args=[self.op.pk]),
                {"audio": audio})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            m = conv.mensagens.filter(direcao="saida", tipo="audio").first()
            self.assertIsNotNone(m)
            self.assertEqual(m.status, "enviada")   # gateway simulado
            self.assertTrue(bool(m.midia_arquivo))

    @override_settings(WHATSAPP_GATEWAY="cloud")
    def test_enviar_audio_fora_da_janela_bloqueia(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        conv = services.abrir_conversa_whatsapp(self.op)  # cliente nunca falou → fechada
        audio = SimpleUploadedFile("v.ogg", b"OggS-fake", content_type="audio/ogg")
        with self.assertRaises(ValidationError):
            services.enviar_audio_whatsapp(conversa=conv, arquivo=audio, usuario=self.user)

    # ---- imagem ----
    def _img(self, nome="foto.jpg", mime="image/jpeg", dados=b"\xff\xd8\xff-fake"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nome, dados, content_type=mime)

    def test_enviar_imagem_registra_saida(self):
        from .models import MensagemWhatsApp
        conv = services.abrir_conversa_whatsapp(self.op)
        msg = services.enviar_imagem_whatsapp(
            conversa=conv, arquivo=self._img(), usuario=self.user, legenda="Nossa suíte")
        self.assertEqual(msg.direcao, "saida")
        self.assertEqual(msg.tipo, MensagemWhatsApp.Tipo.IMAGEM)
        self.assertEqual(msg.status, "enviada")   # gateway simulado
        self.assertEqual(msg.texto, "Nossa suíte")  # legenda
        self.assertTrue(msg.midia_arquivo)

    def test_enviar_imagem_recusa_nao_imagem(self):
        conv = services.abrir_conversa_whatsapp(self.op)
        pdf = self._img(nome="doc.pdf", mime="application/pdf", dados=b"%PDF-fake")
        with self.assertRaises(ValidationError):
            services.enviar_imagem_whatsapp(conversa=conv, arquivo=pdf, usuario=self.user)

    def test_enviar_imagem_recusa_acima_5mb(self):
        conv = services.abrir_conversa_whatsapp(self.op)
        grande = self._img(dados=b"x" * (5 * 1024 * 1024 + 1))
        with self.assertRaises(ValidationError):
            services.enviar_imagem_whatsapp(conversa=conv, arquivo=grande, usuario=self.user)

    @override_settings(WHATSAPP_GATEWAY="cloud")
    def test_enviar_imagem_fora_da_janela_bloqueia(self):
        conv = services.abrir_conversa_whatsapp(self.op)  # janela fechada
        with self.assertRaises(ValidationError):
            services.enviar_imagem_whatsapp(conversa=conv, arquivo=self._img(), usuario=self.user)

    def test_webhook_recebe_imagem(self):
        import json

        from .models import MensagemWhatsApp
        agora = str(int(timezone.now().timestamp()))
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
            "field": "messages", "value": {"messaging_product": "whatsapp", "messages": [{
                "from": "5549999887766", "id": "wamid.IMG1", "timestamp": agora,
                "type": "image", "image": {"id": "media-123", "mime_type": "image/jpeg",
                                            "caption": "olha isso"}}]}}]}]}
        self.client.post(reverse("whatsapp:webhook"), data=json.dumps(payload),
                         content_type="application/json")
        m = MensagemWhatsApp.objects.filter(id_externo="wamid.IMG1").first()
        self.assertIsNotNone(m)
        self.assertEqual(m.tipo, MensagemWhatsApp.Tipo.IMAGEM)
        self.assertEqual(m.direcao, "entrada")
        self.assertEqual(m.texto, "olha isso")           # legenda
        self.assertEqual(m.midia_id_externo, "media-123")

    # ---- indicador de mensagem nova no funil (card + sidebar) ----
    def test_kanban_anota_whatsapp_nao_lidas(self):
        import json
        # cliente manda mensagem → conversa da op fica com 1 não lida
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(wamid="wamid.NL1")),
                         content_type="application/json")
        achado = None
        for col in services.dados_kanban():
            for op in col["itens"]:
                if op.pk == self.op.pk:
                    achado = op
        self.assertIsNotNone(achado, "op deveria aparecer no kanban")
        self.assertEqual(achado.wpp_nao_lidas, 1)

    def test_context_processor_conta_nao_lidas(self):
        import json
        from django.test import RequestFactory

        from .context_processors import whatsapp_nao_lidas
        req = RequestFactory().get("/")
        req.user = self.user
        self.assertEqual(whatsapp_nao_lidas(req).get("wpp_nao_lidas_total", 0), 0)
        self.client.post(reverse("whatsapp:webhook"),
                         data=json.dumps(self._payload_msg(wamid="wamid.NL2")),
                         content_type="application/json")
        self.assertEqual(whatsapp_nao_lidas(req).get("wpp_nao_lidas_total"), 1)
        # responder zera o contador
        conv = services.abrir_conversa_whatsapp(self.op)
        services.enviar_mensagem_whatsapp(conversa=conv, texto="Oi", usuario=self.user)
        self.assertEqual(whatsapp_nao_lidas(req).get("wpp_nao_lidas_total", 0), 0)

    def test_webhook_status_failed_nao_reverte(self):
        import json

        from .models import MensagemWhatsApp
        conv = services.abrir_conversa_whatsapp(self.op)
        m = MensagemWhatsApp.objects.create(
            conversa=conv, direcao="saida", texto="x", status="enviada",
            id_externo="wamid.Z", horario=timezone.now())
        st = lambda s: {"entry": [{"changes": [{"value": {"statuses": [  # noqa: E731
            {"id": "wamid.Z", "status": s, "timestamp": "1757000000"}]}}]}]}
        # failed marca erro; um 'delivered' tardio NÃO reverte
        self.client.post(reverse("whatsapp:webhook"), data=json.dumps(st("failed")),
                         content_type="application/json")
        self.client.post(reverse("whatsapp:webhook"), data=json.dumps(st("delivered")),
                         content_type="application/json")
        m.refresh_from_db()
        self.assertEqual(m.status, "erro")

    @override_settings(WHATSAPP_APP_SECRET="segredo-do-app")
    def test_webhook_exige_assinatura_quando_ha_secret(self):
        import hashlib
        import hmac
        import json
        corpo = json.dumps(self._payload_msg(wamid="wamid.SIG")).encode()
        # sem assinatura → 403
        r = self.client.post(reverse("whatsapp:webhook"), data=corpo,
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        # com assinatura correta → 200
        assinatura = "sha256=" + hmac.new(
            b"segredo-do-app", corpo, hashlib.sha256).hexdigest()
        r = self.client.post(reverse("whatsapp:webhook"), data=corpo,
                             content_type="application/json",
                             HTTP_X_HUB_SIGNATURE_256=assinatura)
        self.assertEqual(r.status_code, 200)

    # ---- disparo em lote ----
    def test_disparar_campanha_respeita_optin(self):
        # lead sem opt-in é pulado
        p2 = Pessoa.objects.create(nome="Sem Optin", telefone="4890000000", aceita_email=False)
        services.criar_oportunidade(usuario=self.user, pessoa=p2, titulo="Sem optin")
        res = services.disparar_campanha_whatsapp(
            template="boas_vindas_fundador", usuario=self.user)
        self.assertEqual(res["enviados"], 1)   # só a Maria (com opt-in)
        self.assertGreaterEqual(res["pulados"], 1)


class SitePropostaTests(TestCase):
    def test_pedir_proposta_cria_oportunidade(self):
        r = self.client.post(reverse("core:pedir_proposta"), {
            "nome": "Lead Site Form",
            "telefone": "49999887766",
            "email": "lead@site.com",
            "hospedes": "2",
            "mensagem": "Quero orçamento",
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            Oportunidade.objects.filter(origem="site", pessoa__email="lead@site.com").exists()
        )


class PaginaCaptacaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="com", password="senha-forte-123")

    def _pagina(self, **extra):
        from .models import PaginaCaptacao
        dados = dict(
            nome="Inauguração — Fundador", slug="promo-lp",
            status=PaginaCaptacao.Status.PUBLICADA,
            tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM,
            hero_titulo="Bem-vindo", criado_por=self.op,
        )
        dados.update(extra)
        return PaginaCaptacao.objects.create(**dados)

    def test_rascunho_nao_e_publica(self):
        from .models import PaginaCaptacao
        self._pagina(status=PaginaCaptacao.Status.RASCUNHO)
        r = self.client.get(reverse("captacao:publica", args=["promo-lp"]))
        self.assertEqual(r.status_code, 404)

    def test_publicada_abre_e_conta_visita(self):
        pag = self._pagina()
        r = self.client.get(reverse("captacao:publica", args=["promo-lp"]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Bem-vindo")
        pag.refresh_from_db()
        self.assertEqual(pag.visitas, 1)

    def test_post_cria_lead_no_funil_etiquetado(self):
        pag = self._pagina(tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM)
        r = self.client.post(reverse("captacao:publica", args=["promo-lp"]), {
            "nome": "Maria Fundadora", "telefone": "49999990000", "email": "",
        })
        self.assertEqual(r.status_code, 302)
        op = Oportunidade.objects.filter(pagina_captacao=pag).first()
        self.assertIsNotNone(op)
        self.assertEqual(op.origem, Oportunidade.Origem.SITE)
        self.assertEqual(op.tipo_interesse, Oportunidade.TipoInteresse.HOSPEDAGEM)
        self.assertEqual(op.pessoa.nome, "Maria Fundadora")

    def test_gestao_lista_e_detalhe_ok(self):
        pag = self._pagina()
        self.client.login(username="com", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("comercial:paginas")).status_code, 200)
        r = self.client.get(reverse("comercial:pagina_detalhe", args=[pag.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "/captacao/promo-lp/")

    def test_pixel_e_whatsapp_renderizam(self):
        self._pagina(meta_pixel_id="123456789", whatsapp_destino="5549999990000")
        r = self.client.get(reverse("captacao:publica", args=["promo-lp"]))
        self.assertContains(r, "fbq('init','123456789')")
        # Tela de agradecimento leva ao WhatsApp
        r2 = self.client.get(reverse("captacao:publica", args=["promo-lp"]) + "?ok=1")
        self.assertContains(r2, "wa.me/5549999990000")
        self.assertContains(r2, "fbq('track','Lead')")

    def test_post_enriquece_lead_com_datas_e_pessoas(self):
        pag = self._pagina()
        self.client.post(reverse("captacao:publica", args=["promo-lp"]), {
            "nome": "João Fundador", "telefone": "49988887777",
            "checkin": "2026-11-14", "checkout": "2026-11-16", "pessoas": "4",
        })
        op = Oportunidade.objects.filter(pagina_captacao=pag).first()
        self.assertIsNotNone(op)
        self.assertEqual(op.hospedes, 4)
        self.assertEqual(str(op.checkin_previsto), "2026-11-14")
        self.assertEqual(str(op.checkout_previsto), "2026-11-16")

    def test_post_limita_pessoas_a_8(self):
        pag = self._pagina()
        self.client.post(reverse("captacao:publica", args=["promo-lp"]), {
            "nome": "Grupo Grande", "telefone": "49988887777", "pessoas": "20",
        })
        op = Oportunidade.objects.filter(pagina_captacao=pag).first()
        self.assertEqual(op.hospedes, 8)

    def test_faq_parseia_pares(self):
        pag = self._pagina(faq_texto="P: Aceita pet?\nR: Sim.\n\nP: Tem café?\nR: Tem.")
        itens = pag.faq_itens
        self.assertEqual(len(itens), 2)
        self.assertEqual(itens[0]["pergunta"], "Aceita pet?")
        self.assertEqual(itens[0]["resposta"], "Sim.")


class PropriedadeLeadTests(TestCase):
    """Regra: todos veem todos; o primeiro que interage/pega assume o lead."""

    def setUp(self):
        self.v1 = Usuario.objects.create_superuser(username="vend1", password="forte-123-abc")
        self.v2 = Usuario.objects.create_superuser(username="vend2", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Lead Órfão", telefone="(49) 99123-4567")
        self.op = services.criar_oportunidade(
            usuario=self.v1, pessoa=self.pessoa, titulo="Órfão", responsavel=None)

    def test_lead_do_site_nasce_sem_dono(self):
        self.assertIsNone(self.op.responsavel)

    def test_primeiro_a_interagir_assume_e_segundo_nao_toma(self):
        self.assertTrue(services.assumir_lead(self.op, self.v1))
        self.op.refresh_from_db()
        self.assertEqual(self.op.responsavel, self.v1)
        self.assertFalse(services.assumir_lead(self.op, self.v2))
        self.op.refresh_from_db()
        self.assertEqual(self.op.responsavel, self.v1)

    def test_usuario_de_sistema_nao_assume(self):
        self.assertFalse(services.assumir_lead(self.op, services._usuario_site()))
        self.op.refresh_from_db()
        self.assertIsNone(self.op.responsavel)

    def test_registrar_atividade_assume_o_lead(self):
        from .models import AtividadeComercial
        services.registrar_atividade(
            oportunidade=self.op, usuario=self.v2,
            tipo=AtividadeComercial.Tipo.NOTA, descricao="primeiro contato")
        self.op.refresh_from_db()
        self.assertEqual(self.op.responsavel, self.v2)

    def test_whatsapp_url_do_telefone(self):
        # Deep link que abre o app direto (sem a página api.whatsapp.com).
        self.assertTrue(self.op.whatsapp_url.startswith("whatsapp://send?phone=55"))

    def test_view_assumir(self):
        self.client.login(username="vend2", password="forte-123-abc")
        self.client.post(reverse("comercial:assumir", args=[self.op.pk]))
        self.op.refresh_from_db()
        self.assertEqual(self.op.responsavel, self.v2)

    def test_trilha_registra_quem_assumiu_e_moveu(self):
        """A 'trilha de pão': cada ação vira evento de sistema com autor."""
        from .models import AtividadeComercial
        services.assumir_lead(self.op, self.v1)
        negociacao = EtapaFunil.objects.get(nome="Negociação")
        services.mover_etapa(self.op, negociacao, self.v1)
        eventos = AtividadeComercial.objects.filter(
            oportunidade=self.op, tipo=AtividadeComercial.Tipo.SISTEMA
        ).order_by("id")
        descricoes = [e.descricao for e in eventos]
        self.assertIn("assumiu o lead", descricoes)
        self.assertTrue(any("moveu:" in d and "Negociação" in d for d in descricoes))
        self.assertTrue(all(e.criado_por == self.v1 for e in eventos))

    def test_trilha_ignora_usuario_de_sistema(self):
        from .models import AtividadeComercial
        services._log_evento(self.op, services._usuario_site(), "não deveria aparecer")
        self.assertFalse(AtividadeComercial.objects.filter(
            oportunidade=self.op, tipo=AtividadeComercial.Tipo.SISTEMA).exists())


class ImpulsionamentoTests(TestCase):
    """Fase A: atribuição de anúncio + gasto manual + painel."""

    def setUp(self):
        from .models import Campanha, PaginaCaptacao
        self.op = Usuario.objects.create_superuser(username="mkt", password="forte-123-abc")
        self.pag = PaginaCaptacao.objects.create(
            nome="Fundador", slug="fundador",
            status=PaginaCaptacao.Status.PUBLICADA, hero_titulo="Oi", criado_por=self.op)
        self.camp = Campanha.objects.create(
            nome="Inauguração Meta Casais", codigo="fundador-meta",
            provedor=Campanha.Provedor.META, pagina_captacao=self.pag, criado_por=self.op)

    def test_captura_grava_rastreio_e_casa_campanha(self):
        op = services.capturar_lead_site(
            nome="Lead Ads", telefone="49999990000",
            origem={"utm_campaign": "fundador-meta", "utm_source": "meta",
                    "fbclid": "abc123", "gclid": ""})
        self.assertEqual(op.campanha, self.camp)
        self.assertEqual(op.origem_rastreio.get("fbclid"), "abc123")
        self.assertNotIn("gclid", op.origem_rastreio)  # vazios não gravam

    def test_utm_desconhecido_nao_casa(self):
        op = services.capturar_lead_site(
            nome="Sem Camp", telefone="49999990001",
            origem={"utm_campaign": "inexistente"})
        self.assertIsNone(op.campanha)

    def test_metricas_custo_e_retorno(self):
        services.registrar_gasto(campanha=self.camp, data=timezone.localdate(),
                                 valor="100.00", usuario=self.op)
        a = services.criar_oportunidade(usuario=self.op, campanha=self.camp,
            pessoa=Pessoa.objects.create(nome="L1"), titulo="l1")
        services.criar_oportunidade(usuario=self.op, campanha=self.camp,
            pessoa=Pessoa.objects.create(nome="L2"), titulo="l2")
        Oportunidade.objects.filter(pk=a.pk).update(
            status=Oportunidade.Status.GANHA, valor_estimado=Decimal("1000.00"))
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.leads, 2)
        self.assertEqual(self.camp.custo_por_lead, Decimal("50.00"))
        self.assertEqual(self.camp.reservas, 1)
        self.assertEqual(self.camp.retorno, Decimal("10.00"))


class ConversaoMidiaTests(TestCase):
    """Fase B: devolver conversões (lead/compra) ao provedor (simulado nos testes)."""

    def setUp(self):
        self.u = Usuario.objects.create_superuser(username="conv", password="forte-123-abc")

    def _lead_com_clique(self):
        pessoa = Pessoa.objects.create(nome="Pago", email="pago@ex.com", telefone="49999990000")
        return services.criar_oportunidade(
            usuario=self.u, pessoa=pessoa, titulo="pago",
            origem_rastreio={"fbclid": "abc", "landing_url": "https://x/y"})

    def test_envia_lead_simulado(self):
        from .models import ConversaoEnviada
        ce = services.enviar_conversao(self._lead_com_clique(), "lead")
        self.assertIsNotNone(ce)
        self.assertEqual(ce.status, ConversaoEnviada.Status.ENVIADA)
        self.assertEqual(ce.evento, "lead")

    def test_sem_clique_nao_envia(self):
        op = services.criar_oportunidade(
            usuario=self.u, pessoa=Pessoa.objects.create(nome="Organico"), titulo="org")
        self.assertIsNone(services.enviar_conversao(op, "lead"))

    def test_idempotente_e_forcar(self):
        op = self._lead_com_clique()
        services.enviar_conversao(op, "lead")
        self.assertIsNone(services.enviar_conversao(op, "lead"))       # já enviada
        self.assertIsNotNone(services.enviar_conversao(op, "lead", forcar=True))  # reenvio

    def test_compra_com_valor(self):
        op = self._lead_com_clique()
        ce = services.enviar_conversao(op, "compra", valor=Decimal("1400.00"))
        self.assertEqual(ce.evento, "compra")
        self.assertEqual(ce.valor, Decimal("1400.00"))

    def test_hash_pii(self):
        from .midia_gateways import hash_email, hash_telefone
        self.assertEqual(len(hash_email("a@b.com")), 64)
        self.assertEqual(hash_email(""), "")
        self.assertTrue(hash_telefone("(49) 99999-0000"))
        self.assertEqual(hash_telefone(""), "")

    def test_hook_lead_no_captura(self):
        from .models import ConversaoEnviada
        with self.captureOnCommitCallbacks(execute=True):
            services.capturar_lead_site(
                nome="Clicou", telefone="49999991111",
                origem={"fbclid": "qq", "utm_campaign": "x"})
        self.assertTrue(ConversaoEnviada.objects.filter(evento="lead").exists())

    def test_reenviar_view(self):
        from .models import ConversaoEnviada
        op = self._lead_com_clique()
        self.client.force_login(self.u)
        self.client.post(reverse("comercial:conversao_reenviar", args=[op.pk]))
        self.assertTrue(ConversaoEnviada.objects.filter(oportunidade=op).exists())


class SincronizarGastoTests(TestCase):
    """Fase C: puxar gasto das plataformas (simulado = no-op nos testes)."""

    def setUp(self):
        from .models import Campanha
        self.u = Usuario.objects.create_superuser(username="sinc", password="forte-123-abc")
        self.camp = Campanha.objects.create(
            nome="Meta Sync", codigo="meta-sync", provedor=Campanha.Provedor.META,
            id_externo="123456", criado_por=self.u)

    def test_upsert_idempotente_por_dia(self):
        import datetime

        from .models import GastoDiario
        d = datetime.date(2026, 9, 1)
        n = services._upsert_gastos_sincronizados(self.camp, [{"data": d, "valor": "120.00"}])
        self.assertEqual(n, 1)
        services._upsert_gastos_sincronizados(self.camp, [{"data": d, "valor": "150.00"}])
        self.assertEqual(
            GastoDiario.objects.filter(campanha=self.camp, origem="sincronizado").count(), 1)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.gasto_total, Decimal("150.00"))

    def test_sincronizar_simulado_noop(self):
        self.assertEqual(services.sincronizar_gastos(campanha=self.camp), 0)


class WhatsAppMVPTests(TestCase):
    """MVP simulado: conversa no funil + respostas rápidas."""

    def setUp(self):
        self.u = Usuario.objects.create_superuser(username="wpp", password="forte-123-abc")
        self.v2 = Usuario.objects.create_superuser(username="wpp2", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Kelly Mazzocco", telefone="49991234567")
        self.op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Lead WhatsApp", responsavel=None)

    def test_receber_abre_janela_e_conta_nao_lida(self):
        m = services.receber_mensagem_whatsapp(oportunidade=self.op, texto="Oi, tem quarto?")
        self.assertEqual(m.direcao, "entrada")
        conv = self.op.conversa_whatsapp
        self.assertTrue(conv.janela_aberta)
        self.assertEqual(conv.nao_lidas, 1)

    def test_receber_idempotente_por_id_externo(self):
        services.receber_mensagem_whatsapp(oportunidade=self.op, texto="a", id_externo="X1")
        services.receber_mensagem_whatsapp(oportunidade=self.op, texto="a", id_externo="X1")
        self.assertEqual(self.op.conversa_whatsapp.mensagens.count(), 1)

    def test_enviar_cria_saida_e_assume_lead(self):
        conv = services.abrir_conversa_whatsapp(self.op)
        m = services.enviar_mensagem_whatsapp(conversa=conv, texto="Olá!", usuario=self.v2)
        self.assertEqual(m.direcao, "saida")
        self.assertEqual(m.status, "enviada")  # simulado
        self.op.refresh_from_db()
        self.assertEqual(self.op.responsavel, self.v2)  # quem responde primeiro assume

    def test_variaveis_da_resposta(self):
        from datetime import date
        self.op.checkin_previsto = date(2026, 10, 31)
        self.op.checkout_previsto = date(2026, 11, 2)
        self.op.save()
        txt = services.aplicar_variaveis_resposta(
            "Oi {nome}, {checkin}→{checkout} = {noites} noites", self.op)
        self.assertEqual(txt, "Oi Kelly, 31/10→02/11 = 2 noites")

    def test_views_enviar_e_simular(self):
        self.client.force_login(self.u)
        self.client.post(reverse("comercial:whatsapp_simular", args=[self.op.pk]),
                         {"texto": "quero reservar"})
        self.client.post(reverse("comercial:whatsapp_enviar", args=[self.op.pk]),
                         {"texto": "claro!"})
        conv = self.op.conversa_whatsapp
        self.assertEqual(conv.mensagens.filter(direcao="entrada").count(), 1)
        self.assertEqual(conv.mensagens.filter(direcao="saida").count(), 1)

    def test_crud_resposta_rapida(self):
        self.client.force_login(self.u)
        self.client.post(reverse("comercial:resposta_nova"),
                         {"titulo": "Oi", "texto": "Olá {nome}", "ordem": "0", "ativo": "on"})
        from .models import RespostaRapida
        self.assertTrue(RespostaRapida.objects.filter(titulo="Oi").exists())


@override_settings(EMAIL_ENVIO_ASSINCRONO=False)
class EmailLeadTests(TestCase):
    """Fase 1 — trilho 1:1: montar o e-mail da proposta + enviar do lead (simulado).

    Envio fixado em síncrono para asserção determinística (produção usa thread de fundo).
    """

    def setUp(self):
        self.u = Usuario.objects.create_superuser(
            username="mail", password="forte-123-abc", email="vend@pousadavotesta.com.br")
        self.pessoa = Pessoa.objects.create(
            nome="Daniela Alves", telefone="49999990000", email="daniela@ex.com")
        self.op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Proposta",
            responsavel=None, valor_estimado=Decimal("800.00"))
        self.op.checkin_previsto = timezone.localdate()
        self.op.checkout_previsto = timezone.localdate() + timedelta(days=2)
        self.op.hospedes = 4
        self.op.save()

    def test_montar_email_formata_cartao_e_assunto(self):
        d = services.montar_proposta_email(self.op)
        self.assertIn("Pousada Vô Testa", d["assunto"])
        self.assertIn("R$ 800,00", d["html"])          # total em BRL no cartão
        self.assertIn("Oi, Daniela", d["corpo"])        # saudação personalizada
        self.assertNotIn("Sinal para garantir", d["html"])  # sem cobrança → sem sinal

    def test_montar_email_com_cobranca_mostra_sinal_e_restante(self):
        from types import SimpleNamespace
        cob = SimpleNamespace(valor=Decimal("240.00"))
        d = services.montar_proposta_email(self.op, cobranca=cob, link="http://x/p/1")
        self.assertIn("R$ 240,00", d["html"])           # sinal
        self.assertIn("R$ 560,00", d["html"])           # restante = 800 - 240
        self.assertIn("http://x/p/1", d["html"])        # botão de pagamento

    def test_email_tem_links_de_resposta(self):
        d = services.montar_proposta_email(self.op)
        self.assertIn("https://wa.me/", d["html"])          # botão WhatsApp
        self.assertIn("Responder no WhatsApp", d["html"])
        self.assertIn("mailto:", d["html"])                 # botão responder por e-mail
        self.assertIn("wa.me/", d["texto"])                 # também no fallback texto

    def test_resumo_da_conversa(self):
        conv = services.abrir_conversa_whatsapp(self.op)
        services.enviar_mensagem_whatsapp(conversa=conv, texto="Café incluso?", usuario=self.u)
        r = services.resumo_da_conversa(self.op)
        self.assertTrue(any("Café incluso?" in m["texto"] for m in r))

    def test_resumo_vazio_sem_conversa(self):
        self.assertEqual(services.resumo_da_conversa(self.op), [])

    def test_enviar_email_grava_envio_e_trilha(self):
        from django.core import mail

        from .models import AtividadeComercial, EnvioEmail
        d = services.montar_proposta_email(self.op)
        envio = services.enviar_email(
            para=self.pessoa.email, assunto=d["assunto"], html=d["html"],
            texto=d["texto"], usuario=self.u, oportunidade=self.op)
        self.assertEqual(envio.status, EnvioEmail.Status.ENVIADO)
        self.assertTrue(envio.message_id)
        self.assertEqual(len(mail.outbox), 1)           # simulado usa o backend do Django
        self.assertEqual(mail.outbox[0].to, ["daniela@ex.com"])
        self.assertTrue(AtividadeComercial.objects.filter(
            oportunidade=self.op, tipo=AtividadeComercial.Tipo.SISTEMA,
            descricao__startswith="enviou e-mail").exists())

    @override_settings(EMAIL_GATEWAY="ses")
    def test_gateway_ses_stub_vira_erro_sem_derrubar(self):
        from .models import EnvioEmail
        d = services.montar_proposta_email(self.op)
        envio = services.enviar_email(
            para=self.pessoa.email, assunto=d["assunto"], html=d["html"],
            texto=d["texto"], usuario=self.u, oportunidade=self.op)
        self.assertEqual(envio.status, EnvioEmail.Status.ERRO)
        self.assertIn("ses", envio.erro.lower())

    def test_view_preview_get(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("comercial:enviar_email_lead", args=[self.op.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enviar por e-mail")

    def test_view_enviar_ao_lead(self):
        from .models import EnvioEmail
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:enviar_email_lead", args=[self.op.pk]),
                             {"acao": "enviar", "assunto": "Oi", "corpo": "texto",
                              "destinatario": self.pessoa.email})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(EnvioEmail.objects.filter(
            oportunidade=self.op, status=EnvioEmail.Status.ENVIADO).exists())

    def test_view_enviar_salva_email_no_cadastro(self):
        """Lead sem e-mail: o campo preenchido é salvo no contato ao enviar."""
        from .models import EnvioEmail
        self.pessoa.email = ""
        self.pessoa.save()
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:enviar_email_lead", args=[self.op.pk]),
                             {"acao": "enviar", "assunto": "Oi", "corpo": "t",
                              "destinatario": "novo@contato.com"})
        self.assertEqual(r.status_code, 302)
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.email, "novo@contato.com")   # salvo no cadastro
        self.assertTrue(EnvioEmail.objects.filter(
            oportunidade=self.op, email="novo@contato.com",
            status=EnvioEmail.Status.ENVIADO).exists())

    def test_view_enviar_sem_destinatario_nao_envia(self):
        from .models import EnvioEmail
        self.pessoa.email = ""
        self.pessoa.save()
        self.client.force_login(self.u)
        self.client.post(reverse("comercial:enviar_email_lead", args=[self.op.pk]),
                         {"acao": "enviar", "assunto": "Oi", "corpo": "t",
                          "destinatario": ""})
        self.assertFalse(EnvioEmail.objects.filter(oportunidade=self.op).exists())
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.email, "")

    # ── Fase 2: templates de e-mail ─────────────────────────────────────────
    def test_aplicar_template_preenche_variaveis(self):
        from .models import TemplateEmail
        t = TemplateEmail.objects.create(
            nome="Oi", assunto="Proposta {quarto}",
            corpo="Oi, {primeiro_nome}! {noites} noite(s).", criado_por=self.u)
        assunto, corpo = services.aplicar_template_email(t, self.op)
        self.assertIn("Daniela", corpo)          # {primeiro_nome} → Daniela
        self.assertNotIn("{primeiro_nome}", corpo)
        self.assertNotIn("{quarto}", assunto)

    def test_salvar_template_reverte_primeiro_nome(self):
        """Salvar do lead troca o 1º nome por {primeiro_nome} p/ reutilizar."""
        t = services.salvar_template_email(
            nome="Meu", assunto="Oi Daniela",
            corpo="Oi, Daniela! tudo bem?", oportunidade=self.op, usuario=self.u)
        self.assertIn("{primeiro_nome}", t.corpo)
        self.assertNotIn("Daniela", t.corpo)

    def test_view_aplica_template_no_corpo(self):
        from .models import TemplateEmail
        t = TemplateEmail.objects.create(
            nome="T", assunto="A {quarto}", corpo="Olá {primeiro_nome}!",
            criado_por=self.u)
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:enviar_email_lead", args=[self.op.pk]),
                             {"acao": "template", "template": str(t.pk)})
        self.assertContains(r, "Olá Daniela!")   # corpo do template aplicado ao lead

    def test_view_salvar_template_cria_registro(self):
        from .models import TemplateEmail
        self.client.force_login(self.u)
        self.client.post(reverse("comercial:enviar_email_lead", args=[self.op.pk]),
                         {"acao": "salvar_template", "template_nome": "Novo T",
                          "assunto": "Assunto X", "corpo": "corpo Y"})
        self.assertTrue(TemplateEmail.objects.filter(nome="Novo T").exists())

    def test_biblioteca_crud(self):
        from .models import TemplateEmail
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:email_template_novo"),
                             {"nome": "CRUD", "assunto": "S", "corpo": "C", "ativo": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(TemplateEmail.objects.filter(nome="CRUD").exists())


class CampanhaEmailTests(TestCase):
    """Fase 3 — campanha por segmento + opt-in/descadastro (LGPD)."""

    def setUp(self):
        self.u = Usuario.objects.create_superuser(
            username="camp", password="forte-123-abc", email="v@ex.com")
        self.p1 = Pessoa.objects.create(nome="Ana", email="ana@ex.com", telefone="1")
        self.p2 = Pessoa.objects.create(nome="Bia", email="bia@ex.com", telefone="2")
        self.op1 = services.criar_oportunidade(usuario=self.u, pessoa=self.p1, titulo="A")
        self.op2 = services.criar_oportunidade(usuario=self.u, pessoa=self.p2, titulo="B")

    def _campanha(self, **seg):
        return services.criar_campanha_email(
            nome="Lançamento", assunto="Oi {primeiro_nome}", corpo="Novidade!",
            segmento=seg, usuario=self.u)

    def test_publico_exclui_optout_e_sem_email(self):
        self.p2.aceita_email = False
        self.p2.save()
        pub = list(services.publico_da_campanha({}))
        self.assertIn(self.p1, pub)
        self.assertNotIn(self.p2, pub)      # descadastrado fora

    def test_publico_exclui_bounce(self):
        from .models import EnvioEmail
        EnvioEmail.objects.create(email="ana@ex.com", assunto="x",
                                  status=EnvioEmail.Status.BOUNCE)
        pub = list(services.publico_da_campanha({}))
        self.assertNotIn(self.p1, pub)      # e-mail devolvido fora

    def test_descadastro_por_token(self):
        self.assertTrue(self.p1.aceita_email)
        p = services.descadastrar_por_token(self.p1.unsub_token)
        self.assertEqual(p, self.p1)
        self.p1.refresh_from_db()
        self.assertFalse(self.p1.aceita_email)
        self.assertIsNotNone(self.p1.email_descadastro_em)

    def test_montar_campanha_tem_descadastro_e_header(self):
        c = self._campanha()
        d = services.montar_email_campanha(c, self.p1)
        self.assertIn("descadastrar", d["html"].lower())
        self.assertIn("List-Unsubscribe", d["headers"])
        self.assertIn("Oi Ana", d["assunto"])   # variável aplicada

    def test_enviar_campanha_idempotente(self):
        from django.core import mail

        from .models import CampanhaEmail, EnvioEmail
        c = self._campanha()
        services.enviar_campanha_email(c, usuario=self.u)
        c.refresh_from_db()
        self.assertEqual(c.status, CampanhaEmail.Status.ENVIADA)
        self.assertEqual(c.enviados, 2)
        self.assertEqual(len(mail.outbox), 2)
        # 2º disparo não reenvia
        mail.outbox.clear()
        services.enviar_campanha_email(c, usuario=self.u)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            EnvioEmail.objects.filter(campanha=c, status="enviado").count(), 2)

    def test_view_descadastro_publico(self):
        r = self.client.get(reverse("email_publico:descadastrar",
                                    args=[self.p1.unsub_token]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "descadastrado")
        self.p1.refresh_from_db()
        self.assertFalse(self.p1.aceita_email)

    def test_view_criar_e_enviar_campanha(self):
        from django.core import mail

        from .models import CampanhaEmail
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:email_campanha_nova"),
                             {"nome": "C1", "assunto": "Oi", "corpo": "corpo"})
        self.assertEqual(r.status_code, 302)
        c = CampanhaEmail.objects.get(nome="C1")
        mail.outbox.clear()
        self.client.post(reverse("comercial:email_campanha_enviar", args=[c.pk]))
        c.refresh_from_db()
        self.assertEqual(c.status, "enviada")
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_consentimento_da_lp_grava_optin(self):
        op = services.capturar_lead_site(
            nome="Novo Lead", email="novo@ex.com", telefone="9", aceita_email=True)
        self.assertTrue(op.pessoa.aceita_email)
        self.assertIsNotNone(op.pessoa.email_optin_em)


@override_settings(PAGAMENTOS_GATEWAY="simulado")
class PropostaSinalTests(TestCase):
    """Ação 'Enviar proposta + sinal': cria cobrança (simulado) + envia no WhatsApp.

    Fixa o gateway simulado para não bater na rede (o .env pode estar em safrapay/HML).
    """

    def setUp(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.PAGAMENTOS, defaults={"ativo": True})
        self.u = Usuario.objects.create_superuser(username="prop", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Ana Sinal", telefone="49999990000")
        self.op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Sinal", responsavel=None,
            valor_estimado=Decimal("585.00"))

    def test_gera_cobranca_e_envia_whatsapp(self):
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:enviar_proposta_sinal", args=[self.op.pk]))
        self.assertEqual(r.status_code, 302)
        self.op.refresh_from_db()
        self.assertIsNotNone(self.op.cobranca_sinal_id)  # cobrança criada e vinculada
        self.assertTrue(
            self.op.conversa_whatsapp.mensagens.filter(direcao="saida").exists())  # link no WhatsApp

    def test_servico_calcula_30_por_cento(self):
        cob = services.criar_cobranca_sinal(self.op, self.u)
        self.assertEqual(cob.valor, Decimal("175.50"))  # 30% de 585

    def test_sinal_idempotente_cancela_anterior(self):
        # Reemitir o sinal não pode deixar dois links pagáveis (pagamento em dobro).
        from apps.pagamentos.models import Cobranca
        c1 = services.criar_cobranca_sinal(self.op, self.u)
        self.op.refresh_from_db()
        c2 = services.criar_cobranca_sinal(self.op, self.u)  # reemitido
        c1.refresh_from_db()
        self.assertEqual(c1.status, Cobranca.Status.CANCELADO)
        self.assertEqual(c2.status, Cobranca.Status.PENDENTE)
        self.assertEqual(
            Cobranca.objects.filter(finalidade=Cobranca.Finalidade.SINAL,
                                    status=Cobranca.Status.PENDENTE).count(), 1)

    def test_copy_da_proposta_e_calorosa_e_formata_brl(self):
        from types import SimpleNamespace
        cob = SimpleNamespace(valor=Decimal("175.50"))  # só o valor importa p/ a copy
        texto = services.montar_proposta_sinal(self.op, cob, "http://x/pagar/abc")
        self.assertIn("Oi, Ana", texto)                     # personalizado no topo
        self.assertIn("*Pousada Vô Testa*", texto)          # marca em destaque
        self.assertIn("*R$ 175,50*", texto)                 # sinal herói em BRL
        self.assertIn("na chegada", texto)                  # reduz fricção (resto depois)
        self.assertIn("http://x/pagar/abc", texto)          # CTA único com o link

    def test_brl_usa_separador_de_milhar(self):
        self.assertEqual(services._brl(Decimal("1500")), "1.500,00")
        self.assertEqual(services._brl(Decimal("450.5")), "450,50")


class TelefoneIncompletoAuditoriaTests(TestCase):
    """Auditoria acusa leads com telefone incompleto/inválido (passivo)."""

    def _op(self, telefone):
        pessoa = Pessoa.objects.create(nome="Lead Tel", telefone=telefone)
        u = Usuario.objects.create_superuser(
            username=f"ta{telefone or 'x'}", password="forte-123-abc")
        return services.criar_oportunidade(usuario=u, pessoa=pessoa, titulo="T")

    def test_acusa_incompleto_e_ignora_valido(self):
        self._op("4999999")          # incompleto → acusa
        tipos = [a["tipo"] for a in services.pendencias_auditoria()]
        self.assertIn("telefone_incompleto", tipos)

    def test_celular_e_fixo_validos_nao_acusam(self):
        self._op("49999887766")      # celular ok
        self._op("4933887766")       # fixo ok (aceitar_fixo)
        achados = [a for a in services.pendencias_auditoria()
                   if a["tipo"] == "telefone_incompleto"]
        self.assertEqual(achados, [])


class PerdaComRelatoTests(TestCase):
    """Motivo 'Dados incompletos' (seed) + relato opcional da perda."""

    def setUp(self):
        self.u = Usuario.objects.create_superuser(username="pr", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Lead Perda")
        self.op = services.criar_oportunidade(usuario=self.u, pessoa=self.pessoa, titulo="P")

    def test_motivo_dados_incompletos_semeado_e_ativo(self):
        m = MotivoPerda.objects.filter(nome="Dados incompletos").first()
        self.assertIsNotNone(m)
        self.assertTrue(m.ativo)

    def test_marcar_perdida_grava_relato(self):
        m = MotivoPerda.objects.get(nome="Dados incompletos")
        services.marcar_perdida(self.op, m, self.u,
                                detalhe="telefone deu número errado 3×")
        self.op.refresh_from_db()
        self.assertEqual(self.op.status, Oportunidade.Status.PERDIDA)
        self.assertEqual(self.op.motivo_perda, m)
        self.assertEqual(self.op.motivo_perda_detalhe, "telefone deu número errado 3×")

    def test_relato_opcional(self):
        m = MotivoPerda.objects.filter(nome="Outro").first() or \
            MotivoPerda.objects.create(nome="Outro")
        services.marcar_perdida(self.op, m, self.u)  # sem detalhe
        self.op.refresh_from_db()
        self.assertEqual(self.op.motivo_perda_detalhe, "")


class UltimoContatoTests(TestCase):
    """Card do funil mostra o último CONTATO REAL (não sistema/tarefa)."""

    def setUp(self):
        self.u = Usuario.objects.create_superuser(username="uc", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Lead Contato")
        self.op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Contato")

    def _atv(self, tipo, descricao, concluida=True):
        return AtividadeComercial.objects.create(
            oportunidade=self.op, tipo=tipo, descricao=descricao,
            quando=timezone.now(), criado_por=self.u, concluida=concluida)

    def test_ignora_sistema_e_tarefa_pega_contato_real(self):
        self._atv(AtividadeComercial.Tipo.SISTEMA, "Ofereceu Quarto 09")
        self._atv(AtividadeComercial.Tipo.TAREFA, "Ligar amanhã", concluida=False)
        alvo = self._atv(AtividadeComercial.Tipo.WHATSAPP, "Enviou proposta no WhatsApp")
        self.assertEqual(self.op.ultimo_contato, alvo)

    def test_sem_contato_real_retorna_none(self):
        self._atv(AtividadeComercial.Tipo.SISTEMA, "Converteu em reserva")
        self.assertIsNone(self.op.ultimo_contato)

    def test_pega_o_mais_recente(self):
        self._atv(AtividadeComercial.Tipo.LIGACAO, "Primeira ligação",
                  ).__class__.objects.filter(descricao="Primeira ligação").update(
            quando=timezone.now() - timedelta(days=2))
        recente = self._atv(AtividadeComercial.Tipo.NOTA, "Nota de hoje")
        self.assertEqual(self.op.ultimo_contato, recente)


class SinalPagoGanhaTests(TestCase):
    """#9 — sinal pago numa oportunidade aberta → ganha e cria a reserva sozinho."""

    def setUp(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        for mod in (Modulo.PAGAMENTOS, Modulo.RESERVAS, Modulo.COMERCIAL):
            ModuloContratado.objects.update_or_create(codigo=mod, defaults={"ativo": True})
        self.u = Usuario.objects.create_superuser(username="s9", password="forte-123-abc")
        self.pessoa = Pessoa.objects.create(nome="Rui Sinal", telefone="49988887777")
        self.tipo = TipoUH.objects.create(nome="Std9", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 09", tipo=self.tipo)
        self.hoje = timezone.localdate()

    def _cobranca_paga(self, op):
        from apps.pagamentos.services import confirmar_pagamento
        cob = services.criar_cobranca_sinal(op, self.u)
        return confirmar_pagamento(cob, self.u, origem="teste")

    def test_sinal_pago_converte_e_confirma(self):
        from apps.reservas.models import Reserva
        op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Ganha por sinal",
            valor_estimado=Decimal("585.00"))
        services.registrar_cotacao(
            oportunidade=op, usuario=self.u, tipo_uh=self.tipo,
            checkin=self.hoje + timedelta(days=5), checkout=self.hoje + timedelta(days=7))
        op.refresh_from_db()
        self._cobranca_paga(op)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.GANHA)
        self.assertIsNotNone(op.reserva_id)
        reserva = Reserva.objects.get(pk=op.reserva_id)
        self.assertEqual(reserva.status, Reserva.Status.CONFIRMADA)

    def test_quarto_indisponivel_no_pagamento_nao_quebra_o_pagamento(self):
        # Entre a cotação e o pagamento, o único quarto do tipo é reservado por outro
        # canal. Pagar o sinal NÃO pode derrubar a confirmação do pagamento.
        from apps.pagamentos.models import Cobranca
        from apps.reservas import services as reservas
        from apps.reservas.models import Reserva
        op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Quarto some",
            valor_estimado=Decimal("585.00"))
        ci, co = self.hoje + timedelta(days=5), self.hoje + timedelta(days=7)
        services.registrar_cotacao(
            oportunidade=op, usuario=self.u, tipo_uh=self.tipo, checkin=ci, checkout=co)
        # ocupa o único quarto do tipo nessas datas (outro hóspede)
        outro = Pessoa.objects.create(nome="Outro Hóspede")
        reservas.criar_prereserva(
            uh=self.uh, checkin=ci, checkout=co, hospede=outro, usuario=self.u)
        cob = self._cobranca_paga(op)
        self.assertEqual(cob.status, Cobranca.Status.PAGO)   # pagamento intacto
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)  # não converteu
        self.assertIsNone(op.reserva_id)
        self.assertTrue(
            op.atividades.filter(descricao__icontains="não foi possível").exists())

    def test_sem_datas_apenas_registra_para_conversao_manual(self):
        op = services.criar_oportunidade(
            usuario=self.u, pessoa=self.pessoa, titulo="Sinal sem datas",
            valor_estimado=Decimal("300.00"))
        self._cobranca_paga(op)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)  # não converteu
        self.assertIsNone(op.reserva_id)
        self.assertTrue(
            op.atividades.filter(descricao__icontains="manualmente").exists())


class PainelQuartosLeadTests(TestCase):
    """Descritivo na conversa: comporta(), painel filtrado, texto de oferta, views."""

    def setUp(self):
        from apps.nucleo.models import ConfiguracaoUH, PosicaoCama

        self.user = Usuario.objects.create_superuser(
            username="vend", password="senha-forte-123")
        self.pessoa = Pessoa.objects.create(nome="Família Souza", telefone="49999990000")
        self.etapa = EtapaFunil.objects.get(nome="Novo lead")
        # Quarto tipo "Q09": 1 posição (fixa 2) + sofá (1 ad / 2 cr) + 1 colchão extra
        self.tipo = TipoUH.objects.create(nome="Intermediário", tarifa_base=Decimal("400"))
        self.uh = UH.objects.create(
            numero="Quarto 09", tipo=self.tipo, nome_tematico="Estúdio da Cartógrafa")
        PosicaoCama.objects.create(uh=self.uh, nome="Quarto", montagem_padrao="casal", ordem=0)
        ConfiguracaoUH.objects.create(
            uh=self.uh, tem_sofa_cama=True, sofa_adultos=1, sofa_criancas=2,
            sofa_idade_maxima=15, max_colchoes_extras=1)
        self.op = Oportunidade.objects.create(
            pessoa=self.pessoa, titulo="Feriadão", etapa=self.etapa,
            adultos=3, criancas=2, idades_criancas=[8, 12], hospedes=5,
            responsavel=self.user, criado_por=self.user,
        )

    # ---- comporta() ----
    def test_comporta_composicoes_do_descritivo(self):
        from apps.comercial import quartos
        self.assertTrue(quartos.comporta(self.uh, 3, 2, [8, 12]))   # 3ad + 2cr no sofá
        self.assertTrue(quartos.comporta(self.uh, 4, 0, []))        # 4 adultos = máx
        self.assertFalse(quartos.comporta(self.uh, 5, 0, []))       # passa da máx

    def test_crianca_acima_do_limite_conta_como_adulto(self):
        from apps.comercial import quartos
        # 2 adultos + 1 criança de 16 = 3 adultos → cabe (máx 4)
        self.assertTrue(quartos.comporta(self.uh, 2, 1, [16]))
        # 4 adultos + 1 criança de 16 = 5 adultos → não cabe
        self.assertFalse(quartos.comporta(self.uh, 4, 1, [16]))

    def test_frase_capacidade_formato_descritivo(self):
        from apps.comercial import quartos
        self.assertEqual(
            quartos.frase_capacidade(self.uh),
            "4 adultos, ou 3 adultos + 2 crianças até 15 anos",
        )

    # ---- preço pela motor (Fase A — religar funil) ----
    @override_settings(PRECO_ISS_ALIQUOTA="4.0", PRECO_TAXA_TURISMO_DIARIA="4.00",
                       PRECO_SINGLE_FATOR="0.70")
    def test_card_precifica_pela_motor_com_pessoa_adicional_e_taxas(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.comercial import quartos
        from apps.reservas import precos

        self.tipo.pessoa_adicional = Decimal("90.00")
        self.tipo.save(update_fields=["pessoa_adicional"])
        ci = timezone.localdate() + timedelta(days=20)
        self.op.checkin_previsto, self.op.checkout_previsto = ci, ci + timedelta(days=2)
        self.op.save(update_fields=["checkin_previsto", "checkout_previsto"])

        painel = quartos.quartos_para_lead(self.op)
        card = next(i for i in painel["servem"] if i["uh"].pk == self.uh.pk)
        cot = precos.cotacao(uh=self.uh, checkin=ci, checkout=ci + timedelta(days=2),
                             adultos=3, criancas_0_5=0, criancas_6_15=2)
        # diária = base 400 + (3−2)×90 + 2×(90/2) = 580 (igual à recepção/site).
        self.assertEqual(card["diaria"], Decimal("580.00"))
        self.assertEqual(card["diaria"], cot["media_noite"])
        self.assertEqual(card["total"], cot["total"])       # com ISS + turismo
        self.assertEqual(card["iss"], cot["iss"])

    def test_disponibilidade_respeita_pool_de_colchoes(self):
        # Fase B: quarto que comporta mas sem colchão extra no pool → não disponível.
        from datetime import timedelta

        from django.utils import timezone

        from apps.comercial import quartos
        from apps.reservas.models import ColchoesExtra
        ci = timezone.localdate() + timedelta(days=20)
        self.op.checkin_previsto, self.op.checkout_previsto = ci, ci + timedelta(days=2)
        self.op.save(update_fields=["checkin_previsto", "checkout_previsto"])
        pool = ColchoesExtra.atual()
        pool.quantidade = 5
        pool.save()
        # 3 adultos + 2 crianças no Quarto 09 → 1 colchão extra; com pool, serve.
        painel = quartos.quartos_para_lead(self.op)
        card = next(i for i in painel["servem"] if i["uh"].pk == self.uh.pk)
        self.assertTrue(card["disponivel"])
        self.assertEqual(card["arranjo"]["extra"], 1)
        # Pool esgotado → cai em "ocupados" por falta de colchão (não por reserva).
        pool.quantidade = 0
        pool.save()
        painel = quartos.quartos_para_lead(self.op)
        self.assertFalse(any(i["uh"].pk == self.uh.pk for i in painel["servem"]))
        oc = next(i for i in painel["ocupados"] if i["uh"].pk == self.uh.pk)
        self.assertEqual(oc["motivo"], "sem_colchao")

    # ---- texto de oferta ----
    def test_texto_oferta_sem_atencao_nem_nao_confirmado(self):
        from apps.comercial import quartos
        from apps.comercial.models import FichaComercial
        FichaComercial.objects.create(
            uh=self.uh, resumo="ambiente único e aconchegante",
            pontos_atencao=["acesso por escada"], confirmados=[])
        hoje = timezone.localdate()
        self.op.checkin_previsto = hoje + timedelta(days=10)
        self.op.checkout_previsto = hoje + timedelta(days=12)
        self.op.save()
        texto = quartos.texto_oferta(self.uh, self.op)
        self.assertIn("Estúdio da Cartógrafa", texto)
        self.assertIn("ambiente único", texto)
        self.assertNotIn("escada", texto)          # ponto de atenção não vaza
        self.assertNotIn("não confirmado", texto)
        self.assertNotIn("A LEVANTAR", texto)

    # ---- proposta com 2–3 quartos (#3) ----
    def test_texto_proposta_combina_quartos_numa_mensagem(self):
        from apps.comercial import quartos
        tipo2 = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("300"))
        uh2 = UH.objects.create(numero="Quarto 10", tipo=tipo2, nome_tematico="Vista Lago")
        hoje = timezone.localdate()
        self.op.checkin_previsto = hoje + timedelta(days=10)
        self.op.checkout_previsto = hoje + timedelta(days=12)
        self.op.adultos, self.op.criancas, self.op.idades_criancas = 2, 0, []
        self.op.hospedes = 2
        self.op.save()
        texto = quartos.texto_proposta(self.op, [self.uh.pk, uh2.pk])
        self.assertIn("Família", texto)                 # abertura personalizada
        self.assertIn("Estúdio da Cartógrafa", texto)   # opção 1
        self.assertIn("Vista Lago", texto)              # opção 2
        self.assertIn("*1.", texto)
        self.assertIn("*2.", texto)
        self.assertEqual(texto.lower().count("cancel"), 1)  # política só uma vez

    def test_view_proposta_quartos_json(self):
        self.client.force_login(self.user)
        hoje = timezone.localdate()
        self.op.checkin_previsto = hoje + timedelta(days=10)
        self.op.checkout_previsto = hoje + timedelta(days=12)
        self.op.save()
        resp = self.client.get(
            reverse("comercial:proposta_quartos", args=[self.op.pk]) + f"?uhs={self.uh.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Estúdio da Cartógrafa", resp.json()["texto"])

    # ---- histórico do recorrente (#8) ----
    def test_historico_hospede_conta_estadias_e_futuras(self):
        from apps.reservas import services as reservas
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        # estadia encerrada
        r1 = reservas.criar_prereserva(
            uh=self.uh, checkin=hoje - timedelta(days=30),
            checkout=hoje - timedelta(days=28), hospede=self.pessoa, usuario=self.user)
        r1.status = Reserva.Status.CHECKOUT
        r1.save(update_fields=["status"])
        # reserva futura em aberto
        reservas.criar_prereserva(
            uh=self.uh, checkin=hoje + timedelta(days=20),
            checkout=hoje + timedelta(days=22), hospede=self.pessoa, usuario=self.user)
        h = reservas.historico_hospede(self.pessoa)
        self.assertEqual(h["estadias"], 1)
        self.assertEqual(h["ultima"], hoje - timedelta(days=28))
        self.assertEqual(h["futuras"], 1)

    def test_oportunidade_mostra_selo_recorrente(self):
        from apps.reservas import services as reservas
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        r = reservas.criar_prereserva(
            uh=self.uh, checkin=hoje - timedelta(days=30),
            checkout=hoje - timedelta(days=28), hospede=self.pessoa, usuario=self.user)
        r.status = Reserva.Status.CHECKOUT
        r.save(update_fields=["status"])
        self.client.force_login(self.user)
        resp = self.client.get(reverse("comercial:oportunidade", args=[self.op.pk]))
        self.assertContains(resp, "Cliente recorrente")

    # ---- datas vizinhas quando lota (#5) ----
    def test_datas_vizinhas_quando_lota(self):
        from apps.comercial import quartos
        from apps.reservas import services as reservas
        self.op.adultos, self.op.criancas, self.op.idades_criancas = 2, 0, []
        self.op.hospedes = 2
        hoje = timezone.localdate()
        ci, co = hoje + timedelta(days=10), hoje + timedelta(days=12)
        # ocupa o único quarto na janela desejada → nada serve
        reservas.criar_prereserva(
            uh=self.uh, checkin=ci, checkout=co, hospede=self.pessoa, usuario=self.user)
        self.op.checkin_previsto, self.op.checkout_previsto = ci, co
        self.op.save()
        painel = quartos.quartos_para_lead(self.op)
        self.assertEqual(painel["servem"], [])
        self.assertTrue(painel["datas_alternativas"])            # sugere vizinhas
        self.assertTrue(all(a["qtd"] >= 1 for a in painel["datas_alternativas"]))

    # ---- painel: ocupado não aparece como disponível ----
    def test_quarto_ocupado_vai_para_ocupados(self):
        from apps.comercial import quartos
        from apps.reservas import services as reservas
        hoje = timezone.localdate()
        ci, co = hoje + timedelta(days=10), hoje + timedelta(days=12)
        reservas.criar_prereserva(
            uh=self.uh, checkin=ci, checkout=co, hospede=self.pessoa, usuario=self.user)
        self.op.checkin_previsto, self.op.checkout_previsto = ci, co
        self.op.save()
        painel = quartos.quartos_para_lead(self.op)
        nomes_servem = [i["uh"].pk for i in painel["servem"]]
        nomes_ocup = [i["uh"].pk for i in painel["ocupados"]]
        self.assertNotIn(self.uh.pk, nomes_servem)
        self.assertIn(self.uh.pk, nomes_ocup)

    # ---- views ----
    def test_view_painel_lista_o_quarto(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("comercial:quartos_lead", args=[self.op.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estúdio da Cartógrafa")

    def test_view_editar_composicao_salva(self):
        self.client.force_login(self.user)
        hoje = timezone.localdate()
        resp = self.client.post(
            reverse("comercial:editar_composicao", args=[self.op.pk]),
            {"adultos": 4, "criancas": 2, "idades_criancas": "8, 12",
             "checkin": (hoje + timedelta(days=10)).isoformat(),
             "checkout": (hoje + timedelta(days=12)).isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.op.refresh_from_db()
        self.assertEqual(self.op.adultos, 4)
        self.assertEqual(self.op.criancas, 2)
        self.assertEqual(self.op.idades_criancas, [8, 12])

    def test_view_oferecer_registra_e_devolve_texto(self):
        from apps.comercial.models import AtividadeComercial
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("comercial:oferecer_quarto", args=[self.op.pk, self.uh.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("texto", resp.json())
        self.assertIn("Estúdio da Cartógrafa", resp.json()["texto"])
        self.assertTrue(
            AtividadeComercial.objects.filter(
                oportunidade=self.op, tipo=AtividadeComercial.Tipo.SISTEMA,
                descricao__icontains="Estúdio da Cartógrafa").exists())

    def test_view_oferecer_com_datas_cria_cotacao_e_politica(self):
        # Fase C: com datas, "Enviar ao cliente" registra a cotação (motor) → valor
        # estimado preenche; o texto traz a política de cancelamento.
        from datetime import timedelta

        from django.utils import timezone

        from apps.comercial.models import Cotacao
        ci = timezone.localdate() + timedelta(days=15)
        self.op.checkin_previsto, self.op.checkout_previsto = ci, ci + timedelta(days=2)
        self.op.save(update_fields=["checkin_previsto", "checkout_previsto"])
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("comercial:oferecer_quarto", args=[self.op.pk, self.uh.pk]))
        self.assertTrue(resp.json()["cotou"])
        self.assertIn("Cancelamento", resp.json()["texto"])    # política no texto
        self.op.refresh_from_db()
        self.assertGreater(self.op.valor_estimado, 0)          # valor estimado preenchido
        self.assertTrue(Cotacao.objects.filter(oportunidade=self.op).exists())

    def test_view_comparar_monta_tabela(self):
        # segundo quarto pra comparar
        uh2 = UH.objects.create(
            numero="Quarto 17", tipo=self.tipo, nome_tematico="Torre do Astrônomo",
            vista_lago=True)
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("comercial:comparar_quartos", args=[self.op.pk]),
            {"uhs": f"{self.uh.pk},{uh2.pk}"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estúdio da Cartógrafa")
        self.assertContains(resp, "Torre do Astrônomo")
        self.assertContains(resp, "Capacidade")
        self.assertContains(resp, "Vista para o lago")

    def test_ficha_comercial_form_pontos_por_linha(self):
        from apps.comercial.forms import FichaComercialForm
        from apps.comercial.models import FichaComercial
        ficha = FichaComercial.objects.create(uh=self.uh, pontos_atencao=["a", "b"])
        # prefill: lista → linhas
        self.assertEqual(FichaComercialForm(instance=ficha).fields["pontos_atencao_txt"].initial, "a\nb")
        # save: linhas → lista (ignora linhas vazias e espaços)
        form = FichaComercialForm(
            {"resumo": "x", "indicado_para": "Casal", "historia_e_venda": "",
             "pontos_atencao_txt": "linha1\n\n  linha2  "}, instance=ficha)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(obj.pontos_atencao, ["linha1", "linha2"])

    def test_uh_form_edita_ficha_comercial_num_so_lugar(self):
        """A tela de editar quarto (núcleo) mostra a seção do descritivo comercial."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("uh_editar", args=[self.uh.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Descritivo comercial")
        self.assertContains(resp, "Pontos de atenção")

    def test_campos_a_levantar_reflete_campo_preenchido(self):
        from apps.comercial import quartos
        # vazio → aparece como "a levantar"
        self.assertIn("Banheiro", quartos._campos_a_levantar(self.uh, None))
        # preenchido → some (campo tem casa própria na UH)
        self.uh.banheiro = "1 banheiro com box, chuveiro e secador"
        self.uh.save()
        self.uh.refresh_from_db()
        self.assertNotIn("Banheiro", quartos._campos_a_levantar(self.uh, None))

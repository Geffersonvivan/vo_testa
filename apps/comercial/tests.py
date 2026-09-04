from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, Prospecto, TipoUH

from . import services
from .models import AnaliseLead, EtapaFunil, MotivoPerda, Oportunidade

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

    def test_feedback_marca_revisado(self):
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Fb Lead"), titulo="Fb",
        )
        self.client.force_login(self.user)
        r = self.client.post(reverse("comercial:cacador_feedback", args=[op.pk]), {"util": "1"})
        self.assertEqual(r.status_code, 302)
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertTrue(analise.util)
        self.assertIsNotNone(analise.revisado_em)

    def test_fila_renderiza_lead(self):
        services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Fila Lead"), titulo="Fila",
        )
        self.client.force_login(self.user)
        r = self.client.get(reverse("comercial:cacador"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fila Lead")

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

    def test_badge_novo_no_lead_recente(self):
        services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Recentíssimo"), titulo="r",
        )
        self.client.force_login(self.user)
        r = self.client.get(reverse("comercial:cacador"))
        self.assertContains(r, "cac-novo")

    def test_lead_quente_mostra_chama_e_etapa(self):
        ci = timezone.localdate() + timedelta(days=5)
        op = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Bem Quente"),
            titulo="q", valor_estimado=Decimal("5000"),
            origem=Oportunidade.Origem.INDICACAO,
            checkin_previsto=ci, checkout_previsto=ci + timedelta(days=2),
        )
        analise = AnaliseLead.objects.get(oportunidade=op)
        self.assertEqual(analise.temperatura, AnaliseLead.Temperatura.QUENTE)
        self.client.force_login(self.user)
        r = self.client.get(reverse("comercial:cacador"))
        self.assertContains(r, "cac-flama")     # chama no lead quente
        self.assertContains(r, "no funil ·")    # etapa do funil visível no card

    def test_fila_filtra_por_origem(self):
        services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Lead Site"),
            titulo="s", origem=Oportunidade.Origem.SITE,
        )
        services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Lead Telefone"),
            titulo="t", origem=Oportunidade.Origem.TELEFONE,
        )
        self.client.force_login(self.user)
        r = self.client.get(reverse("comercial:cacador") + "?origem=site")
        self.assertContains(r, "Lead Site")
        self.assertNotContains(r, "Lead Telefone")

    def test_fila_prioriza_a_revisar(self):
        # Quente (score alto) mas já revisado deve ficar ABAIXO de um novo a revisar.
        quente = services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Quente Revisado"),
            titulo="q", valor_estimado=Decimal("3000"), origem=Oportunidade.Origem.INDICACAO,
        )
        an = quente.analise
        an.revisado_em = timezone.now()
        an.save(update_fields=["revisado_em"])
        services.criar_oportunidade(
            usuario=self.user, pessoa=Pessoa.objects.create(nome="Frio Novo"), titulo="f",
        )
        self.client.force_login(self.user)
        body = self.client.get(reverse("comercial:cacador")).content.decode()
        self.assertLess(body.index("Frio Novo"), body.index("Quente Revisado"))


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

    def test_instagram_proposta_ok(self):
        r = self.client.get(reverse("comercial:instagram"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Link na bio")
        self.assertContains(r, "ManyChat")
        self.assertContains(r, "API oficial")

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
        from .models import PaginaCaptacao
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

    def test_lead_incompleto_400(self):
        import json
        r = self.client.post(reverse("lp:fundador_lead"),
                             data=json.dumps({"nome": ""}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

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


class SitePropostaTests(TestCase):
    def test_pedir_proposta_cria_oportunidade(self):
        r = self.client.post(reverse("core:pedir_proposta"), {
            "nome": "Lead Site Form",
            "telefone": "4999887766",
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
        self.assertTrue(self.op.whatsapp_url.startswith("https://wa.me/55"))

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

    def test_painel_e_detalhe_renderizam(self):
        self.client.force_login(self.op)
        self.assertEqual(self.client.get(reverse("comercial:impulsionamento")).status_code, 200)
        r = self.client.get(reverse("comercial:campanha_detalhe", args=[self.camp.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "utm_campaign=fundador-meta")

    def test_lancar_gasto_via_view(self):
        self.client.force_login(self.op)
        self.client.post(reverse("comercial:campanha_gasto", args=[self.camp.pk]),
                         {"data": "2026-09-01", "valor": "250.00"})
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.gasto_total, Decimal("250.00"))


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

    def test_view_sincronizar_redireciona(self):
        self.client.force_login(self.u)
        r = self.client.post(reverse("comercial:campanha_sincronizar", args=[self.camp.pk]))
        self.assertEqual(r.status_code, 302)


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

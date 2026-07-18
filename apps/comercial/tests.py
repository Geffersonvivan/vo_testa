from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, Prospecto, TipoUH

from . import services
from .models import Cotacao, EtapaFunil, MotivoPerda, Oportunidade

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
        from apps.reservas.models import Reserva
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
        self.assertContains(r, "Templates")

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

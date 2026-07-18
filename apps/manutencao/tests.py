from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    ModuloContratado,
    Pessoa,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo
from apps.reservas import services as reservas_services

from . import services
from .models import OrdemServico

Usuario = get_user_model()


class ManutencaoBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(
            username="zelador", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(nome="Padrão", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)


class OrdemServicoTests(ManutencaoBase):
    def test_abrir_bloqueando_tira_da_disponibilidade(self):
        hoje = timezone.localdate()
        self.assertIn(self.uh, reservas_services.uhs_disponiveis(hoje, hoje + timedelta(days=1)))
        os = services.abrir_os(
            self.op, uh=self.uh, titulo="Vazamento", bloquear=True
        )
        self.uh.refresh_from_db()
        self.assertEqual(self.uh.status, UH.Status.BLOQUEADA)
        self.assertTrue(os.bloqueia_uh)
        self.assertNotIn(self.uh, reservas_services.uhs_disponiveis(hoje, hoje + timedelta(days=1)))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="bloqueio_uh").exists())

    def test_nao_bloqueia_quarto_ocupado(self):
        from apps.reservas.models import Reserva

        hospede = Pessoa.objects.create(nome="Fulano")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.op,
        )
        r.fazer_checkin(self.op)  # agora HOSPEDADA
        with self.assertRaises(ValidationError):
            services.abrir_os(self.op, uh=self.uh, titulo="Troca de lâmpada", bloquear=True)

    def test_concluir_libera_quarto(self):
        os = services.abrir_os(self.op, uh=self.uh, titulo="Pintura", bloquear=True)
        services.concluir_os(os, self.op, resolucao="Pintado",
                             custo_maodeobra="150", custo_pecas="80")
        os.refresh_from_db()
        self.uh.refresh_from_db()
        self.assertEqual(os.status, OrdemServico.Status.CONCLUIDA)
        self.assertEqual(os.custo_total, Decimal("230.00"))
        self.assertEqual(self.uh.status, UH.Status.ATIVA)

    def test_concluir_gera_faxina_com_governanca(self):
        os = services.abrir_os(self.op, uh=self.uh, titulo="Elétrica", bloquear=True)
        services.concluir_os(os, self.op)
        from apps.governanca.models import TarefaGovernanca

        self.assertTrue(
            TarefaGovernanca.objects.filter(uh=self.uh, origem="manutencao").exists()
        )

    def test_preventiva_agenda_proxima(self):
        os = services.abrir_os(
            self.op, uh=self.uh, titulo="Revisar ar-condicionado",
            tipo=OrdemServico.Tipo.PREVENTIVA, recorrencia_meses=6,
        )
        proxima = services.concluir_os(os, self.op)
        self.assertIsNotNone(proxima)
        self.assertEqual(proxima.tipo, OrdemServico.Tipo.PREVENTIVA)
        self.assertIsNotNone(proxima.agendada_para)

    def test_prestador_e_dados_fiscais(self):
        from datetime import date
        prestador = Pessoa.objects.create(nome="Refrigeração Serra Ltda")
        os = services.abrir_os(
            self.op, uh=self.uh, titulo="Compressor", prestador=prestador,
            previsto_para=date(2026, 7, 10),
        )
        self.assertEqual(os.prestador, prestador)
        self.assertEqual(os.previsto_para, date(2026, 7, 10))
        services.concluir_os(os, self.op, nota_fiscal="NF 123",
                             garantia_ate=date(2027, 1, 10))
        os.refresh_from_db()
        self.assertEqual(os.nota_fiscal, "NF 123")
        self.assertEqual(os.garantia_ate, date(2027, 1, 10))

    def test_area_comum_nao_exige_quarto(self):
        os = services.abrir_os(self.op, area="Piscina", titulo="Bomba com ruído")
        self.assertEqual(os.alvo, "Piscina")
        self.assertFalse(os.bloqueia_uh)

    def test_alvo_obrigatorio(self):
        with self.assertRaises(ValidationError):
            services.abrir_os(self.op, titulo="Sem alvo")

    def test_cancelar_libera_e_audita(self):
        os = services.abrir_os(self.op, uh=self.uh, titulo="Ralo entupido", bloquear=True)
        services.cancelar_os(os, self.op, "chamado duplicado")
        os.refresh_from_db()
        self.uh.refresh_from_db()
        self.assertEqual(os.status, OrdemServico.Status.CANCELADA)
        self.assertEqual(self.uh.status, UH.Status.ATIVA)
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="cancelamento_os").exists())


class PermissaoTests(ManutencaoBase):
    def test_abrir_pela_view(self):
        self.client.login(username="zelador", password="senha-forte-123")
        r = self.client.post(reverse("manutencao:nova"), {
            "uh": self.uh.pk, "titulo": "Chuveiro frio", "tipo": "corretiva",
            "prioridade": "alta", "bloquear": "1",
        })
        self.assertEqual(r.status_code, 302)
        self.uh.refresh_from_db()
        self.assertEqual(self.uh.status, UH.Status.BLOQUEADA)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.MANUTENCAO).update(ativo=False)
        self.client.login(username="zelador", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("manutencao:painel")).status_code, 404)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="hospede", password="senha-forte-123")
        self.client.login(username="hospede", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("manutencao:painel")).status_code, 403)

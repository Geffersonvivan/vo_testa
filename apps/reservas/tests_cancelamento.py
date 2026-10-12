"""Testes da política de cancelamento (única) + reagendamento (Fase 6)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.nucleo.models import Pessoa, TipoUH, UH
from apps.reservas import cancelamento, services
from apps.reservas.models import Reserva


@override_settings(CANCELAMENTO_ARREPENDIMENTO_DIAS=7, CANCELAMENTO_RETENCAO_PCT="10")
class PoliticaCancelamentoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rec", password="x", email="rec@teste.com")
        self.tipo = TipoUH.objects.create(nome="Cabana C", tarifa_base=Decimal("300.00"))
        self.uh = UH.objects.create(numero="C1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Cliente C")
        self.hoje = timezone.localdate()

    def _reserva(self, status=Reserva.Status.CONFIRMADA, dias=5, offset=10):
        ci = self.hoje + timedelta(days=offset)
        return Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=dias), status=status,
            valor_diaria=Decimal("300.00"), criado_por=self.user)

    def test_dentro_da_janela_devolve_100(self):
        r = self._reserva()
        r.confirmada_em = timezone.now() - timedelta(days=3)  # 3 dias < 7
        pol = cancelamento.politica_cancelamento(r)
        self.assertEqual(pol["cenario"], "nao_iniciada")
        self.assertTrue(pol["dentro_arrependimento"])
        self.assertEqual(pol["retencao_valor"], Decimal("0.00"))
        self.assertEqual(pol["cobranca"], Decimal("0.00"))

    def test_fora_da_janela_retem_10(self):
        r = self._reserva()
        r.confirmada_em = timezone.now() - timedelta(days=10)  # 10 > 7
        pol = cancelamento.politica_cancelamento(r)
        self.assertFalse(pol["dentro_arrependimento"])
        # total = 300×5 = 1500 → 10% = 150 retido.
        self.assertEqual(pol["valor_total"], Decimal("1500.00"))
        self.assertEqual(pol["retencao_valor"], Decimal("150.00"))
        self.assertEqual(pol["cobranca"], Decimal("150.00"))

    def test_exatamente_7_dias_ainda_dentro(self):
        r = self._reserva()
        r.confirmada_em = timezone.now() - timedelta(days=7)
        self.assertTrue(cancelamento.politica_cancelamento(r)["dentro_arrependimento"])

    def test_em_hospedagem_cobra_consumido_mais_10(self):
        # Entrou há 2 dias, estadia de 5 noites.
        ci = self.hoje - timedelta(days=2)
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=5), status=Reserva.Status.HOSPEDADA,
            valor_diaria=Decimal("300.00"), criado_por=self.user)
        pol = cancelamento.politica_cancelamento(r)
        self.assertEqual(pol["cenario"], "em_hospedagem")
        self.assertEqual(pol["dias_consumidos"], 2)
        self.assertEqual(pol["diarias_consumidas"], Decimal("600.00"))
        # total 1500 → 10% = 150; cobrança = 600 + 150 = 750.
        self.assertEqual(pol["retencao_valor"], Decimal("150.00"))
        self.assertEqual(pol["cobranca"], Decimal("750.00"))

    def test_devolucao_desconta_cobranca_do_pago(self):
        r = self._reserva()
        r.confirmada_em = timezone.now() - timedelta(days=10)  # retém 150
        # Pagou 450 (30%) → devolve 450 − 150 = 300.
        self.assertEqual(cancelamento.devolucao(r, Decimal("450.00")), Decimal("300.00"))

    def test_sem_confirmacao_nada_a_reter(self):
        r = self._reserva(status=Reserva.Status.PRE_RESERVA)
        r.confirmada_em = None
        self.assertEqual(cancelamento.politica_cancelamento(r)["cobranca"], Decimal("0.00"))

    def test_sem_confirmacao_fora_da_janela_retem(self):
        # Nunca confirmada: a janela conta da criação; 10 dias depois → retém 10%.
        r = self._reserva(status=Reserva.Status.PRE_RESERVA)
        r.confirmada_em = None
        pol = cancelamento.politica_cancelamento(r, quando=timezone.now() + timedelta(days=10))
        self.assertFalse(pol["dentro_arrependimento"])
        self.assertEqual(pol["retencao_valor"], Decimal("150.00"))

    def test_em_hospedagem_dia_do_checkin_cobra_1_diaria(self):
        ci = self.hoje  # entra hoje
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=5), status=Reserva.Status.HOSPEDADA,
            valor_diaria=Decimal("300.00"), criado_por=self.user)
        pol = cancelamento.politica_cancelamento(r)
        self.assertEqual(pol["dias_consumidos"], 1)              # mínimo 1
        self.assertEqual(pol["diarias_consumidas"], Decimal("300.00"))
        self.assertEqual(pol["cobranca"], Decimal("450.00"))    # 300 + 10%×1500


class TransferirDatasTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rec2", password="x", email="rec2@teste.com")
        self.tipo = TipoUH.objects.create(nome="Cabana T", tarifa_base=Decimal("300.00"))
        self.uh = UH.objects.create(numero="TT1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Cliente T")
        self.hoje = timezone.localdate()

    def test_transfere_e_recalcula(self):
        ci = self.hoje + timedelta(days=10)
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=2), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("300.00"), criado_por=self.user)
        novo_ci = self.hoje + timedelta(days=20)
        services.transferir_datas(r, novo_ci, novo_ci + timedelta(days=3), self.user)
        r.refresh_from_db()
        self.assertEqual(r.checkin, novo_ci)
        self.assertEqual(r.valor_diaria, Decimal("300.00"))  # fora de temporada = base

    def test_nao_transfere_hospedada(self):
        ci = self.hoje - timedelta(days=1)
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=2), status=Reserva.Status.HOSPEDADA,
            valor_diaria=Decimal("300.00"), criado_por=self.user)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            services.transferir_datas(
                r, self.hoje + timedelta(days=30), self.hoje + timedelta(days=32), self.user)


@override_settings(CANCELAMENTO_ARREPENDIMENTO_DIAS=7, CANCELAMENTO_RETENCAO_PCT="10")
class CancelamentoViewTests(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.user = get_user_model().objects.create_superuser(
            username="ger", password="x", email="ger@teste.com")
        self.client.force_login(self.user)
        self.tipo = TipoUH.objects.create(nome="Cabana V", tarifa_base=Decimal("300.00"))
        self.uh = UH.objects.create(numero="V1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Cliente V")
        self.hoje = timezone.localdate()

    def _reserva(self):
        ci = self.hoje + timedelta(days=10)
        return Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=ci,
            checkout=ci + timedelta(days=2), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("300.00"), criado_por=self.user)

    def test_transferir_view_reagenda(self):
        r = self._reserva()
        novo_ci = self.hoje + timedelta(days=25)
        resp = self.client.post(self.reverse("reservas:transferir", args=[r.pk]), {
            "checkin": novo_ci.isoformat(),
            "checkout": (novo_ci + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.checkin, novo_ci)
        self.assertEqual(r.status, Reserva.Status.CONFIRMADA)

    def test_cancelar_view_registra_politica(self):
        r = self._reserva()
        r.confirmada_em = timezone.now() - timedelta(days=10)  # fora do prazo → 10%
        r.save(update_fields=["confirmada_em"])
        self.client.post(self.reverse("reservas:cancelar", args=[r.pk]),
                         {"motivo": "Hóspede desistiu"})
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CANCELADA)
        self.assertIn("reter", r.motivo_cancelamento.lower())

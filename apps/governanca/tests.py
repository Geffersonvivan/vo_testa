from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


class GovernancaBase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(
            username="governanta", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)


class FluxoLimpezaTests(GovernancaBase):
    def test_abrir_faxina_deixa_sujo(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")
        self.assertEqual(tarefa.status, "pendente")

    def test_nao_duplica_faxina_pendente(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        services.abrir_faxina(self.uh, usuario=self.user)
        self.assertEqual(TarefaGovernanca.objects.filter(uh=self.uh).count(), 1)

    def test_iniciar_e_concluir(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(tarefa, self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")
        services.concluir_tarefa(tarefa, self.user)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, "concluida")
        self.assertEqual(services.situacao_uh(self.uh).situacao, "limpa")
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="faxina_concluida").exists()
        )

    def test_inspecionar(self):
        services.inspecionar(self.uh, self.user)
        self.assertTrue(services.situacao_uh(self.uh).pronta)


class SinalCheckoutTests(GovernancaBase):
    def test_checkout_gera_faxina(self):
        from apps.reservas import services as rs
        from apps.reservas.models import Reserva

        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=hospede, checkin=hoje,
            checkout=hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("100"), criado_por=self.user,
        )
        conta = r.fazer_checkin(self.user)
        SessaoCaixa.objects.create(
            operador=self.user, modulo="nucleo", fundo_troco=Decimal("0")
        )
        rs.receber_pagamento(
            conta, self.user, FormaPagamento.objects.get(tipo="dinheiro"),
            conta.saldo(),
        )
        from apps.frigobar.services import registrar_conferencia

        registrar_conferencia(self.user, conta, "checkout", [])
        r.fazer_checkout(self.user)
        self.assertTrue(
            TarefaGovernanca.objects.filter(uh=self.uh, status="pendente").exists()
        )
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")

    def test_uh_pronta_para_checkin(self):
        self.assertTrue(services.uh_pronta_para_checkin(self.uh))
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self.assertFalse(services.uh_pronta_para_checkin(self.uh))
        services.definir_status(self.uh, StatusLimpeza.Situacao.INSPECIONADA, self.user)
        self.assertTrue(services.uh_pronta_para_checkin(self.uh))


class MapaIntegracaoTests(GovernancaBase):
    def test_mapa_reflete_limpeza(self):
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self.client.login(username="governanta", password="senha-forte-123")
        r = self.client.get(reverse("reservas:mapa_quartos"))
        self.assertContains(r, "A limpar")


class PermissaoTests(GovernancaBase):
    def test_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.client.login(username="governanta", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 404)

"""E2E ponta-a-ponta — Auditoria do CRM.

Fluxo-mestre #1: atravessa Reservas + Caixa + Estoque + Loja + Governança usando os
services REAIS (sem mocks), verificando os invariantes que mais doem se quebrarem:
dinheiro (folio ↔ caixa), disponibilidade (antioverbooking) e handoff entre módulos
(consumo da Loja cai no folio; check-out suja o quarto na Governança).

Roda isolado no banco de teste e é repetível — vira ativo permanente da auditoria.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.nucleo.models import (
    UH, CategoriaProduto, FormaPagamento, LocalEstoque, ModuloContratado,
    Pessoa, Produto, SessaoCaixa, TipoUH, registrar_entrada, saldo,
)
from apps.nucleo.modulos import Modulo

Usuario = get_user_model()


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class FluxoMestre1E2ETests(TestCase):
    """Reserva por unidade → check-in → consumo na Loja (folio) → check-out → caixa."""

    def setUp(self):
        for cod in (Modulo.RESERVAS, Modulo.LOJA, Modulo.ESTOQUE, Modulo.GOVERNANCA):
            ModuloContratado.objects.update_or_create(codigo=cod, defaults={"ativo": True})
        self.op = Usuario.objects.create_superuser(username="e2e", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="E2E-1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede E2E")
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.local = LocalEstoque.objects.create(nome="Loja dep", modulo="loja")
        self.produto = Produto.objects.create(
            nome="Refri", categoria=cat, preco_venda=Decimal("7.00"))
        registrar_entrada(self.produto, self.local, 20, Decimal("2.50"), self.op)

    def test_fluxo_mestre(self):
        from apps.loja import services as loja
        from apps.reservas import services as rsv
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        saida = hoje + timedelta(days=2)

        # 1) Pré-reserva por unidade + confirmar
        reserva = rsv.criar_prereserva(
            uh=self.uh, checkin=hoje, checkout=saida, hospede=self.hospede, usuario=self.op)
        self.assertEqual(reserva.status, Reserva.Status.PRE_RESERVA)
        self.assertTrue(rsv.confirmar_reserva(reserva.id, self.op))
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.CONFIRMADA)

        # 2) Antioverbooking: mesma UH no mesmo período é recusada
        with self.assertRaises(ValidationError):
            rsv.criar_prereserva(uh=self.uh, checkin=hoje, checkout=saida,
                                 hospede=self.hospede, usuario=self.op)

        # 3) Caixa da recepção (Reservas) aberto
        SessaoCaixa.objects.create(operador=self.op, modulo="reservas",
                                   fundo_troco=Decimal("0.00"))

        # 4) Check-in → conta aberta, com as diárias já lançadas
        conta = reserva.fazer_checkin(self.op)
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.HOSPEDADA)
        self.assertTrue(conta.aberta)
        diarias = conta.total_lancamentos()
        self.assertGreater(diarias, Decimal("0.00"))   # a hospedagem foi cobrada

        # 5) Consumo na Loja → cai no FOLIO e baixa o estoque (handoff Loja→Reservas)
        loja.finalizar_venda(self.op, self.local,
                             [{"produto_id": self.produto.pk, "quantidade": 2}],
                             "conta", conta_id=conta.id)
        self.assertEqual(saldo(self.produto, self.local), Decimal("18.000"))
        conta.refresh_from_db()
        # total_por_natureza() indexa pela LABEL da NaturezaFiscal ("Consumo"/"Serviço").
        self.assertEqual(conta.total_por_natureza().get("Consumo", Decimal("0")),
                         Decimal("14.00"))
        self.assertEqual(conta.total_lancamentos(), diarias + Decimal("14.00"))

        # 6) Pagar o folio no caixa → saldo zera (o check-out EXIGE a conta quitada:
        #    invariante confirmado — fazer_checkout recusa com saldo em aberto).
        total = conta.total_lancamentos()
        rsv.receber_pagamento(conta, self.op, self.dinheiro, total)
        conta.refresh_from_db()
        self.assertEqual(conta.saldo(), Decimal("0.00"))

        # 7) Check-out → status CHECKOUT, conta fecha + Governança suja o quarto (sinal)
        reserva.fazer_checkout(self.op)
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.CHECKOUT)
        conta.refresh_from_db()
        self.assertFalse(conta.aberta)
        from apps.governanca.models import StatusLimpeza
        st = StatusLimpeza.objects.filter(uh=self.uh).first()
        self.assertIsNotNone(st, "Governança não marcou o quarto no check-out")
        self.assertEqual(st.situacao, StatusLimpeza.Situacao.SUJA)


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class ReceberPagamentoGuardTests(TestCase):
    """Baixa: receber_pagamento aceitava valor acima do saldo (overpayment) e
    travava o check-out."""

    def setUp(self):
        from apps.nucleo.models import ModuloContratado
        ModuloContratado.objects.update_or_create(codigo=Modulo.RESERVAS,
                                                   defaults={"ativo": True})
        self.op = Usuario.objects.create_superuser(username="rp", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="RP-1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede RP")
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def test_pagamento_acima_do_saldo_recusado(self):
        from apps.reservas import services as rsv
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje, checkout=hoje + timedelta(days=1),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op)
        conta = r.fazer_checkin(self.op)
        SessaoCaixa.objects.create(operador=self.op, modulo="reservas",
                                   fundo_troco=Decimal("0.00"))
        saldo = conta.saldo()
        with self.assertRaises(ValidationError):
            rsv.receber_pagamento(conta, self.op, self.dinheiro, saldo + Decimal("50.00"))
        rsv.receber_pagamento(conta, self.op, self.dinheiro, saldo)  # exato = ok
        conta.refresh_from_db()
        self.assertEqual(conta.saldo(), Decimal("0.00"))

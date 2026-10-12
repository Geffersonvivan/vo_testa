"""Comercial escuta Reservas sem inverter dependência."""

from django.dispatch import receiver

from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.pagamentos.signals import pagamento_confirmado
from apps.reservas.signals import quarto_liberado, reserva_encerrada

from . import services


@receiver(reserva_encerrada)
def on_reserva_encerrada(sender, reserva=None, evento="", motivo="", usuario=None, **kwargs):
    if not modulo_ativo(Modulo.COMERCIAL) or reserva is None:
        return
    services.anotar_reserva_encerrada(
        reserva_id=reserva.pk, evento=evento, motivo=motivo or "", usuario=usuario,
    )


@receiver(quarto_liberado)
def on_checkout_comercial(sender, uh=None, reserva=None, usuario=None, origem="", **kwargs):
    """Hand-off NPS / retenção após check-out (origem=checkout)."""
    if origem != "checkout" or reserva is None or not modulo_ativo(Modulo.COMERCIAL):
        return
    services.anotar_reserva_encerrada(
        reserva_id=reserva.pk, evento="checkout", usuario=usuario,
    )


@receiver(pagamento_confirmado)
def on_sinal_pago(sender, cobranca=None, usuario=None, **kwargs):
    """Sinal pago numa oportunidade aberta → ganha + cria a reserva sozinho."""
    if cobranca is None or not modulo_ativo(Modulo.COMERCIAL):
        return
    from apps.pagamentos.models import Cobranca
    # Só o sinal "solto" (gerado sobre o lead, ainda sem reserva/grupo). O fluxo
    # converter_em_reserva já amarra reserva_id e é tratado em confirmar_pagamento.
    if cobranca.finalidade != Cobranca.Finalidade.SINAL:
        return
    if cobranca.reserva_id or cobranca.grupo_id:
        return
    from .models import Oportunidade
    op = Oportunidade.objects.filter(cobranca_sinal_id=cobranca.id).first()
    if op is None or op.reserva_id or op.status != Oportunidade.Status.ABERTA:
        return
    services.ganhar_por_sinal(op, cobranca, usuario)

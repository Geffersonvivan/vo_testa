"""Comercial escuta Reservas sem inverter dependência."""

from django.dispatch import receiver

from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
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

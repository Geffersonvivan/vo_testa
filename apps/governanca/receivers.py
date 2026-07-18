"""Conecta a Governança aos sinais de outros módulos:
- Reservas (check-out/troca → faxina)
- Manutenção (reparo concluído → quarto a limpar antes de reabrir)
"""

from django.dispatch import receiver

from apps.manutencao.signals import reparo_concluido
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.reservas.signals import quarto_liberado

from . import services


@receiver(quarto_liberado)
def on_quarto_liberado(sender, uh, reserva=None, usuario=None, origem="", **kwargs):
    # Só age se a Governança estiver contratada (degradação graciosa).
    if not modulo_ativo(Modulo.GOVERNANCA):
        return
    services.abrir_faxina(uh, usuario=usuario, origem=origem or "checkout")


@receiver(reparo_concluido)
def on_reparo_concluido(sender, uh, ordem=None, usuario=None, **kwargs):
    # Quarto que saiu de manutenção precisa de limpeza antes de voltar a receber.
    if not modulo_ativo(Modulo.GOVERNANCA):
        return
    services.abrir_faxina(uh, usuario=usuario, origem="manutencao")

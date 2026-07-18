"""Conecta a Lavanderia à Governança: faxina concluída → recolhe enxoval sujo."""
from django.dispatch import receiver

from apps.governanca.signals import faxina_concluida
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo

from . import services


@receiver(faxina_concluida)
def on_faxina_concluida(sender, uh, tarefa=None, usuario=None, **kwargs):
    # Só age se a Lavanderia estiver contratada (degradação graciosa).
    if not modulo_ativo(Modulo.LAVANDERIA):
        return
    services.coletar_faxina(uh, usuario)

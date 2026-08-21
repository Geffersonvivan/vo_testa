"""
Reenvia à FNRH Digital as reservas pendentes ou com erro (backstop do envio
best-effort do check-in). Rodar por cron a cada poucos minutos.

Uso: manage.py enviar_fnrh_pendentes
"""
from django.core.management.base import BaseCommand

from apps.reservas.services import enviar_fnrh, fnrh_pendentes_qs


class Command(BaseCommand):
    help = "Empurra à FNRH Digital as reservas pendentes/com erro de sincronização."

    def handle(self, *args, **opts):
        pendentes = list(fnrh_pendentes_qs())
        ok = sum(1 for r in pendentes if enviar_fnrh(r))
        self.stdout.write(self.style.SUCCESS(
            f"{ok}/{len(pendentes)} reserva(s) enviada(s) à FNRH."
        ))

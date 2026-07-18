"""
Expira as pré-reservas de canal cujo prazo de retenção venceu (libera o quarto).
Rodar por cron a cada poucos minutos. A disponibilidade já ignora vencidas em tempo
real; este comando mantém o mapa limpo e serve de backstop.

Uso: manage.py expirar_reservas
"""
from django.core.management.base import BaseCommand

from apps.reservas.services import expirar_vencidas


class Command(BaseCommand):
    help = "Cancela pré-reservas com retenção vencida, liberando os quartos."

    def handle(self, *args, **opts):
        n = expirar_vencidas()
        self.stdout.write(self.style.SUCCESS(f"{n} pré-reserva(s) expirada(s)."))

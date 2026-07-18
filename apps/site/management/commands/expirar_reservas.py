from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.site.models import Reserva


class Command(BaseCommand):
    help = 'Marca como "expirada" as reservas aguardando pagamento cujo prazo já passou.'

    def handle(self, *args, **options):
        agora = timezone.now()
        vencidas = Reserva.objects.filter(
            status='aguardando',
            expira_em__isnull=False,
            expira_em__lt=agora,
        )
        total = vencidas.update(status='expirada')
        self.stdout.write(self.style.SUCCESS(f'{total} reserva(s) expirada(s).'))

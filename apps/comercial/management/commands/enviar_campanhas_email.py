"""Dispara campanhas de e-mail agendadas cujo horário chegou (backstop do agendamento).

Uso: manage.py enviar_campanhas_email            (todas as agendadas vencidas)
     manage.py enviar_campanhas_email --id 3     (uma campanha específica, força)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comercial.models import CampanhaEmail
from apps.comercial.services import enviar_campanha_email


class Command(BaseCommand):
    help = "Envia campanhas de e-mail agendadas (cron) ou uma específica por id."

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, default=None,
                            help="ID de uma campanha para enviar agora.")

    def handle(self, *args, **options):
        if options["id"]:
            qs = CampanhaEmail.objects.filter(pk=options["id"])
        else:
            qs = CampanhaEmail.objects.filter(
                status=CampanhaEmail.Status.AGENDADA,
                agendar_para__lte=timezone.now())
        if not qs.exists():
            self.stdout.write("Nenhuma campanha para enviar.")
            return
        for c in qs:
            camp = enviar_campanha_email(c)
            self.stdout.write(self.style.SUCCESS(
                f"Campanha “{camp.nome}”: {camp.enviados} enviados, "
                f"{camp.erros} erro(s) de {camp.total} alvos."))

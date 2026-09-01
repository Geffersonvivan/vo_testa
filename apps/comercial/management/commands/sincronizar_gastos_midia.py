"""Sincroniza o gasto das campanhas com as plataformas (Fase C) — cron diário.

Uso: manage.py sincronizar_gastos_midia [--dias N]
Com MIDIA_GATEWAY=simulado (padrão) é no-op (modo manual). Com meta/google e as
campanhas com id_externo, busca o gasto dos últimos N dias e grava (origem=sincronizado).
"""
from django.core.management.base import BaseCommand

from apps.comercial import services


class Command(BaseCommand):
    help = "Puxa o gasto de anúncio das plataformas para as campanhas ativas."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=7,
                            help="Janela de dias para sincronizar (padrão 7).")

    def handle(self, *args, **options):
        n = services.sincronizar_gastos(dias=options["dias"])
        self.stdout.write(self.style.SUCCESS(f"Dias-campanha sincronizados: {n}"))

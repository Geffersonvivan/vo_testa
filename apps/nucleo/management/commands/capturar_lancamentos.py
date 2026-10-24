"""
Capturas automáticas da camada Contábil (taxa de cartão, CMV, comissão OTA).

Idempotente. Uso: `manage.py capturar_lancamentos` (mês corrente) ou
`--ano 2026 --mes 9`. Rodar no fechamento do mês (ou via cron).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contabil.capturas import capturar_mes


class Command(BaseCommand):
    help = "Gera os lançamentos automáticos (taxa de cartão, CMV, comissão OTA) do mês."

    def add_arguments(self, parser):
        hoje = timezone.localdate()
        parser.add_argument("--ano", type=int, default=hoje.year)
        parser.add_argument("--mes", type=int, default=hoje.month)

    def handle(self, *args, **opts):
        ano, mes = opts["ano"], opts["mes"]
        r = capturar_mes(ano, mes)
        self.stdout.write(self.style.SUCCESS(
            f"Competência {ano:04d}-{mes:02d}: "
            f"receita {r['receita']} setor(es) · taxa de cartão {r['taxa_cartao']} · "
            f"CMV {r['cmv']} módulo(s) · comissão OTA {r['comissao_ota']}."
        ))

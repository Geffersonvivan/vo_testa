"""
Materializa as contas recorrentes do mês (aluguel, folha, energia, pró-labore...).

Idempotente: rodar duas vezes não duplica (unicidade recorrência×competência).
Uso: `manage.py gerar_recorrentes` (mês corrente) ou `--ano 2026 --mes 11`.
Rodar via cron no início de cada mês (backstop: rodar quando quiser).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.nucleo.models.financeiro import ContaRecorrente


class Command(BaseCommand):
    help = "Gera os títulos a pagar/receber das contas recorrentes na competência."

    def add_arguments(self, parser):
        hoje = timezone.localdate()
        parser.add_argument("--ano", type=int, default=hoje.year)
        parser.add_argument("--mes", type=int, default=hoje.month)

    def handle(self, *args, **opts):
        ano, mes = opts["ano"], opts["mes"]
        criados = reaproveitados = 0
        for rec in ContaRecorrente.objects.filter(ativo=True):
            antes = rec.titulos.filter(competencia=f"{ano:04d}-{mes:02d}").exists()
            rec.gerar(ano, mes)
            if antes:
                reaproveitados += 1
            else:
                criados += 1
        self.stdout.write(self.style.SUCCESS(
            f"Competência {ano:04d}-{mes:02d}: {criados} título(s) criado(s), "
            f"{reaproveitados} já existia(m)."
        ))

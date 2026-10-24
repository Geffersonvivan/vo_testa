"""
Aplica o fechamento mensal guiado (folha, encargos, pró-labore, DAS) à DRE,
gerando/atualizando os lançamentos de competência.

O FechamentoMensal é preenchido na tela/admin; este comando (re)aplica.
Uso: `manage.py aplicar_fechamento --ano 2026 --mes 9`.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.contabil.models import FechamentoMensal


class Command(BaseCommand):
    help = "Aplica o fechamento mensal (gera os lançamentos de folha/encargos/pró-labore/DAS)."

    def add_arguments(self, parser):
        hoje = timezone.localdate()
        parser.add_argument("--ano", type=int, default=hoje.year)
        parser.add_argument("--mes", type=int, default=hoje.month)

    def handle(self, *args, **opts):
        ano, mes = opts["ano"], opts["mes"]
        fm = FechamentoMensal.objects.filter(ano=ano, mes=mes).first()
        if not fm:
            raise CommandError(
                f"Nenhum fechamento cadastrado para {ano:04d}-{mes:02d}. "
                "Preencha os valores (admin/tela) antes de aplicar."
            )
        fm.aplicar()
        self.stdout.write(self.style.SUCCESS(
            f"Fechamento {ano:04d}-{mes:02d} aplicado: folha R$ {fm.folha}, "
            f"encargos R$ {fm.encargos}, pró-labore R$ {fm.pro_labore}, DAS R$ {fm.das}."
        ))

"""Lista os leads (oportunidades) com telefone incompleto/inválido — passivo de antes
da validação. Não altera nada; só reporta pra correção manual.

Uso: manage.py relatorio_telefones_incompletos [--todos]
  (sem --todos: só oportunidades abertas; com --todos: todas)
"""
from django.core.management.base import BaseCommand

from apps.comercial.models import Oportunidade
from apps.comercial.services import _telefone_ok


class Command(BaseCommand):
    help = "Lista leads com telefone incompleto/inválido (para correção manual)."

    def add_arguments(self, parser):
        parser.add_argument("--todos", action="store_true",
                            help="Inclui oportunidades fechadas (ganhas/perdidas).")

    def handle(self, *args, **opts):
        qs = Oportunidade.objects.select_related("pessoa").order_by("-criado_em")
        if not opts["todos"]:
            qs = qs.filter(status=Oportunidade.Status.ABERTA)

        com_tel = total = 0
        linhas = []
        for op in qs:
            tel = (op.pessoa.telefone or "").strip()
            if not tel:
                continue
            com_tel += 1
            if not _telefone_ok(tel):
                total += 1
                linhas.append(f"  #{op.pk}  {op.pessoa.nome[:28]:<28}  {tel:<20}  "
                              f"[{op.get_status_display()}]")

        escopo = "todas" if opts["todos"] else "abertas"
        self.stdout.write(f"Oportunidades ({escopo}) com telefone preenchido: {com_tel}")
        self.stdout.write(self.style.WARNING(
            f"Com telefone INCOMPLETO/INVÁLIDO: {total}"))
        for ln in linhas:
            self.stdout.write(ln)
        if not total:
            self.stdout.write(self.style.SUCCESS("Nenhum telefone incompleto. 🎉"))

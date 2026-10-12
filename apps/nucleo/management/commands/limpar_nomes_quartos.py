"""Remove os nomes temáticos dos quartos — a pousada usa só o número ("Quarto N").

Zera `UH.nome_tematico` (hospedagem) e a `VitrineQuarto.descricao_curta` que apenas
espelhava o nome (para o site não vazar o tema como subtítulo). Idempotente — rodar no
deploy. Day use não é tocado. A recepção pode voltar a nomear na tela, se um dia quiser.

Uso:  manage.py limpar_nomes_quartos
"""
from django.core.management.base import BaseCommand

from apps.nucleo.models import UH, TipoUH


class Command(BaseCommand):
    help = "Zera os nomes temáticos dos quartos (exibe só 'Quarto N')."

    def handle(self, *args, **opts):
        qs = UH.objects.exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
        nomes = qs.exclude(nome_tematico="").update(nome_tematico="")

        # Subtítulo da vitrine (site) que só repetia o nome/tema → limpa p/ não vazar.
        descr = 0
        try:
            from apps.site.models import VitrineQuarto
        except Exception:  # noqa: BLE001 — módulo site pode não estar disponível
            VitrineQuarto = None
        if VitrineQuarto is not None:
            for v in VitrineQuarto.objects.select_related("uh").exclude(descricao_curta=""):
                if v.uh.tipo.modalidade == TipoUH.Modalidade.DAY_USE:
                    continue
                v.descricao_curta = ""
                v.save(update_fields=["descricao_curta"])
                descr += 1

        self.stdout.write(self.style.SUCCESS(
            f"{nomes} nome(s) temático(s) e {descr} subtítulo(s) de vitrine zerados."))

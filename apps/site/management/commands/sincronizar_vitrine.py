"""
Sincroniza a vitrine POR UNIDADE: garante uma VitrineQuarto para cada quarto físico
(UH) de hospedagem do CRM. O nome temático, as qualidades e o preço vêm do CRM; a
mídia editorial (foto, tour 360°) e o destaque ficam na VitrineQuarto.

Não mexe nas fotos/textos já preenchidos: só cria o que falta. Por padrão marca os
9 primeiros quartos (por número) como destaque, formando o grid 3×3 da home.

Uso: manage.py sincronizar_vitrine
"""
from django.core.management.base import BaseCommand

from apps.nucleo.models import UH, TipoUH
from apps.site.models import VitrineQuarto

DESTAQUES_HOME = 9  # grid 3×3 na página inicial


class Command(BaseCommand):
    help = "Cria/garante a vitrine (1 card) de cada quarto físico de hospedagem."

    def handle(self, *args, **opts):
        uhs = list(
            UH.objects.filter(
                status=UH.Status.ATIVA, tipo__modalidade=TipoUH.Modalidade.HOSPEDAGEM,
            ).select_related("tipo").order_by("numero")
        )
        criados = 0
        for i, uh in enumerate(uhs):
            _, novo = VitrineQuarto.objects.get_or_create(
                uh=uh,
                defaults={
                    "descricao_curta": uh.nome_tematico or f"Quarto {uh.numero}",
                    "descricao": uh.diferenciais or "",
                    "metragem": 25,
                    "destaque": i < DESTAQUES_HOME,
                    "publicar": True,
                    "ordem": i,
                },
            )
            criados += 1 if novo else 0

        total = VitrineQuarto.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Vitrine por unidade: {criados} criada(s); {total} quarto(s) na vitrine."
        ))

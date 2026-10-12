"""Seed idempotente da configuração de camas/colchões dos 24 quartos + estoque global
de colchões extra. Fonte: docs/Reservas/CONFIGURACAO_QUARTOS.md (+ PLANO_ESTOQUE_COLCHOES.md).

Reconcilia o modelo existente (não duplica):
- casais_max  -> nº de PosicaoCama (cada posição = 1 casal = 2 colchões, base garantida).
- camas_solteiro -> max_colchoes_extras = camas_solteiro - 2*casais_max (o pool de extras).
- sofa_cama   -> ConfiguracaoUH.tem_sofa_cama (1 adulto ou 2 crianças ≤15).
- layout      -> UH.layout.
E cria/atualiza o singleton ColchoesExtra (default 10).

Uso:  manage.py configurar_camas [--estoque 10]
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.nucleo.models import UH
from apps.nucleo.models.cadastros import ConfiguracaoUH, PosicaoCama
from apps.reservas.models import ColchoesExtra

# numero -> (layout, camas_solteiro, casais_max, sofa_cama)
CONFIG = {
    "01": ("separado", 6, 2, True),  "02": ("separado", 6, 2, True),
    "03": ("meia_divisao", 3, 1, False), "04": ("conjugado", 3, 1, False),
    "05": ("conjugado", 3, 1, False), "06": ("conjugado", 3, 1, False),
    "07": ("conjugado", 3, 1, False), "08": ("conjugado", 3, 1, False),
    "09": ("separado", 4, 1, True),  "10": ("separado", 4, 1, False),
    "11": ("conjugado", 2, 1, False), "12": ("conjugado", 2, 1, False),
    "13": ("conjugado", 3, 1, False), "14": ("conjugado", 3, 1, False),
    "15": ("separado", 4, 1, True),
    "16": ("separado", 7, 2, True),  "17": ("separado", 7, 2, True),
    "18": ("separado", 7, 2, True),  "19": ("separado", 6, 2, True),
    "20": ("separado", 6, 2, True),  "21": ("separado", 6, 2, True),
    "22": ("separado", 7, 2, True),  "23": ("separado", 7, 2, True),
    "24": ("separado", 7, 2, True),
}


class Command(BaseCommand):
    help = "Configura camas/colchões dos 24 quartos + estoque de colchões extra (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--estoque", type=int, default=10,
                            help="Colchões extra em estoque (default 10).")

    @transaction.atomic
    def handle(self, *args, **opts):
        total_base = total_extras = 0
        for num, (layout, camas_s, casais_m, sofa) in CONFIG.items():
            uh = UH.objects.filter(numero=f"Quarto {num}").first()
            if not uh:
                self.stdout.write(self.style.WARNING(f"Quarto {num} não encontrado — pulado"))
                continue

            uh.layout = layout
            uh.save(update_fields=["layout"])

            # posições = casais_max (cria/ajusta; cada posição começa como casal)
            posicoes = list(uh.posicoes_cama.order_by("ordem", "id"))
            while len(posicoes) < casais_m:
                i = len(posicoes) + 1
                posicoes.append(PosicaoCama.objects.create(
                    uh=uh, nome=f"Quarto {i}", ordem=i,
                    montagem_padrao=PosicaoCama.Montagem.CASAL,
                ))
            for sobra in posicoes[casais_m:]:
                sobra.delete()

            extras = camas_s - 2 * casais_m
            cfg, _ = ConfiguracaoUH.objects.get_or_create(uh=uh)
            cfg.tem_sofa_cama = sofa
            if sofa:
                cfg.sofa_adultos, cfg.sofa_criancas, cfg.sofa_idade_maxima = 1, 2, 15
            cfg.max_colchoes_extras = extras
            cfg.save()

            total_base += 2 * casais_m
            total_extras += extras
            self.stdout.write(
                f"Quarto {num}: casais_max={casais_m} · camas_solteiro={camas_s} "
                f"· extras={extras} · sofá={'sim' if sofa else 'não'} · {layout}"
            )

        est = ColchoesExtra.atual()
        est.quantidade = opts["estoque"]
        est.save(update_fields=["quantidade"])

        self.stdout.write(self.style.SUCCESS(
            f"\nBase garantida (casais×2): {total_base} colchões · "
            f"vagas extras demandadas: {total_extras} · "
            f"estoque de colchões extra: {est.quantidade}"
        ))

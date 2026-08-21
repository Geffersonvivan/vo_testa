"""Semeia a composição de camas dos 24 quartos (capacidade por unidade).

Idempotente. Rode depois de criar/atualizar os quartos (ex.: após o seed de
estrutura) num ambiente novo. Em bases existentes a migração
`nucleo/0017_seed_camas_config` já fez isso.

    python manage.py popular_camas

Configuração real: dois cômodos = 01,02,16..24 (11); sofá = 01,02,09,15,16..24
(13); colchões = 2 nos de dois cômodos, 1 nos de um; PCD = 04 e 14. Total: 70
vagas fixas + 13 sofá + 35 colchão → lotação máxima 118 (131 com crianças).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.nucleo.models import UH, ConfiguracaoUH, PosicaoCama

DOIS_COMODOS = {1, 2, 16, 17, 18, 19, 20, 21, 22, 23, 24}
COM_SOFA = {1, 2, 9, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24}
PCD = {4, 14}


def _num(numero: str) -> int:
    return int("".join(c for c in numero if c.isdigit()) or 0)


@transaction.atomic
def semear_camas() -> int:
    """(Re)cria posições de cama e configuração dos quartos de pernoite.
    Retorna quantos quartos foram configurados."""
    total = 0
    for uh in UH.objects.filter(tipo__modalidade="hospedagem"):
        n = _num(uh.numero)
        if not n:
            continue
        duplo = n in DOIS_COMODOS

        PosicaoCama.objects.filter(uh=uh).delete()
        nomes = ["Quarto 1", "Quarto 2"] if duplo else ["Quarto"]
        for ordem, nome in enumerate(nomes):
            PosicaoCama.objects.create(
                uh=uh, nome=nome, montagem_padrao="casal", ordem=ordem,
            )

        ConfiguracaoUH.objects.update_or_create(
            uh=uh,
            defaults={
                "tem_sofa_cama": n in COM_SOFA,
                "sofa_adultos": 1,
                "sofa_criancas": 2,
                "sofa_idade_maxima": 15,
                "max_colchoes_extras": 2 if duplo else 1,
                "tarifa_colchao_extra": Decimal("80.00"),
            },
        )
        if n in PCD and not uh.pcd:
            uh.pcd = True
            uh.save(update_fields=["pcd"])
        total += 1
    return total


class Command(BaseCommand):
    help = "Semeia a composição de camas dos 24 quartos (idempotente)."

    def handle(self, *args, **options):
        total = semear_camas()
        self.stdout.write(self.style.SUCCESS(f"Camas configuradas em {total} quartos."))

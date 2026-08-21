"""Semeia a composição de camas dos 24 quartos (capacidade derivada da unidade).

Configuração real da pousada:
- Dois cômodos (2 posições): 01, 02, 16, 17, 18, 19, 20, 21, 22, 23, 24 (11 quartos)
- Sofá-cama: 01, 02, 09, 15, 16..24 (13 quartos)
- Colchões extras: 2 nos de dois cômodos, 1 nos de um cômodo
- PCD: 04 e 14
- Day use (DAY-01..08): sem cama — fora deste seed

Confere no fim: 70 vagas fixas + 13 sofá + 35 colchão = lotação máx. 118 (131 com
crianças no sofá). Se der diferente, o seed está errado.
"""
from decimal import Decimal

from django.db import migrations

DOIS_COMODOS = {1, 2, 16, 17, 18, 19, 20, 21, 22, 23, 24}
COM_SOFA = {1, 2, 9, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24}
PCD = {4, 14}


def _num(numero: str) -> int:
    return int("".join(c for c in numero if c.isdigit()) or 0)


def semear(apps, schema_editor):
    UH = apps.get_model("nucleo", "UH")
    PosicaoCama = apps.get_model("nucleo", "PosicaoCama")
    ConfiguracaoUH = apps.get_model("nucleo", "ConfiguracaoUH")

    for uh in UH.objects.filter(tipo__modalidade="hospedagem"):
        n = _num(uh.numero)
        if not n:
            continue
        duplo = n in DOIS_COMODOS

        # Posições de cama (idempotente): recria a composição base.
        PosicaoCama.objects.filter(uh=uh).delete()
        if duplo:
            nomes = ["Quarto 1", "Quarto 2"]
        else:
            nomes = ["Quarto"]
        for ordem, nome in enumerate(nomes):
            PosicaoCama.objects.create(
                uh=uh, nome=nome, montagem_padrao="casal", ordem=ordem,
            )

        # Configuração (sofá + colchões extras).
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


def desfazer(apps, schema_editor):
    PosicaoCama = apps.get_model("nucleo", "PosicaoCama")
    ConfiguracaoUH = apps.get_model("nucleo", "ConfiguracaoUH")
    PosicaoCama.objects.all().delete()
    ConfiguracaoUH.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0016_configuracaouh_posicaocama"),
    ]

    operations = [
        migrations.RunPython(semear, desfazer),
    ]

"""Só 4 vagas de "Dia na Pousada": DAY-05..08 saem de operação.

Desativa (INATIVA) em vez de apagar — some do mapa e fica não-reservável, mas
preserva qualquer reserva histórica (seguro em produção). Reversível.
"""

from django.db import migrations

EXTRAS = ["DAY-05", "DAY-06", "DAY-07", "DAY-08"]


def desativar_extras(apps, schema_editor):
    UH = apps.get_model("nucleo", "UH")
    UH.objects.filter(numero__in=EXTRAS).update(status="inativa")


def reativar_extras(apps, schema_editor):
    UH = apps.get_model("nucleo", "UH")
    UH.objects.filter(numero__in=EXTRAS).update(status="ativa")


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0027_migrar_recados_antigos_resolvidos"),
    ]

    operations = [
        migrations.RunPython(desativar_extras, reativar_extras),
    ]

"""Semeia o campo `bloco` (bloco/área) dos 24 quartos com a ala oficial, para que
tudo que já mostra `bloco` (lista de estrutura, admin, form de quarto) reflita a
localização oficial. Day use (DAY-0N) é ignorado. Idempotente e defensivo: só ajusta
quando o valor difere; não toca em reservas/leads.
"""
from django.db import migrations


def semear_alas(apps, schema_editor):
    from apps.nucleo.alas import ala_do_quarto
    UH = apps.get_model("nucleo", "UH")
    for uh in UH.objects.select_related("tipo"):
        if uh.tipo and uh.tipo.modalidade == "day_use":
            continue
        ala = ala_do_quarto(uh.numero)
        if ala and uh.bloco != ala:
            uh.bloco = ala
            uh.save(update_fields=["bloco"])


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0041_seed_pessoa_adicional_day_use"),
    ]

    operations = [
        migrations.RunPython(semear_alas, migrations.RunPython.noop),
    ]

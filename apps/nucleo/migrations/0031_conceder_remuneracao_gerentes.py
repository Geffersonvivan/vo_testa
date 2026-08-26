"""Salário passou a exigir a flag de área 'remuneracao'. Para não tirar acesso
de quem já via (gerentes/staff), concede a flag a eles. Superusuário faz bypass.
Reversível: remove a flag."""

from django.db import migrations


def conceder(apps, schema_editor):
    Usuario = apps.get_model("nucleo", "Usuario")
    for u in Usuario.objects.filter(is_staff=True, is_superuser=False):
        areas = list(u.areas or [])
        if "remuneracao" not in areas:
            areas.append("remuneracao")
            u.areas = areas
            u.save(update_fields=["areas"])


def remover(apps, schema_editor):
    Usuario = apps.get_model("nucleo", "Usuario")
    for u in Usuario.objects.all():
        if u.areas and "remuneracao" in u.areas:
            u.areas = [a for a in u.areas if a != "remuneracao"]
            u.save(update_fields=["areas"])


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0030_funcionario_compensacao_feriado_and_more"),
    ]

    operations = [
        migrations.RunPython(conceder, remover),
    ]

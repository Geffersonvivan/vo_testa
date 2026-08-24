"""Recados já existentes viram 'resolvida' (histórico preservado, saem das
pendências). Sem autor de fechamento (migração de sistema); resolvida_em =
data de criação."""

from django.db import migrations
from django.db.models import F


def marcar_resolvidos(apps, schema_editor):
    EntradaLogbook = apps.get_model("nucleo", "EntradaLogbook")
    EntradaLogbook.objects.all().update(
        status="resolvida",
        resolvida_em=F("criado_em"),
        resolucao_nota="Migrado do formato antigo de recados.",
    )


def reverter(apps, schema_editor):
    EntradaLogbook = apps.get_model("nucleo", "EntradaLogbook")
    EntradaLogbook.objects.filter(
        resolucao_nota="Migrado do formato antigo de recados."
    ).update(status="aberta", resolvida_em=None, resolucao_nota="")


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0026_entradalogbook_resolucao_nota_and_more"),
    ]

    operations = [
        migrations.RunPython(marcar_resolvidos, reverter),
    ]

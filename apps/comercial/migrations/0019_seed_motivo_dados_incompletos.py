from django.db import migrations


def semear(apps, schema_editor):
    """Adiciona o motivo de perda 'Dados incompletos' (ativo). Idempotente — só cria
    um registro de catálogo, não toca em oportunidades/leads."""
    MotivoPerda = apps.get_model("comercial", "MotivoPerda")
    MotivoPerda.objects.get_or_create(
        nome="Dados incompletos", defaults={"ativo": True})


def remover(apps, schema_editor):
    MotivoPerda = apps.get_model("comercial", "MotivoPerda")
    MotivoPerda.objects.filter(
        nome="Dados incompletos", oportunidades__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0018_oportunidade_motivo_perda_detalhe"),
    ]

    operations = [
        migrations.RunPython(semear, remover),
    ]

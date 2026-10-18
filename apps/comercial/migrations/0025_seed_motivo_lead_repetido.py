from django.db import migrations


def semear(apps, schema_editor):
    """Adiciona o motivo de perda 'Lead repetido (mesma campanha)' (ativo). Idempotente —
    só cria um registro de catálogo, não toca em oportunidades/leads."""
    MotivoPerda = apps.get_model("comercial", "MotivoPerda")
    MotivoPerda.objects.get_or_create(
        nome="Lead repetido (mesma campanha)", defaults={"ativo": True})


def remover(apps, schema_editor):
    MotivoPerda = apps.get_model("comercial", "MotivoPerda")
    MotivoPerda.objects.filter(
        nome="Lead repetido (mesma campanha)", oportunidades__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0024_seed_blueprint_lp"),
    ]

    operations = [
        migrations.RunPython(semear, remover),
    ]

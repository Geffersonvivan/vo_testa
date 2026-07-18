from django.db import migrations


def ativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.get_or_create(codigo="auditoria", defaults={"ativo": True})


def desativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="auditoria").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nucleo", "0010_seed_almoxarifado"),
    ]
    operations = [
        migrations.RunPython(ativar, desativar),
    ]

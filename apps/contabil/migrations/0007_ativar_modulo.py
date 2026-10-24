from django.db import migrations


def ativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.get_or_create(codigo="contabil", defaults={"ativo": True})


def desativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="contabil").delete()


class Migration(migrations.Migration):
    dependencies = [("contabil", "0006_fechamentomensal")]
    operations = [migrations.RunPython(ativar, desativar)]

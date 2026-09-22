"""Ativa o módulo Marketing e cria a verba padrão (singleton)."""
from django.db import migrations


def semear(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    VerbaMarketing = apps.get_model("marketing", "VerbaMarketing")
    ModuloContratado.objects.get_or_create(codigo="marketing", defaults={"ativo": True})
    if not VerbaMarketing.objects.exists():
        VerbaMarketing.objects.create(tetos={}, alerta_pct=80)


def reverter(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="marketing").delete()
    # A verba não é apagada (pode já ter tetos configurados).


class Migration(migrations.Migration):
    dependencies = [
        ("marketing", "0001_initial"),
        ("nucleo", "0034_pessoa_aceita_whatsapp_pessoa_whatsapp_optin_em"),
    ]
    operations = [
        migrations.RunPython(semear, reverter),
    ]

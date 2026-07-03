# Ativa os 11 módulos da fase 1 para a Pousada Vô Testa (cliente nº 1).

from django.db import migrations

MODULOS_FASE_1 = [
    "reservas",
    "governanca",
    "manutencao",
    "escala",
    "estoque",
    "loja",
    "restaurante",
    "lavanderia",
    "frigobar",
    "pagamentos",
    "appsite",
]


def ativar_modulos(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    for codigo in MODULOS_FASE_1:
        ModuloContratado.objects.get_or_create(codigo=codigo, defaults={"ativo": True})


def desativar_modulos(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo__in=MODULOS_FASE_1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(ativar_modulos, desativar_modulos),
    ]

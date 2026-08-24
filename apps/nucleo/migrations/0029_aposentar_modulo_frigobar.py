"""Aposenta o módulo Frigobar: desativa o ModuloContratado (fica fora do menu,
do uso e — junto com a remoção do catálogo/rotas — some da Central de Módulos).
Não apaga o registro nem as tabelas do app (opção 2: dormente, reversível)."""

from django.db import migrations


def desativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="frigobar").update(ativo=False)


def reativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.filter(codigo="frigobar").update(ativo=True)


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0028_reduzir_day_use_para_4"),
    ]

    operations = [
        migrations.RunPython(desativar, reativar),
    ]

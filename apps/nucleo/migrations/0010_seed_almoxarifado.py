"""Cria o depósito padrão: Almoxarifado central (vinculado ao núcleo)."""

from django.db import migrations


def criar_almoxarifado(apps, schema_editor):
    LocalEstoque = apps.get_model("nucleo", "LocalEstoque")
    LocalEstoque.objects.get_or_create(
        nome="Almoxarifado central", defaults={"modulo": "nucleo"}
    )


def remover(apps, schema_editor):
    LocalEstoque = apps.get_model("nucleo", "LocalEstoque")
    LocalEstoque.objects.filter(nome="Almoxarifado central").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nucleo", "0009_categoriaproduto_localestoque_inventario_produto_and_more"),
    ]

    operations = [
        migrations.RunPython(criar_almoxarifado, remover),
    ]

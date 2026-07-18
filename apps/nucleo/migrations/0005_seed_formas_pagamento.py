"""Seed das formas de pagamento padrão (ESPECIFICACAO §4.3)."""

from django.db import migrations

FORMAS = [
    ("Dinheiro", "dinheiro", False),
    ("Pix", "pix", False),
    ("Cartão de débito", "cartao_debito", False),
    ("Cartão de crédito", "cartao_credito", True),
    ("Transferência", "transferencia", False),
    ("Cortesia", "cortesia", False),
]


def criar_formas(apps, schema_editor):
    FormaPagamento = apps.get_model("nucleo", "FormaPagamento")
    for nome, tipo, parcela in FORMAS:
        FormaPagamento.objects.get_or_create(
            nome=nome, defaults={"tipo": tipo, "permite_parcelamento": parcela}
        )


def remover_formas(apps, schema_editor):
    FormaPagamento = apps.get_model("nucleo", "FormaPagamento")
    FormaPagamento.objects.filter(nome__in=[f[0] for f in FORMAS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nucleo", "0004_formapagamento_pessoa_temporada_tipouh_and_more"),
    ]

    operations = [
        migrations.RunPython(criar_formas, remover_formas),
    ]

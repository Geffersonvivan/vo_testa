"""
Sinaliza as CategoriaFinanceira que o sistema alimenta automaticamente
(captura de receita/custo + fechamento) como `automatica=True` — para sumirem
do lançamento manual e não haver dupla contagem. Defensivo: só liga a flag.
"""

from django.db import migrations

RECEITA = ["Hospedagem", "Loja", "Restaurante", "Lavanderia"]
DESPESA = [
    "Taxa de cartão (adquirente)",
    "Custo das mercadorias vendidas (CMV)",
    "Comissão de canal (OTA)",
    "Folha de pagamento",
    "Encargos sociais (FGTS/INSS)",
    "Pró-labore",
    "Simples Nacional (DAS)",
]


def ligar(apps, schema_editor):
    Categoria = apps.get_model("nucleo", "CategoriaFinanceira")
    Categoria.objects.filter(nome__in=RECEITA, tipo="receita").update(automatica=True)
    Categoria.objects.filter(nome__in=DESPESA, tipo="despesa").update(automatica=True)


def desligar(apps, schema_editor):
    Categoria = apps.get_model("nucleo", "CategoriaFinanceira")
    Categoria.objects.filter(nome__in=RECEITA, tipo="receita").update(automatica=False)
    Categoria.objects.filter(nome__in=DESPESA, tipo="despesa").update(automatica=False)


class Migration(migrations.Migration):
    dependencies = [
        ("contabil", "0007_ativar_modulo"),
        ("nucleo", "0048_categoriafinanceira_automatica_and_more"),
    ]
    operations = [migrations.RunPython(ligar, desligar)]

"""
Rótulo neutro da conta de dedução 3.1.02.01: o regime (Simples × Lucro Presumido)
ainda não está confirmado (Cartão CNPJ mostra Porte ME, mas não o regime; a prova é
a Consulta Optantes do Simples). Enquanto isso, a conta deixa de dizer "Simples
Nacional" e passa a "Impostos sobre a receita" — serve para DAS (Simples) OU
PIS/COFINS/ISS (Presumido). Só renomeia; não mexe em lançamento.
"""

from django.db import migrations

NOVO = "(-) Impostos sobre a receita"
ANTIGO = "(-) Simples Nacional"


def renomear(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    ContaContabil.objects.filter(classificacao="3.1.02.01").update(nome=NOVO)


def reverter(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    ContaContabil.objects.filter(classificacao="3.1.02.01").update(nome=ANTIGO)


class Migration(migrations.Migration):
    dependencies = [("contabil", "0008_flag_categorias_automaticas")]
    operations = [migrations.RunPython(renomear, reverter)]

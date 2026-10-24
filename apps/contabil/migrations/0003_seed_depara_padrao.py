"""Seed do de-para padrão: regras automáticas + fallbacks por tipo."""

from django.db import migrations

# (campo_origem, valor, conta_classificacao, prioridade)
#   campo_origem ∈ {natureza_folio, origem_sistema}
REGRAS = [
    ("natureza_folio", "servico", "3.1.01.03", 5),
    ("natureza_folio", "consumo", "3.1.01.01", 5),
    ("origem_sistema", "cmv", "4.5.01.01", 8),
    ("origem_sistema", "pagamento_taxa", "5.1.03.02", 8),
    ("origem_sistema", "comissao_ota", "5.1.01.02", 8),
    ("origem_sistema", "simples", "3.1.02.01", 8),
    # Fallbacks por tipo (nunca fica órfão): prioridade 0, fora da disputa normal.
    ("origem_sistema", "fallback_receita", "3.1.01.03", 0),
    ("origem_sistema", "fallback_despesa", "5.1.02.02", 0),
]


def seed(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")
    for campo, valor, classif, prioridade in REGRAS:
        conta = ContaContabil.objects.filter(classificacao=classif).first()
        if not conta:
            continue
        filtro = {campo: valor}
        MapeamentoContabil.objects.get_or_create(
            defaults=dict(conta=conta, prioridade=prioridade),
            **filtro,
        )


def unseed(apps, schema_editor):
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")
    for campo, valor, *_ in REGRAS:
        MapeamentoContabil.objects.filter(**{campo: valor}).delete()


class Migration(migrations.Migration):
    dependencies = [("contabil", "0002_seed_plano_contas")]
    operations = [migrations.RunPython(seed, unseed)]

"""
Backfill: carimba `conta_contabil` nos lançamentos e contas que já existiam.

Defensivo (memória do projeto): só preenche quando está EM BRANCO; nunca
sobrescreve, nunca apaga. Resolve pela categoria (de-para) e, no vazio, pelo
fallback do tipo.
"""

from django.db import migrations

FALLBACK = {"receita": "fallback_receita", "despesa": "fallback_despesa"}


def _conta_por_categoria(MapeamentoContabil, categoria_id):
    m = (
        MapeamentoContabil.objects.filter(categoria_id=categoria_id)
        .select_related("conta").order_by("-prioridade").first()
    )
    return m.conta if m else None


def _conta_fallback(MapeamentoContabil, tipo):
    chave = FALLBACK.get(tipo)
    if not chave:
        return None
    m = MapeamentoContabil.objects.filter(origem_sistema=chave).select_related("conta").first()
    return m.conta if m else None


def backfill(apps, schema_editor):
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")
    Lancamento = apps.get_model("nucleo", "LancamentoFinanceiro")
    ContaPR = apps.get_model("nucleo", "ContaPagarReceber")

    for lanc in Lancamento.objects.filter(conta_contabil="").select_related("categoria"):
        conta = _conta_por_categoria(MapeamentoContabil, lanc.categoria_id) \
            or _conta_fallback(MapeamentoContabil, lanc.tipo)
        if conta:
            Lancamento.objects.filter(pk=lanc.pk).update(conta_contabil=conta.classificacao)

    for c in ContaPR.objects.filter(conta_contabil="").select_related("categoria"):
        tipo = c.categoria.tipo if c.categoria_id else None
        conta = _conta_por_categoria(MapeamentoContabil, c.categoria_id) \
            or _conta_fallback(MapeamentoContabil, tipo)
        if conta:
            ContaPR.objects.filter(pk=c.pk).update(conta_contabil=conta.classificacao)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("contabil", "0004_depara_categorias_existentes"),
        ("nucleo", "0046_contapagarreceber_competencia_and_more"),
    ]
    operations = [migrations.RunPython(backfill, noop)]

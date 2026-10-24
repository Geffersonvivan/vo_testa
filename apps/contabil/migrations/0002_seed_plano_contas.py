"""Seed do plano de contas enxuto de pousada (ver mockup §2)."""

from django.db import migrations

# (classificacao, nome, grupo, natureza, tipo, codigo_contador, ordem)
CONTAS = [
    ("3", "RECEITAS", "receita", "credora", "sintetica", None, 300),
    ("3.1.01", "RECEITA BRUTA", "receita", "credora", "sintetica", None, 310),
    ("3.1.01.01", "Revenda de Mercadorias", "receita", "credora", "analitica", 1502, 311),
    ("3.1.01.03", "Prestação de Serviços", "receita", "credora", "analitica", 1561, 313),
    ("3.1.02", "DEDUÇÕES DA RECEITA", "receita", "devedora", "sintetica", None, 320),
    ("3.1.02.01", "(-) Simples Nacional", "receita", "devedora", "analitica", 3056, 321),
    ("3.1.02.02", "(-) Devoluções e Abatimentos", "receita", "devedora", "analitica", 4984, 322),
    ("4", "CUSTOS DOS SERVIÇOS E MERCADORIAS", "custo", "devedora", "sintetica", None, 400),
    ("4.2.01", "CUSTO DOS SERVIÇOS", "custo", "devedora", "sintetica", None, 420),
    ("4.2.01.01", "Gastos com Pessoal (operação)", "custo", "devedora", "analitica", 2230, 421),
    ("4.2.01.02", "Materiais aplicados nos serviços", "custo", "devedora", "analitica", 2371, 422),
    ("4.2.01.03", "Gastos gerais dos serviços", "custo", "devedora", "analitica", 2418, 423),
    ("4.5.01", "CUSTO DAS MERCADORIAS", "custo", "devedora", "sintetica", None, 450),
    ("4.5.01.01", "Custo das Mercadorias Vendidas (CMV)", "custo", "devedora", "analitica", 3091, 451),
    ("5", "DESPESAS OPERACIONAIS", "despesa", "devedora", "sintetica", None, 500),
    ("5.1.01", "DESPESAS COM VENDAS", "despesa", "devedora", "sintetica", None, 510),
    ("5.1.01.02", "Despesas com Vendas (comercial, OTA, propaganda)", "despesa", "devedora", "analitica", 3301, 512),
    ("5.1.02", "DESPESAS ADMINISTRATIVAS", "despesa", "devedora", "sintetica", None, 520),
    ("5.1.02.02", "Outros Gastos Administrativos", "despesa", "devedora", "analitica", 3665, 522),
    ("5.1.03", "DESPESAS E RECEITAS FINANCEIRAS", "despesa", "devedora", "sintetica", None, 530),
    ("5.1.03.01", "Receitas Financeiras", "despesa", "credora", "analitica", 3850, 531),
    ("5.1.03.02", "Despesas Financeiras (juros, taxas de cartão)", "despesa", "devedora", "analitica", 3926, 532),
]


def _pai(classificacao, existentes):
    """Maior prefixo (por pontos) que existe no conjunto."""
    partes = classificacao.split(".")
    for corte in range(len(partes) - 1, 0, -1):
        cand = ".".join(partes[:corte])
        if cand in existentes:
            return cand
    return None


def seed(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    codigos = {c[0] for c in CONTAS}
    criadas = {}
    for classif, nome, grupo, natureza, tipo, cod, ordem in CONTAS:
        obj, _ = ContaContabil.objects.get_or_create(
            classificacao=classif,
            defaults=dict(
                nome=nome, grupo=grupo, natureza=natureza, tipo=tipo,
                codigo_contador=cod, ordem=ordem,
            ),
        )
        criadas[classif] = obj
    # 2ª passada: amarra os pais
    for classif, obj in criadas.items():
        pai = _pai(classif, codigos)
        if pai and obj.conta_pai_id is None:
            obj.conta_pai = criadas[pai]
            obj.save(update_fields=["conta_pai"])


def unseed(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    # Apaga filhas antes dos pais (ordem reversa de classificação).
    for classif, *_ in sorted(CONTAS, key=lambda c: c[0], reverse=True):
        ContaContabil.objects.filter(classificacao=classif).delete()


class Migration(migrations.Migration):
    dependencies = [("contabil", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]

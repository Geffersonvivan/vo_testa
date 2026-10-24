"""
De-para das CategoriaFinanceira que já existem no banco.

Defensivo: SÓ cria linhas de MapeamentoContabil (uma por categoria). Nunca altera
nem apaga categorias/lançamentos existentes. Idempotente (get_or_create por
categoria). Mapeia por palavra-chave do nome; o que não casar vai para o
guarda-chuva do tipo (receita/despesa) e pode ser refinado depois pelo
assistente de órfãos.
"""

import unicodedata

from django.db import migrations

# palavra-chave (sem acento, minúscula) -> classificação da conta
CHAVES_RECEITA = [
    (("diaria", "hosped", "servic", "lavanderia", "day use", "evento"), "3.1.01.03"),
    (("consumo", "produto", "mercadoria", "bebida", "restaurante", "loja", "venda", "frigobar"), "3.1.01.01"),
    (("simples", "tribut", "imposto", "iss", "devolu", "abatimento"), "3.1.02.01"),
]
CHAVES_DESPESA = [
    (("honor", "contab", "advog"), "5.1.02.02"),
    (("propaganda", "publicid", "market", "comiss", "ota", "promo"), "5.1.01.02"),
    (("energia", "luz", "agua", "internet", "manuten", "telefone", "limpeza", "material", "utilidade"), "4.2.01.03"),
    (("salar", "folha", "pessoal", "fgts", "inss", "feria", "pro-labore", "pro labore", "13"), "4.2.01.01"),
    (("juros", "banc", "tarifa", "cartao", "financ", "adquir"), "5.1.03.02"),
]
PADRAO_RECEITA = "3.1.01.03"
PADRAO_DESPESA = "5.1.02.02"


def _sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _classif_para(nome, tipo):
    n = _sem_acento(nome)
    chaves = CHAVES_RECEITA if tipo == "receita" else CHAVES_DESPESA
    for termos, classif in chaves:
        if any(t in n for t in termos):
            return classif
    return PADRAO_RECEITA if tipo == "receita" else PADRAO_DESPESA


def seed(apps, schema_editor):
    CategoriaFinanceira = apps.get_model("nucleo", "CategoriaFinanceira")
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")

    for cat in CategoriaFinanceira.objects.all():
        if MapeamentoContabil.objects.filter(categoria_id=cat.id).exists():
            continue
        classif = _classif_para(cat.nome, cat.tipo)
        conta = ContaContabil.objects.filter(classificacao=classif).first()
        if not conta:
            continue
        MapeamentoContabil.objects.create(
            conta=conta, categoria_id=cat.id, prioridade=10,
            observacao="de-para inicial (migração)",
        )


def unseed(apps, schema_editor):
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")
    MapeamentoContabil.objects.filter(
        observacao="de-para inicial (migração)"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("contabil", "0003_seed_depara_padrao"),
        ("nucleo", "0004_formapagamento_pessoa_temporada_tipouh_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]

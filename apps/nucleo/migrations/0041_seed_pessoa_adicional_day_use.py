"""Seed best-effort do P.adic por categoria + preço do day use (Manual §2 / Parametros_CRM).

Casa pela categoria (palavra-chave no nome do TipoUH) e só preenche quando ainda está
zerado — idempotente e não sobrescreve ajuste feito no admin. Categorias com nome fora do
padrão ficam em R$0 para o dono preencher na tela. Day use recebe R$180/pessoa.
"""
from decimal import Decimal

from django.db import migrations

# Palavra-chave (minúscula) → P.adic. Ordem importa: "… mirante" antes do genérico.
REGRAS = [
    ("engenhoca mirante", Decimal("250.00")),
    ("historias mirante", Decimal("215.00")),
    ("histórias mirante", Decimal("215.00")),
    ("recepcao", Decimal("250.00")),
    ("recepção", Decimal("250.00")),
    ("engenhoca", Decimal("190.00")),
    ("historias", Decimal("160.00")),
    ("histórias", Decimal("160.00")),
    ("superior", Decimal("350.00")),
    ("central", Decimal("300.00")),
    ("hobbit", Decimal("400.00")),
]
PRECO_DAY_USE = Decimal("180.00")


def seed(apps, schema_editor):
    TipoUH = apps.get_model("nucleo", "TipoUH")
    for tipo in TipoUH.objects.all():
        if tipo.modalidade == "day_use":
            if not tipo.preco_day_use:
                tipo.preco_day_use = PRECO_DAY_USE
                tipo.save(update_fields=["preco_day_use"])
            continue
        if tipo.pessoa_adicional:
            continue
        nome = (tipo.nome or "").lower()
        for chave, valor in REGRAS:
            if chave in nome:
                tipo.pessoa_adicional = valor
                tipo.save(update_fields=["pessoa_adicional"])
                break


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0040_tipouh_pessoa_adicional_tipouh_preco_day_use"),
    ]

    operations = [migrations.RunPython(seed, noop)]

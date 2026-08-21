"""Filtro de moeda único do sistema (pt-BR).

Fonte única de formatação de dinheiro para templates e e-mails — por isso mora
no núcleo, não em Pagamentos. `{{ valor|intcomma_brl }}` → "R$ 1.600,00".

Regra de ouro: um só formatador. Não criar um segundo em outro app — dois
formatadores no mesmo sistema sempre divergem em algum caso.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def intcomma_brl(valor):
    """1600 → 'R$ 1.600,00' · -67.5 → '-R$ 67,50' · None/inválido → 'R$ 0,00'."""
    if valor is None or valor == "":
        return "R$ 0,00"
    try:
        v = Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return "R$ 0,00"

    inteiro, _, centavos = f"{abs(v):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = f"R$ {'.'.join(grupos)},{centavos}"
    return f"-{texto}" if v < 0 else texto

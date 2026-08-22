from django import template

from ..formatacao import frase

register = template.Library()


@register.filter
def frase_auditoria(registro):
    """Frase legível de um registro da trilha (ver apps/auditoria/formatacao.py)."""
    return frase(registro)

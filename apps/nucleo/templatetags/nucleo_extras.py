from django import template

from ..estrutura import capacidade as _capacidade
from ..estrutura import descricao_camas as _descricao_camas
from ..models import modulo_ativo as _modulo_ativo

register = template.Library()


@register.filter
def modulo_ativo(codigo):
    """Uso: {% if 'appsite'|modulo_ativo %} ... {% endif %}"""
    return _modulo_ativo(codigo)


@register.filter
def camas_uh(uh):
    """Frase de camas gerada da estrutura. Uso: {{ uh|camas_uh }}"""
    return _descricao_camas(uh)


@register.filter
def lotacao_uh(uh):
    """Lotação máxima da unidade (com crianças no sofá). Uso: {{ uh|lotacao_uh }}"""
    return _capacidade(uh)["maxima_criancas"]

import re

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# "reserva #25" / "Reserva #25" / "em reservas #7" → captura o rótulo + o número.
_RE_RESERVA = re.compile(r"(reservas?)\s+#(\d+)", re.IGNORECASE)


@register.filter
def linkar_reservas(texto):
    """Transforma 'reserva #NN' (na linha do tempo do lead) em link para o detalhe
    da reserva. Escapa o texto antes e insere só o <a> como HTML seguro. Se a rota
    não existir (módulo Reservas inativo), mantém o texto puro."""
    saida = escape(texto or "")

    def _sub(m):
        try:
            url = reverse("reservas:detalhe", args=[int(m.group(2))])
        except (NoReverseMatch, ValueError):
            return m.group(0)
        return f'{m.group(1)} <a href="{url}">#{m.group(2)}</a>'

    return mark_safe(_RE_RESERVA.sub(_sub, saida))

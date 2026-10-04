"""Exportação CSV segura (compartilhada pelo projeto).

Neutraliza CSV/formula-injection: uma célula que começa com =, +, -, @ (ou tab/CR)
é executável ao abrir no Excel/Sheets. Prefixamos com aspa simples para virar texto.
Padrão pt-BR: delimitador `;` + BOM (utf-8-sig) para o Excel abrir com acentos.
"""
from django.http import HttpResponse

_GATILHOS = ("=", "+", "-", "@", "\t", "\r")


def sanitizar_celula(v):
    """Devolve a célula neutralizada contra formula-injection."""
    s = "" if v is None else str(v)
    return ("'" + s) if s[:1] in _GATILHOS else s


def resposta_csv(filename: str) -> HttpResponse:
    """HttpResponse pronta para CSV pt-BR (charset utf-8-sig + BOM)."""
    resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")  # BOM p/ Excel pt-BR
    return resp

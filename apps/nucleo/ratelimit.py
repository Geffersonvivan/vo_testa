"""
Rate limiting leve por IP, via cache do Django (sem dependência nova).

Defesa em profundidade para endpoints públicos (webhook, link de pagamento, portal).
NOTA: em produção com múltiplos workers, use um cache COMPARTILHADO (Redis) — o
LocMemCache é por processo, então o limite fica por worker. Ainda assim reduz abuso
automatizado; a proteção primária de cada rota não depende disto.
"""
from django.core.cache import cache


def client_ip(request) -> str:
    """IP do cliente. Atrás de proxy (Railway), o 1º item de X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "desconhecido")


def limite_excedido(request, escopo: str, limite: int, janela_seg: int, sufixo: str = "") -> bool:
    """True se o IP passou de `limite` requisições em `janela_seg` para `escopo`.
    `sufixo` permite bucket adicional (ex.: token da cobrança)."""
    chave = f"rl:{escopo}:{client_ip(request)}:{sufixo}"
    cache.add(chave, 0, janela_seg)
    try:
        atual = cache.incr(chave)
    except ValueError:  # chave expirou entre add e incr
        cache.set(chave, 1, janela_seg)
        atual = 1
    return atual > limite

"""LP Fundador — servida direto do HTML oficial em LPs/LP_Fundador/ (fonte da verdade).

A raiz `/` serve a LP quando HOME_MODO='lp_fundador' (senão, o site normal). O formulário
posta JSON no endpoint do CRM e cai no funil (capturar_lead_site).
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services

_LP_PATH = Path(settings.BASE_DIR) / "LPs" / "LP_Fundador" / "LP_Fundador.html"
_LP_CACHE = {"html": None}

# Anti-abuso do endpoint público de lead (não é auth — só corta spam/bot):
_RATE_MAX = 6            # nº de leads aceitos por IP
_RATE_JANELA = 600       # … a cada 10 min
_MIN_MS = 1500           # tempo mínimo de preenchimento (bot posta instantâneo)
_VISITA_COOKIE = "lpv_fundador"   # conta 1 visita por navegador (dedupe reload)
_VISITA_TTL = 6 * 3600


def _lp_html() -> str:
    # Em produção lê uma vez (cache em memória); em DEBUG relê p/ editar ao vivo.
    if _LP_CACHE["html"] is None or settings.DEBUG:
        _LP_CACHE["html"] = _LP_PATH.read_text(encoding="utf-8")
    return _LP_CACHE["html"]


_BOTS = ("bot", "crawl", "spider", "facebookexternalhit", "whatsapp", "preview",
         "slurp", "bingpreview", "embedly", "quora", "pinterest", "telegrambot",
         "developers.google.com", "headless")


def _ip(request) -> str:
    """IP do cliente respeitando o proxy do Railway (X-Forwarded-For)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")) or "?"


def _contar_visita_lp(request):
    """+1 visita na Página de Captação 'fundador' (pula scrapers/preview de link)."""
    ua = (request.META.get("HTTP_USER_AGENT", "") or "").lower()
    if not ua or any(b in ua for b in _BOTS):
        return
    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug="fundador").first()
    if pagina:
        services.registrar_visita_pagina(pagina)


@never_cache
def servir_lp_fundador(request):
    """Renderiza a LP Fundador (HTML autocontido). Injeta o Google tag (env).

    `@never_cache`: sem isto, recarregar/voltar no histórico ou um proxy serviriam do
    cache e a visita nunca chegaria ao servidor — subcontando as métricas.
    Conta 1 visita por navegador (cookie `lpv_fundador`) — reload/back não infla.
    """
    html = _lp_html().replace("__GTAG_ID__", getattr(settings, "GOOGLE_TAG_ID", "") or "")
    resp = HttpResponse(html)
    if not request.COOKIES.get(_VISITA_COOKIE):
        try:
            _contar_visita_lp(request)
        except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
            pass
        resp.set_cookie(_VISITA_COOKIE, "1", max_age=_VISITA_TTL,
                        httponly=True, samesite="Lax",
                        secure=not settings.DEBUG)
    return resp


def privacidade(request):
    """Política de Privacidade (LGPD) — pública, linkada pela LP."""
    return render(request, "lp/privacidade.html")


def home_root(request):
    """Raiz `/`: LP Fundador quando ligada por env; senão o site público normal."""
    if getattr(settings, "HOME_MODO", "") == "lp_fundador":
        return servir_lp_fundador(request)
    from apps.site import views as site_views
    return site_views.home(request)


@csrf_exempt
@never_cache
@require_POST
def lp_fundador_lead(request):
    """Recebe o lead da LP (JSON) e joga no funil. Best-effort: nunca quebra a página."""
    try:
        dados = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "erro": "json inválido"}, status=400)

    # Anti-bot silencioso: honeypot preenchido ou envio instantâneo → finge sucesso
    # (não revela a defesa) e descarta sem criar lead nem chamar a CAPI.
    if (dados.get("empresa") or "").strip():
        return JsonResponse({"ok": True})
    try:
        ms = float(dados.get("ms") or 0)
    except (TypeError, ValueError):
        ms = 0
    if 0 < ms < _MIN_MS:
        return JsonResponse({"ok": True})

    # Rate limit por IP (corta flood de leads/CAPI). Best-effort — cache pode faltar.
    ip = _ip(request)
    try:
        chave = f"lp_lead_rate:{ip}"
        cache.add(chave, 0, _RATE_JANELA)
        if cache.incr(chave) > _RATE_MAX:
            return JsonResponse({"ok": True})  # silencioso
    except Exception:  # noqa: BLE001 — sem cache, segue sem rate limit
        pass

    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    whats = (dados.get("whatsapp") or dados.get("whats") or "").strip()
    if not nome or not (email or whats):
        return JsonResponse({"ok": False, "erro": "dados incompletos"}, status=400)

    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug="fundador").first()
    origem = dict(dados.get("rastreio") or {})
    origem.setdefault("origem_form", dados.get("origem") or "lp-fundador")
    try:
        services.capturar_lead_site(
            nome=nome, email=email, telefone=whats,
            tipo_interesse=(pagina.tipo_interesse if pagina else "hospedagem"),
            pagina=pagina, mensagem="Lista de espera — LP Fundador",
            origem=origem, aceita_email=bool(dados.get("consent", True)))
    except Exception:  # noqa: BLE001 — captação pública nunca estoura
        pass

    # Conversions API (Meta) pelo servidor — dedupe com o Pixel via event_id.
    try:
        ip = _ip(request)
        services.enviar_capi_lead(
            email=email, telefone=whats,
            event_id=(dados.get("event_id") or ""),
            fbp=(dados.get("fbp") or ""), fbc=(dados.get("fbc") or ""),
            event_source_url=request.META.get("HTTP_REFERER", ""),
            client_ip=ip, user_agent=request.META.get("HTTP_USER_AGENT", ""))
    except Exception:  # noqa: BLE001
        pass
    return JsonResponse({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# LP Fundador II — nova campanha (13/09/2026), servida em paralelo à Fundador
# original, em /lp/fundador-2/. Código ADITIVO: não altera a LP que está no ar.
# ─────────────────────────────────────────────────────────────────────────────
_LP2_PATH = (Path(settings.BASE_DIR) / "LPs" / "LP_Fundador_II_13_09_2026"
             / "LP_Fundador_II_13_09_2026.html")
_LP2_CACHE = {"html": None}
_LP2_SLUG = "fundador-2"                 # casa com a PaginaCaptacao e o utm_campaign
_VISITA2_COOKIE = "lpv_fundador_2"       # conta 1 visita por navegador (dedupe reload)


def _lp2_html() -> str:
    if _LP2_CACHE["html"] is None or settings.DEBUG:
        _LP2_CACHE["html"] = _LP2_PATH.read_text(encoding="utf-8")
    return _LP2_CACHE["html"]


def _qtd_fundadores() -> int:
    """Nº real de leads na lista de fundadores — prova social viva.

    Conta as DUAS LPs (Fundador + Fundador II): a prova social é a lista inteira,
    não só a LP II (que herdou os leads da original). Marcadores robustos = slug da
    página de captação + `origem_form` (não depende de texto de observação).
    """
    from django.db.models import Q

    from .models import Oportunidade
    try:
        return Oportunidade.objects.filter(
            Q(pagina_captacao__slug__in=("fundador", _LP2_SLUG))
            | Q(origem_rastreio__origem_form__in=("lp-fundador", "lp-fundador-2"))
        ).distinct().count()
    except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
        return 0


def _contar_visita_pagina(request, slug: str):
    """+1 visita na Página de Captação `slug` (pula scrapers/preview de link)."""
    ua = (request.META.get("HTTP_USER_AGENT", "") or "").lower()
    if not ua or any(b in ua for b in _BOTS):
        return
    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug=slug).first()
    if pagina:
        services.registrar_visita_pagina(pagina)


@never_cache
def servir_lp_fundador_2(request):
    """LP Fundador II (HTML autocontido) em /lp/fundador-2/. Injeta o Google tag."""
    html = _lp2_html().replace("__GTAG_ID__", getattr(settings, "GOOGLE_TAG_ID", "") or "")
    n = _qtd_fundadores()
    html = html.replace("__QTD_FUNDADORES__", str(n) if n else "56")  # fallback seguro
    resp = HttpResponse(html)
    if not request.COOKIES.get(_VISITA2_COOKIE):
        try:
            _contar_visita_pagina(request, _LP2_SLUG)
        except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
            pass
        resp.set_cookie(_VISITA2_COOKIE, "1", max_age=_VISITA_TTL,
                        httponly=True, samesite="Lax",
                        secure=not settings.DEBUG)
    return resp


@csrf_exempt
@never_cache
@require_POST
def lp_fundador_2_lead(request):
    """Lead da LP Fundador II (JSON) → funil, etiquetado na campanha fundador-2."""
    try:
        dados = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "erro": "json inválido"}, status=400)

    # Anti-bot silencioso: honeypot preenchido ou envio instantâneo → finge sucesso.
    if (dados.get("empresa") or "").strip():
        return JsonResponse({"ok": True})
    try:
        ms = float(dados.get("ms") or 0)
    except (TypeError, ValueError):
        ms = 0
    if 0 < ms < _MIN_MS:
        return JsonResponse({"ok": True})

    ip = _ip(request)
    try:
        chave = f"lp_lead_rate:{ip}"
        cache.add(chave, 0, _RATE_JANELA)
        if cache.incr(chave) > _RATE_MAX:
            return JsonResponse({"ok": True})  # silencioso
    except Exception:  # noqa: BLE001 — sem cache, segue sem rate limit
        pass

    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    whats = (dados.get("whatsapp") or dados.get("whats") or "").strip()
    if not nome or not (email or whats):
        return JsonResponse({"ok": False, "erro": "dados incompletos"}, status=400)

    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug=_LP2_SLUG).first()
    origem = dict(dados.get("rastreio") or {})
    origem.setdefault("origem_form", dados.get("origem") or "lp-fundador-2")
    try:
        services.capturar_lead_site(
            nome=nome, email=email, telefone=whats,
            tipo_interesse=(pagina.tipo_interesse if pagina else "hospedagem"),
            pagina=pagina, mensagem="Lista de espera — LP Fundador II",
            origem=origem, aceita_email=bool(dados.get("consent", True)),
            ip=ip, user_agent=request.META.get("HTTP_USER_AGENT", ""))
    except Exception:  # noqa: BLE001 — captação pública nunca estoura
        pass

    try:
        services.enviar_capi_lead(
            email=email, telefone=whats,
            event_id=(dados.get("event_id") or ""),
            fbp=(dados.get("fbp") or ""), fbc=(dados.get("fbc") or ""),
            event_source_url=request.META.get("HTTP_REFERER", ""),
            client_ip=ip, user_agent=request.META.get("HTTP_USER_AGENT", ""))
    except Exception:  # noqa: BLE001
        pass
    return JsonResponse({"ok": True})

"""LP Fundador — servida direto do HTML oficial em LPs/LP_Fundador/ (fonte da verdade).

A raiz `/` serve a LP quando HOME_MODO='lp_fundador' (senão, o site normal). O formulário
posta JSON no endpoint do CRM e cai no funil (capturar_lead_site).
"""
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services

_LP_PATH = Path(settings.BASE_DIR) / "LPs" / "LP_Fundador" / "LP_Fundador.html"
_LP_CACHE = {"html": None}


def _lp_html() -> str:
    # Em produção lê uma vez (cache em memória); em DEBUG relê p/ editar ao vivo.
    if _LP_CACHE["html"] is None or settings.DEBUG:
        _LP_CACHE["html"] = _LP_PATH.read_text(encoding="utf-8")
    return _LP_CACHE["html"]


def servir_lp_fundador(request):
    """Renderiza a LP Fundador (HTML autocontido)."""
    return HttpResponse(_lp_html())


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
    return JsonResponse({"ok": True})

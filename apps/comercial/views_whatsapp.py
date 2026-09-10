"""Webhook público do WhatsApp Cloud API (Meta) — fora do /crm, sem login.

- GET: handshake de verificação (hub.challenge) usando WHATSAPP_VERIFY_TOKEN.
- POST: eventos (mensagens recebidas + status de entrega) → services.processar_webhook.

Best-effort: sempre responde 200 rápido para a Meta não reenfileirar; erros são
engolidos e logados (a Meta reentrega em caso de não-2xx).
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services

logger = logging.getLogger(__name__)


def _assinatura_valida(request) -> bool:
    """Confere a assinatura X-Hub-Signature-256 (HMAC do corpo com o App Secret).

    Se WHATSAPP_APP_SECRET não estiver configurado, não checa (dev/simulado).
    """
    segredo = getattr(settings, "WHATSAPP_APP_SECRET", "")
    if not segredo:
        return True
    cabecalho = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    if not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(
        segredo.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecalho[len("sha256="):], esperado)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        # Verificação do webhook (Meta chama uma vez ao configurar).
        modo = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        desafio = request.GET.get("hub.challenge", "")
        esperado = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
        if modo == "subscribe" and esperado and token == esperado:
            return HttpResponse(desafio, content_type="text/plain")
        return HttpResponseForbidden("token inválido")

    # POST: eventos
    if not _assinatura_valida(request):
        return HttpResponseForbidden("assinatura inválida")
    try:
        payload = json.loads(request.body or b"{}")
        services.processar_webhook_whatsapp(payload)
    except Exception:  # noqa: BLE001 — nunca devolve erro pra Meta reenfileirar em loop
        logger.exception("Falha ao processar webhook do WhatsApp")
    return JsonResponse({"ok": True})

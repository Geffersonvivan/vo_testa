"""
Gateway do WhatsApp (conversa dentro do funil). Plugável por `WHATSAPP_GATEWAY`:
- **simulado** (default): sem rede — MVP/dev/testes. O envio "funciona" localmente.
- **cloud**: WhatsApp Business Platform (Meta Cloud API) — envio real (texto + template).
- **bsp**: via provedor (Twilio/360dialog/Zenvia) — stub.

Ver docs/Marketing/CRM_WhatsApp.md. A janela de 24h e os templates são regra da Meta;
no simulado o envio é sempre permitido para facilitar o teste. Envio real usa a Graph
API `/{phone-id}/messages` com Bearer token; sem dependência externa (urllib).
"""
from __future__ import annotations

import json
import logging
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def normalizar_telefone(telefone: str) -> str:
    """Número em formato E.164 (só dígitos) para a API. Assume Brasil (55) se faltar.

    Aceita '(49) 99143-8813', '49991438813', '5549...' → devolve '5549...'.
    """
    num = "".join(c for c in (telefone or "") if c.isdigit())
    if not num:
        return ""
    if num.startswith("55") and len(num) >= 12:
        return num
    return "55" + num


def _api_post(payload: dict) -> dict:
    """POST na Graph API do WhatsApp. Retorna {ok, id, erro}."""
    token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
    phone_id = getattr(settings, "WHATSAPP_CLOUD_PHONE_ID", "")
    if not (token and phone_id):
        raise ValidationError(
            "WhatsApp Cloud: configure WHATSAPP_CLOUD_TOKEN e WHATSAPP_CLOUD_PHONE_ID "
            "no .env (ou use WHATSAPP_GATEWAY=simulado).")
    versao = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    url = f"https://graph.facebook.com/{versao}/{phone_id}/messages"
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            corpo = json.loads(resp.read().decode("utf-8", "replace"))
            wamid = ""
            msgs = corpo.get("messages") or []
            if msgs:
                wamid = msgs[0].get("id", "")
            return {"ok": True, "id": wamid}
    except urlerror.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "id": "", "erro": f"HTTP {e.code}: {corpo}"}
    except Exception as e:  # rede, timeout, etc.
        return {"ok": False, "id": "", "erro": str(e)[:300]}


class GatewaySimulado:
    nome = "simulado"

    def enviar(self, conversa, texto: str) -> dict:
        logger.info("WHATSAPP[simulado] texto → %s: %s", conversa.telefone, texto[:60])
        return {"ok": True, "id": ""}

    def enviar_template(self, telefone: str, template: str, idioma: str = "pt_BR",
                        variaveis=None) -> dict:
        logger.info("WHATSAPP[simulado] template '%s' → %s vars=%s",
                    template, telefone, variaveis or [])
        return {"ok": True, "id": ""}


class GatewayCloud:
    nome = "cloud"

    def enviar(self, conversa, texto: str) -> dict:
        """Mensagem de texto livre (só válida dentro da janela de 24h — a Meta valida)."""
        return _api_post({
            "messaging_product": "whatsapp",
            "to": normalizar_telefone(conversa.telefone),
            "type": "text",
            "text": {"preview_url": False, "body": texto},
        })

    def enviar_template(self, telefone: str, template: str, idioma: str = "pt_BR",
                        variaveis=None) -> dict:
        """Template aprovado (inicia conversa / fora da janela). variaveis → {{1}}, {{2}}…"""
        componentes = []
        if variaveis:
            componentes.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in variaveis],
            })
        payload = {
            "messaging_product": "whatsapp",
            "to": normalizar_telefone(telefone),
            "type": "template",
            "template": {"name": template, "language": {"code": idioma}},
        }
        if componentes:
            payload["template"]["components"] = componentes
        return _api_post(payload)


class GatewayBsp:
    nome = "bsp"

    def enviar(self, conversa, texto: str) -> dict:
        raise ValidationError(
            "WhatsApp BSP: integração via provedor (Twilio/360dialog) ainda não "
            "implementada (stub). Use WHATSAPP_GATEWAY=simulado.")

    def enviar_template(self, telefone: str, template: str, idioma: str = "pt_BR",
                        variaveis=None) -> dict:
        raise ValidationError("WhatsApp BSP: template ainda não implementado (stub).")


_GATEWAYS = {"simulado": GatewaySimulado, "cloud": GatewayCloud, "bsp": GatewayBsp}


def get_whatsapp_gateway():
    nome = getattr(settings, "WHATSAPP_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"WHATSAPP_GATEWAY desconhecido: {nome!r}. Use: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

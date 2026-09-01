"""
Gateway do WhatsApp (conversa dentro do funil). Plugável por `WHATSAPP_GATEWAY`:
- **simulado** (default): sem rede — MVP/dev/testes. O envio "funciona" localmente.
- **cloud**: WhatsApp Business Platform (Meta Cloud API) — exige token/número (stub).
- **bsp**: via provedor (Twilio/360dialog/Zenvia) — stub.

Ver docs/Marketing/CRM_WhatsApp.md. A janela de 24h e os templates são regra da Meta;
no simulado o envio é sempre permitido para facilitar o teste.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class GatewaySimulado:
    nome = "simulado"

    def enviar(self, conversa, texto: str) -> dict:
        logger.info("WHATSAPP[simulado] → %s: %s", conversa.telefone, texto[:60])
        return {"ok": True, "id": ""}


class GatewayCloud:
    nome = "cloud"

    def enviar(self, conversa, texto: str) -> dict:
        token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
        numero = getattr(settings, "WHATSAPP_CLOUD_PHONE_ID", "")
        if not (token and numero):
            raise ValidationError(
                "WhatsApp Cloud: configure WHATSAPP_CLOUD_TOKEN e WHATSAPP_CLOUD_PHONE_ID "
                "no .env (ou use WHATSAPP_GATEWAY=simulado).")
        # Envio real (Graph API /{phone-id}/messages) fica para a Fase 2.
        raise ValidationError("WhatsApp Cloud: envio real ainda não implementado (stub).")


class GatewayBsp:
    nome = "bsp"

    def enviar(self, conversa, texto: str) -> dict:
        raise ValidationError(
            "WhatsApp BSP: integração via provedor (Twilio/360dialog) ainda não "
            "implementada (stub). Use WHATSAPP_GATEWAY=simulado.")


_GATEWAYS = {"simulado": GatewaySimulado, "cloud": GatewayCloud, "bsp": GatewayBsp}


def get_whatsapp_gateway():
    nome = getattr(settings, "WHATSAPP_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"WHATSAPP_GATEWAY desconhecido: {nome!r}. Use: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

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


def _baixar_media(media_id: str):
    """Baixa uma mídia do WhatsApp em 2 passos. Retorna (bytes, mime) ou (None, '').

    1. GET /{media_id} → resolve a URL temporária + mime_type.
    2. GET nessa URL COM o Bearer token (a URL expira em minutos).
    """
    token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
    versao = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    if not (token and media_id):
        return None, ""
    hdr = {"Authorization": f"Bearer {token}"}
    try:
        req = urlrequest.Request(
            f"https://graph.facebook.com/{versao}/{media_id}", headers=hdr)
        with urlrequest.urlopen(req, timeout=15) as resp:
            meta = json.loads(resp.read().decode("utf-8", "replace"))
        url = meta.get("url")
        mime = meta.get("mime_type", "")
        if not url:
            return None, mime
        with urlrequest.urlopen(urlrequest.Request(url, headers=hdr), timeout=30) as r2:
            return r2.read(), mime
    except Exception:  # noqa: BLE001 — download best-effort; o chamador trata None
        return None, ""


def _upload_media(conteudo: bytes, mime: str, filename: str = "audio.ogg") -> dict:
    """POST /{phone_id}/media (multipart). Retorna {ok, id, erro}."""
    import uuid
    token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
    phone_id = getattr(settings, "WHATSAPP_CLOUD_PHONE_ID", "")
    if not (token and phone_id):
        raise ValidationError("WhatsApp Cloud: configure WHATSAPP_CLOUD_TOKEN/PHONE_ID.")
    versao = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    url = f"https://graph.facebook.com/{versao}/{phone_id}/media"
    b = uuid.uuid4().hex

    def campo(nome, valor):
        return (f'--{b}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n'
                f'{valor}\r\n').encode()

    corpo = campo("messaging_product", "whatsapp") + campo("type", mime)
    corpo += (f'--{b}\r\nContent-Disposition: form-data; name="file"; '
              f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n').encode()
    corpo += conteudo + b"\r\n" + f"--{b}--\r\n".encode()
    req = urlrequest.Request(
        url, data=corpo, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urlrequest.urlopen(req, timeout=45) as resp:
            dado = json.loads(resp.read().decode("utf-8", "replace"))
            return {"ok": True, "id": dado.get("id", "")}
    except urlerror.HTTPError as e:
        return {"ok": False, "id": "", "erro": f"HTTP {e.code}: "
                f"{e.read().decode('utf-8', 'replace')[:300]}"}
    except Exception as e:  # noqa: BLE001
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

    def baixar_midia(self, media_id: str):
        """Sandbox: sem rede. Devolve (None, '') — o chamador grava só os metadados."""
        logger.info("WHATSAPP[simulado] baixar_midia %s", media_id)
        return None, ""

    def upload_midia(self, conteudo: bytes, mime: str, filename: str = "audio.ogg") -> dict:
        logger.info("WHATSAPP[simulado] upload_midia %s (%d bytes)", mime, len(conteudo or b""))
        return {"ok": True, "id": "sim-media"}

    def enviar_audio(self, conversa, media_id: str) -> dict:
        logger.info("WHATSAPP[simulado] áudio → %s (media %s)", conversa.telefone, media_id)
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

    def baixar_midia(self, media_id: str):
        """Baixa a mídia (áudio/voz) da Meta. Retorna (bytes, mime) ou (None, '')."""
        return _baixar_media(media_id)

    def upload_midia(self, conteudo: bytes, mime: str, filename: str = "audio.ogg") -> dict:
        """Sobe a mídia pra Meta e devolve o media id (p/ depois enviar por id)."""
        return _upload_media(conteudo, mime, filename)

    def enviar_audio(self, conversa, media_id: str) -> dict:
        """Mensagem de áudio (só válida dentro da janela de 24h — a Meta valida)."""
        return _api_post({
            "messaging_product": "whatsapp",
            "to": normalizar_telefone(conversa.telefone),
            "type": "audio",
            "audio": {"id": media_id},
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

    def baixar_midia(self, media_id: str):
        return None, ""

    def upload_midia(self, conteudo: bytes, mime: str, filename: str = "audio.ogg") -> dict:
        raise ValidationError("WhatsApp BSP: upload de mídia ainda não implementado (stub).")

    def enviar_audio(self, conversa, media_id: str) -> dict:
        raise ValidationError("WhatsApp BSP: áudio ainda não implementado (stub).")


_GATEWAYS = {"simulado": GatewaySimulado, "cloud": GatewayCloud, "bsp": GatewayBsp}


def get_whatsapp_gateway():
    nome = getattr(settings, "WHATSAPP_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"WHATSAPP_GATEWAY desconhecido: {nome!r}. Use: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

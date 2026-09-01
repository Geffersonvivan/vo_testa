"""
Gateway de Conversões de Mídia (Fase B do Gestor de Impulsionamento).

Devolve conversões (Lead, Compra/Reserva) ao Meta/Google para que o algoritmo
otimize por quem realmente paga — não só por quem preenche formulário. Casa a venda
ao anúncio pelos identificadores de clique (`fbclid`/`gclid`) capturados na Fase A.

Plugável por `MIDIA_GATEWAY` (settings):
- **simulado** (default): sem rede, retorna sucesso — dev/testes.
- **meta**: Meta Conversions API (exige META_CAPI_TOKEN + META_PIXEL_ID no .env).
- **google**: Google Ads Offline Conversion Import (exige developer token + OAuth2).

PRIVACIDADE: e-mail e telefone SEMPRE enviados com **hash SHA-256** (exigência das
plataformas). Nada de dado pessoal em texto puro.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def hash_email(valor: str) -> str:
    v = (valor or "").strip().lower()
    return hashlib.sha256(v.encode()).hexdigest() if v else ""


def hash_telefone(valor: str) -> str:
    """Só dígitos, com código do país (Brasil), depois SHA-256."""
    d = re.sub(r"\D", "", valor or "")
    if not d:
        return ""
    if not d.startswith("55"):
        d = "55" + d
    return hashlib.sha256(d.encode()).hexdigest()


def _get_json(url: str) -> dict:
    req = urlrequest.Request(url, method="GET")
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            return {"ok": True, "dados": json.loads(resp.read().decode("utf-8", "replace"))}
    except urlerror.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "erro": f"HTTP {e.code}: {corpo}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)[:300]}


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
            return {"ok": True, "id": "", "detalhe": body[:500]}
    except urlerror.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "erro": f"HTTP {e.code}: {corpo}"}
    except Exception as e:  # rede, timeout, etc.
        return {"ok": False, "erro": str(e)[:300]}


class GatewaySimulado:
    nome = "simulado"

    def enviar_conversao(self, evento: dict) -> dict:
        logger.info("MÍDIA[simulado] conversão %s ref=%s valor=%s",
                    evento.get("evento"), evento.get("ref"), evento.get("valor"))
        return {"ok": True, "id": f"sim-{evento.get('evento')}-{evento.get('ref')}",
                "detalhe": "simulado (sem rede)"}

    def sincronizar_gastos(self, campanha, desde, ate) -> list:
        """Sem rede: modo manual — não sincroniza gasto (retorna vazio)."""
        return []


class GatewayMeta:
    nome = "meta"

    def enviar_conversao(self, evento: dict) -> dict:
        token = getattr(settings, "META_CAPI_TOKEN", "")
        pixel = getattr(settings, "META_PIXEL_ID", "")
        if not (token and pixel):
            raise ValidationError(
                "Meta: configure META_CAPI_TOKEN e META_PIXEL_ID no .env "
                "(ou use MIDIA_GATEWAY=simulado).")
        user_data = {}
        if evento.get("email_hash"):
            user_data["em"] = [evento["email_hash"]]
        if evento.get("telefone_hash"):
            user_data["ph"] = [evento["telefone_hash"]]
        if evento.get("fbc"):
            user_data["fbc"] = evento["fbc"]
        dado = {
            "event_name": "Purchase" if evento["evento"] == "compra" else "Lead",
            "event_time": evento["event_time"],
            "event_id": evento["event_id"],  # dedup do lado do Meta
            "action_source": "website",
            "event_source_url": evento.get("landing_url", ""),
            "user_data": user_data,
        }
        if evento.get("valor"):
            dado["custom_data"] = {"currency": "BRL", "value": evento["valor"]}
        payload = {"data": [dado]}
        code = getattr(settings, "META_CAPI_TEST_CODE", "")
        if code:
            payload["test_event_code"] = code
        url = f"https://graph.facebook.com/v19.0/{pixel}/events?access_token={token}"
        return _post_json(url, payload)

    def sincronizar_gastos(self, campanha, desde, ate) -> list:
        """Marketing API (Insights): gasto diário da campanha (Fase C).

        Exige token com permissão ads_read (revisão do app) e a campanha com
        `id_externo` = ID da campanha no Meta. Retorna [{data, valor}].
        """
        token = getattr(settings, "META_CAPI_TOKEN", "")
        if not token:
            raise ValidationError("Meta: configure META_CAPI_TOKEN (com ads_read) no .env.")
        if not campanha.id_externo:
            return []
        params = (
            f"fields=spend&level=campaign&time_increment=1"
            f"&time_range={{'since':'{desde.isoformat()}','until':'{ate.isoformat()}'}}"
            f"&access_token={token}"
        )
        url = f"https://graph.facebook.com/v19.0/{campanha.id_externo}/insights?{params}"
        dados = _get_json(url)
        if not dados.get("ok"):
            raise ValidationError(f"Meta insights: {dados.get('erro')}")
        import datetime as _dt
        saida = []
        for linha in dados.get("dados", {}).get("data", []):
            try:
                d = _dt.date.fromisoformat(linha["date_start"])
                saida.append({"data": d, "valor": linha.get("spend", "0")})
            except (KeyError, ValueError):
                continue
        return saida


class GatewayGoogle:
    nome = "google"

    def enviar_conversao(self, evento: dict) -> dict:
        # Google Ads Offline Conversion Import exige developer token aprovado + OAuth2 +
        # customer id + ação de conversão. Sem a biblioteca/credenciais, erro claro.
        cid = getattr(settings, "GOOGLE_ADS_CUSTOMER_ID", "")
        acao = getattr(settings, "GOOGLE_ADS_CONVERSION_ACTION", "")
        if not (cid and acao):
            raise ValidationError(
                "Google: conversão offline requer developer token aprovado + OAuth2 "
                "(GOOGLE_ADS_CUSTOMER_ID/CONVERSION_ACTION). Use MIDIA_GATEWAY=simulado/meta.")
        # Integração real (google-ads) fica para quando o developer token sair.
        raise ValidationError(
            "Google: integração de conversão offline ainda não implementada (stub).")

    def sincronizar_gastos(self, campanha, desde, ate) -> list:
        # Google Ads API (relatórios) exige developer token aprovado + OAuth2.
        raise ValidationError(
            "Google: sincronização de gasto requer developer token aprovado (stub).")


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "meta": GatewayMeta,
    "google": GatewayGoogle,
}


def get_midia_gateway():
    nome = getattr(settings, "MIDIA_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"MIDIA_GATEWAY desconhecido: {nome!r}. Use um de: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

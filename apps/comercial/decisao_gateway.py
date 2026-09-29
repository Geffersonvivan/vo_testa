"""
Gateway de DECISÃO do lead (score/canal). Plugável por `DECISAO_GATEWAY`:
- **simulado** (default): sem rede — decide de forma DETERMINÍSTICA a partir das
  features do lead. Serve dev/CI e a **Fase 0 (sombra)** do piloto Jev.
- **jev**: TypeSafe AI (System One) — Score/Choice/Noul via HTTP. Best-effort;
  desligado até haver `JEV_API_URL` + `JEV_API_KEY` (formato do payload a confirmar
  na conta — ver docs/JEV_CRM_TEST.md).

Interface única: `avaliar_lead(features: dict) -> dict | None`, devolvendo
`{"score":0-100, "confianca":0-1, "canal":..., "qualificado":0-1, "modelo":str}`
ou **None** (o chamador cai na heurística — degradação graciosa). Enviamos só
FEATURES derivadas, nunca PII (nome/telefone/e-mail crus).
"""
from __future__ import annotations

import json
import logging
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Peso por origem (mesma leitura do funil, mas fórmula própria — 2ª opinião).
_ORIGEM = {
    "indicacao": 20, "site": 15, "whatsapp": 15, "telefone": 12,
    "agencia": 10, "presencial": 10, "outro": 4,
}


class GatewaySimulado:
    """Decisão determinística a partir das features — sem rede. Base da Fase 0."""

    nome = "simulado"

    def avaliar_lead(self, features: dict) -> dict:
        f = features or {}
        valor = f.get("valor_estimado") or 0
        score = 8
        if valor >= 2000:
            score += 34
        elif valor >= 800:
            score += 22
        elif valor > 0:
            score += 12
        if f.get("tem_datas"):
            score += 18
        ant = f.get("antecedencia_dias")
        if ant is not None and 0 <= ant <= 30:  # urgência aproxima a decisão
            score += 8
        score += _ORIGEM.get(f.get("origem"), 4)
        score += min(20, (f.get("n_atividades") or 0) * 5)
        if f.get("tem_cotacao"):
            score += 10
        score = max(0, min(100, score))

        sinais = ((1 if valor > 0 else 0)
                  + (1 if f.get("tem_datas") else 0)
                  + (1 if f.get("tem_cotacao") else 0)
                  + min(2, f.get("n_atividades") or 0))
        confianca = min(0.97, round(0.55 + 0.09 * sinais, 3))

        if f.get("origem") in ("telefone", "indicacao"):
            canal = "ligacao"
        elif f.get("tem_telefone"):
            canal = "whatsapp"
        elif f.get("tem_email"):
            canal = "email"
        else:
            canal = "whatsapp"

        q = 0.30
        if f.get("tem_telefone") or f.get("tem_email"):
            q += 0.35
        if f.get("tem_datas") or valor > 0:
            q += 0.25
        qualificado = round(min(1.0, q), 3)

        return {"score": score, "confianca": confianca, "canal": canal,
                "qualificado": qualificado, "modelo": "simulado-v1"}


class GatewayJev:
    """TypeSafe AI (System One). Best-effort — devolve None em qualquer erro."""

    nome = "jev"

    def avaliar_lead(self, features: dict) -> dict | None:
        url = getattr(settings, "JEV_API_URL", "")
        key = getattr(settings, "JEV_API_KEY", "")
        if not (url and key):
            raise ValidationError(
                "Jev: configure JEV_API_URL e JEV_API_KEY (ou use DECISAO_GATEWAY=simulado).")
        timeout = getattr(settings, "JEV_TIMEOUT_MS", 800) / 1000.0
        # Perguntas tipadas (Score/Choice/Noul) sobre o mesmo estado (features).
        # OBS: shape do payload/rota a confirmar na conta TypeSafe (ver plano).
        payload = {
            "state": features,
            "questions": [
                {"id": "conversao", "type": "score",
                 "prompt": "Probabilidade de a oportunidade converter em reserva (0-100)."},
                {"id": "canal", "type": "choice",
                 "prompt": "Melhor canal de 1º contato.",
                 "options": ["whatsapp", "ligacao", "email"]},
                {"id": "qualificado", "type": "noul",
                 "prompt": "Este lead é real/qualificado?"},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                corpo = json.loads(resp.read().decode("utf-8", "replace"))
        except (urlerror.URLError, ValueError, TimeoutError) as e:
            logger.warning("Jev indisponível (%s) — caindo na heurística.", e)
            return None
        try:
            ans = {a["id"]: a for a in corpo.get("answers", [])}
            return {
                "score": int(round(float(ans["conversao"]["score"]))),
                "confianca": round(float(ans["conversao"].get("confidence", 0)), 3),
                "canal": ans["canal"].get("choice") or "",
                "qualificado": round(float(ans["qualificado"].get("noul", 0)), 3),
                "modelo": corpo.get("model", "jev"),
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Jev: resposta em formato inesperado (%s).", e)
            return None


_GATEWAYS = {"simulado": GatewaySimulado, "jev": GatewayJev}


def get_decisao_gateway():
    nome = getattr(settings, "DECISAO_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"DECISAO_GATEWAY desconhecido: {nome!r}. Use: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

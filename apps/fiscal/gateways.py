"""
Gateway fiscal plugável. Escolha via `FISCAL_GATEWAY` no settings.

- `simulado` (default): sandbox — autoriza na hora com número/chave fake. Serve para
  testar o fluxo do módulo sem credencial nenhuma.
- `focus`: Focus NFe (recomendado; R$ 89,90/mês — ver docs/Implementar_fiscal.md).
  STUB — preencher endpoint/token quando a conta de homologação existir.
- `governo`: integração direta (NFS-e Nacional/ADN + NFC-e SEFAZ-SC), rota grátis.
  STUB — exige certificado A1 e assinatura de XML.
- `spedy`: Spedy (spedy.com.br) — NFS-e Nacional + NFC-e + NF-e via API REST única.
  STUB — defina SPEDY_API_KEY (+ certificado A1 no painel Spedy). Ver docs/Implementar_fiscal.md.

Interface: criar_documento(doc) -> dict; cancelar(doc, motivo) -> dict.
O dict de emissão pode conter: gateway, gateway_id, numero, serie, chave, protocolo,
xml_url, pdf_url, status ('autorizada'|'rejeitada'), motivo_rejeicao, payload.
"""
import uuid

from django.conf import settings
from django.utils import timezone


class GatewayFiscalBase:
    nome = "base"

    def emitir(self, documento) -> dict:
        raise NotImplementedError

    def cancelar(self, documento, motivo) -> dict:
        raise NotImplementedError


class GatewaySimulado(GatewayFiscalBase):
    """Sandbox: autoriza imediatamente com dados fake (para testes/demonstração)."""
    nome = "simulado"

    def emitir(self, documento) -> dict:
        gid = f"SIM-{uuid.uuid4().hex[:12].upper()}"
        chave = "".join(filter(str.isdigit, uuid.uuid4().hex))[:44].ljust(44, "0")
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "status": "autorizada",
            "numero": str(abs(hash(gid)) % 100000),
            "serie": "1",
            "chave": chave,
            "protocolo": gid,
            "xml_url": "",
            "pdf_url": "",
            "payload": {"sandbox": True, "emitido_em": timezone.now().isoformat()},
        }

    def cancelar(self, documento, motivo) -> dict:
        return {"cancelado": True, "motivo": motivo}


class GatewayFocus(GatewayFiscalBase):
    """Focus NFe — STUB. Preencher com base_url + token de homologação/produção.
    Docs: https://focusnfe.com.br/doc"""
    nome = "focus"

    def emitir(self, documento) -> dict:
        # TODO: montar payload conforme documento.tipo (nfse/nfce) e POST na API Focus,
        # usando settings.FISCAL_FOCUS_TOKEN e settings.FISCAL_FOCUS_URL.
        raise NotImplementedError(
            "Gateway Focus NFe ainda não configurado — defina FISCAL_FOCUS_TOKEN/URL "
            "e implemente a chamada (ver docs/Implementar_fiscal.md)."
        )

    def cancelar(self, documento, motivo) -> dict:
        raise NotImplementedError("Cancelamento Focus NFe não configurado.")


class GatewayGoverno(GatewayFiscalBase):
    """Integração direta com o governo (NFS-e Nacional/ADN + NFC-e SEFAZ-SC) — STUB.
    Rota grátis, porém exige certificado A1, assinatura de XML e webservices."""
    nome = "governo"

    def emitir(self, documento) -> dict:
        # TODO: gerar XML, assinar com o certificado A1, enviar ao ADN (NFS-e) ou
        # SEFAZ-SC (NFC-e), tratar retorno/contingência.
        raise NotImplementedError(
            "Gateway Governo (direto) ainda não implementado — exige certificado A1 e "
            "assinatura de XML (ver docs/Implementar_fiscal.md)."
        )

    def cancelar(self, documento, motivo) -> dict:
        raise NotImplementedError("Cancelamento direto no governo não implementado.")


class GatewaySpedy(GatewayFiscalBase):
    """
    Spedy (spedy.com.br) — NFS-e Nacional (+ NFC-e/NF-e) via API REST.

    Ambientes: prod `api.spedy.com.br/v1` · sandbox `sandbox-api.spedy.com.br/v1`.
    Auth: header `X-Api-Key` (a chave identifica a empresa — não se envia companyId).
    Emissão ASSÍNCRONA: o POST retorna `created/enqueued`; o status final (authorized/
    rejected) chega por **webhook** (`invoice.status_changed`). Idempotência: `integrationId`
    (= `DocumentoFiscal.referencia`). Cancelar: DELETE `/service-invoices/{id}` com `reason`.

    Pré-requisitos p/ produção (one-time, no painel Spedy): empresa cadastrada + settings
    (`series`/`issueType`) + **certificado A1**. NFC-e ainda espera a IE.
    """
    nome = "spedy"
    BASE_PROD = "https://api.spedy.com.br/v1"
    BASE_SANDBOX = "https://sandbox-api.spedy.com.br/v1"

    def base_url(self) -> str:
        return self.BASE_SANDBOX if getattr(settings, "SPEDY_SANDBOX", True) else self.BASE_PROD

    def _endpoint(self, documento) -> str:
        # SERVIÇO → NFS-e; CONSUMO → NFC-e (NF-e B2B fica para depois).
        return "service-invoices" if getattr(documento, "tipo", "nfse") == "nfse" else "consumer-invoices"

    def _http(self, method, path, body=None):
        import json
        import urllib.error
        import urllib.request

        from django.core.exceptions import ValidationError

        key = getattr(settings, "SPEDY_API_KEY", "")
        if not key:
            raise NotImplementedError(
                "Gateway Spedy não configurado — defina SPEDY_API_KEY e suba o certificado "
                "A1 no painel do Spedy (ver docs/Implementar_fiscal.md)."
            )
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url()}{path}", data=data, method=method,
            headers={"X-Api-Key": key, "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode() or "{}"
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode(errors="replace")[:500]
            raise ValidationError(f"Spedy recusou a requisição ({exc.code}): {detalhe}") from exc
        except urllib.error.URLError as exc:
            raise ValidationError(f"Spedy indisponível: {exc.reason}") from exc

    def _payload_nfse(self, documento) -> dict:
        p = {
            "integrationId": (documento.referencia or f"doc:{documento.pk}")[:36],
            "effectiveDate": timezone.now().isoformat(),
            "description": documento.descricao,
            "federalServiceCode": getattr(settings, "FISCAL_NFSE_LC116", "9.01"),
            "total": {
                "invoiceAmount": float(documento.valor),
                "issRate": float(getattr(settings, "FISCAL_NFSE_ISS_ALIQUOTA", "4.0")),
            },
        }
        tom = getattr(documento, "tomador", None)
        if tom:
            receiver = {"name": tom.nome}
            doc = "".join(filter(str.isdigit, tom.documento or ""))
            if doc:
                receiver["federalTaxNumber"] = doc
            if getattr(tom, "email", ""):
                receiver["email"] = tom.email
            p["receiver"] = receiver
        return p

    def emitir(self, documento) -> dict:
        if not getattr(settings, "SPEDY_API_KEY", ""):
            raise NotImplementedError(
                "Gateway Spedy não configurado — defina SPEDY_API_KEY e suba o certificado "
                "A1 no painel do Spedy (ver docs/Implementar_fiscal.md)."
            )
        if getattr(documento, "tipo", "nfse") != "nfse":
            raise NotImplementedError(
                "Spedy: só NFS-e implementada por ora — NFC-e aguarda a Inscrição Estadual."
            )
        payload = self._payload_nfse(documento)
        _status_http, resp = self._http("POST", "/service-invoices", payload)
        estado = (resp.get("status") or "created").lower()
        mapa = {"authorized": "autorizada", "rejected": "rejeitada"}
        return {
            "gateway": self.nome,
            "gateway_id": str(resp.get("id", "")),
            # created/enqueued/received → processando (o fecho vem por webhook)
            "status": mapa.get(estado, "processando"),
            "payload": {"integrationId": payload["integrationId"], "resposta": resp},
        }

    def cancelar(self, documento, motivo) -> dict:
        from django.core.exceptions import ValidationError
        if not documento.gateway_id:
            raise ValidationError("Spedy: documento sem id do gateway para cancelar.")
        self._http("DELETE", f"/service-invoices/{documento.gateway_id}", {"reason": motivo})
        return {"cancelado": True, "motivo": motivo}


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "focus": GatewayFocus,
    "governo": GatewayGoverno,
    "spedy": GatewaySpedy,
}


def get_gateway():
    nome = getattr(settings, "FISCAL_GATEWAY", "simulado")
    return _GATEWAYS.get(nome, GatewaySimulado)()

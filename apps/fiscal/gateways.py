"""
Gateway fiscal plugável. Escolha via `FISCAL_GATEWAY` no settings.

- `simulado` (default): sandbox — autoriza na hora com número/chave fake. Serve para
  testar o fluxo do módulo sem credencial nenhuma.
- `focus`: Focus NFe (recomendado; R$ 89,90/mês — ver docs/Implementar_fiscal.md).
  STUB — preencher endpoint/token quando a conta de homologação existir.
- `governo`: integração direta (NFS-e Nacional/ADN + NFC-e SEFAZ-SC), rota grátis.
  STUB — exige certificado A1 e assinatura de XML.

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


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "focus": GatewayFocus,
    "governo": GatewayGoverno,
}


def get_gateway():
    nome = getattr(settings, "FISCAL_GATEWAY", "simulado")
    return _GATEWAYS.get(nome, GatewaySimulado)()

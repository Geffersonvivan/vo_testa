"""
Abstração de gateway de pagamento.

- **simulado**: sandbox local (fim-a-fim sem provedor).
- **safrapay**: API e-commerce SafraPay (docs em developers.safrapay.com.br).
  Exige `SAFRAPAY_TOKEN` no .env. Sem token → ValidationError clara (não cai no simulado).
"""
from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.utils import timezone
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)


class GatewaySimulado:
    """Sandbox: gera identificadores/códigos fake e aceita estorno sempre."""
    nome = "simulado"

    def criar_cobranca(self, cobranca) -> dict:
        gid = f"SIM-{uuid.uuid4().hex[:16].upper()}"
        dados = {
            "gateway": self.nome,
            "gateway_id": gid,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {"sandbox": True, "metodo": cobranca.metodo},
        }
        if cobranca.metodo == cobranca.Metodo.PIX:
            dados["pix_copia_cola"] = (
                f"00020126VOTESTA{gid}5204000053039865802BR6009SAOPAULO62070503***6304SIM"
            )
        elif cobranca.metodo == cobranca.Metodo.CARTAO:
            dados["payload"]["checkout_url"] = f"/crm/pagamentos/pagar/{cobranca.token}/"
            dados["payload"]["instrucao"] = "Sandbox: use «Já paguei» para simular o cartão."
        elif cobranca.metodo == cobranca.Metodo.BOLETO:
            dados["payload"]["linha_digitavel"] = (
                f"23793.38128 60000.000003 00000.000400 1 {gid[-8:]}"
            )
            dados["payload"]["instrucao"] = "Sandbox: boleto simulado — use «Já paguei»."
        return dados

    def estornar(self, cobranca) -> dict:
        return {"estornado": True, "gateway_id": cobranca.gateway_id}


class GatewaySafrapay:
    """
    Provider SafraPay (homologação/produção via SAFRAPAY_ENV).

    Fluxo: Merchant Token → POST /v2/merchant/auth → Bearer accessToken →
    POST /v2/charge/pix (ou outros). Token vazio no portal = conta sem API liberada.
    """
    nome = "safrapay"
    CACHE_TOKEN = "safrapay_access_token"

    def _credenciais(self):
        token = (getattr(settings, "SAFRAPAY_TOKEN", "") or "").strip()
        merchant_id = (getattr(settings, "SAFRAPAY_ID", "") or "").strip()
        codigo = (getattr(settings, "SAFRAPAY_CODIGO_ATIVACAO", "") or "").strip()
        base = (getattr(settings, "SAFRAPAY_GATEWAY_URL", "") or "").rstrip("/")
        return {
            "token": token,
            "merchant_id": merchant_id,
            "codigo_ativacao": codigo,
            "base": base,
        }

    def _exigir_token(self):
        cred = self._credenciais()
        if not cred["token"]:
            raise ValidationError(
                "Safrapay: Token ausente no .env (SAFRAPAY_TOKEN). "
                "No portal Developers o campo Token precisa estar preenchido — "
                "solicite liberação da API e-commerce à SafraPay."
            )
        if not cred["base"]:
            raise ValidationError("Safrapay: SAFRAPAY_GATEWAY_URL não configurada.")
        return cred

    def _http(self, method, path, *, headers=None, body=None, timeout=30):
        cred = self._exigir_token()
        url = f"{cred['base']}{path}"
        data = None
        hdrs = {"Accept": "application/json", "User-Agent": "CRM-Vo-Testa/1.0"}
        if headers:
            hdrs.update(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        req = urlrequest.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw) if raw else {}
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            logger.warning("Safrapay HTTP %s %s → %s %s", method, path, exc.code, raw[:400])
            try:
                detalhe = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                detalhe = {"raw": raw[:500]}
            raise ValidationError(
                f"Safrapay recusou a requisição ({exc.code}). "
                f"Detalhe: {detalhe.get('message') or detalhe.get('erro') or raw[:200]}"
            ) from exc
        except urlerror.URLError as exc:
            raise ValidationError(f"Safrapay indisponível: {exc.reason}") from exc

    def _access_token(self) -> str:
        cached = cache.get(self.CACHE_TOKEN)
        if cached:
            return cached
        cred = self._exigir_token()
        status, data = self._http(
            "POST", "/v2/merchant/auth",
            headers={"Authorization": cred["token"]},
        )
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise ValidationError(
                "Safrapay: autenticação sem accessToken na resposta. "
                "Confira o Merchant Token (mk_…) no portal /keys."
            )
        # JWT típico ~ hours; cache conservador 50 min
        cache.set(self.CACHE_TOKEN, token, timeout=50 * 60)
        return token

    def _centavos(self, valor) -> int:
        return int((Decimal(str(valor)) * 100).quantize(Decimal("1")))

    def _customer(self, cobranca) -> dict:
        pagador = cobranca.pagador
        customer = {
            "name": (pagador.nome if pagador else "Cliente")[:120],
            "email": (getattr(pagador, "email", None) or "nao-informado@pousadavotesta.com.br"),
            "documentType": 1,  # CPF
            "document": "".join(
                c for c in (getattr(pagador, "documento", "") or "00000000000") if c.isdigit()
            )[:14] or "00000000000",
        }
        phone = "".join(c for c in (getattr(pagador, "telefone", "") or "") if c.isdigit())
        if len(phone) >= 10:
            customer["phone"] = {
                "countryCode": "55",
                "areaCode": phone[-11:-9] if len(phone) >= 11 else phone[:2],
                "number": phone[-9:] if len(phone) >= 11 else phone[2:],
                "type": 5,
            }
        return customer

    def _metadata(self, cobranca) -> list:
        return [
            {"key": "finalidade", "value": cobranca.finalidade},
            {"key": "cobranca_id", "value": str(cobranca.pk or "")},
            {"key": "reserva_id", "value": str(cobranca.reserva_id or "")},
        ]

    def _parse_charge(self, data, *, merchant_charge_id) -> tuple[str, dict]:
        charge = data.get("charge") or data
        gid = str(charge.get("id") or data.get("id") or "")
        if not gid:
            raise ValidationError("Safrapay: cobrança sem id na resposta.")
        return gid, charge

    def criar_cobranca(self, cobranca) -> dict:
        self._exigir_token()
        if cobranca.metodo == cobranca.Metodo.PIX:
            return self._criar_pix(cobranca)
        if cobranca.metodo == cobranca.Metodo.CARTAO:
            return self._criar_cartao(cobranca)
        if cobranca.metodo == cobranca.Metodo.BOLETO:
            return self._criar_boleto(cobranca)
        if cobranca.metodo == cobranca.Metodo.LINK:
            # Link = checkout hospedado; usa autorização com redirecionamento quando Token existir.
            return self._criar_cartao(cobranca, como_link=True)
        raise ValidationError(f"Safrapay: método '{cobranca.metodo}' não suportado.")

    def _criar_pix(self, cobranca) -> dict:
        access = self._access_token()
        merchant_charge_id = f"VT-{cobranca.pk or uuid.uuid4().hex[:8]}"
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "customer": self._customer(cobranca),
                "transactions": [
                    {"amount": self._centavos(cobranca.valor), "paymentType": "Pix"},
                ],
                "metadata": self._metadata(cobranca),
                "source": 1,
            }
        }
        _status, data = self._http(
            "POST", "/v2/charge/pix",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        pix = charge.get("qrCode") or data.get("qrCode") or ""
        if not pix:
            for tx in charge.get("transactions") or []:
                pix = tx.get("qrCode") or tx.get("emv") or pix
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "pix_copia_cola": pix,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {"safrapay": data, "merchantChargeId": merchant_charge_id},
        }

    def _criar_cartao(self, cobranca, *, como_link=False) -> dict:
        """Crédito à vista (autoCapture). Cartão de teste só em HML com Token."""
        access = self._access_token()
        merchant_charge_id = f"VT-{cobranca.pk or uuid.uuid4().hex[:8]}"
        # Sem dados de cartão na UI ainda: HML exige card no body — o operador
        # homologa com o cartão que a SafraPay indicar (painel / evidências).
        card = (cobranca.payload or {}).get("card") or {
            "cardholderName": "CLIENTE HOMOLOGACAO",
            "cardNumber": "4111111111111111",
            "expirationMonth": 12,
            "expirationYear": 2030,
            "securityCode": "123",
        }
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "customer": self._customer(cobranca),
                "transactions": [{
                    "card": card,
                    "paymentType": 2,
                    "amount": self._centavos(cobranca.valor),
                    "installmentNumber": max(1, int(cobranca.parcelas or 1)),
                    "installmentType": 0,
                    "autoCapture": True,
                }],
                "metadata": self._metadata(cobranca) + (
                    [{"key": "modo", "value": "link"}] if como_link else []
                ),
                "source": 1,
            }
        }
        _status, data = self._http(
            "POST", "/v2/charge/authorization",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {
                "safrapay": data,
                "merchantChargeId": merchant_charge_id,
                "checkout_url": f"/crm/pagamentos/pagar/{cobranca.token}/",
            },
        }

    def _criar_boleto(self, cobranca) -> dict:
        access = self._access_token()
        merchant_charge_id = f"VT-{cobranca.pk or uuid.uuid4().hex[:8]}"
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "customer": self._customer(cobranca),
                "transactions": [{
                    "amount": self._centavos(cobranca.valor),
                    "paymentType": "Boleto",
                }],
                "metadata": self._metadata(cobranca),
                "source": 1,
            }
        }
        _status, data = self._http(
            "POST", "/v2/charge/boleto",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        linha = (
            charge.get("digitableLine")
            or charge.get("linhaDigitavel")
            or data.get("digitableLine")
            or ""
        )
        if not linha:
            for tx in charge.get("transactions") or []:
                linha = tx.get("digitableLine") or tx.get("linhaDigitavel") or linha
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "expira_em": timezone.now() + timezone.timedelta(days=3),
            "payload": {
                "safrapay": data,
                "merchantChargeId": merchant_charge_id,
                "linha_digitavel": linha,
            },
        }

    def estornar(self, cobranca) -> dict:
        access = self._access_token()
        if not cobranca.gateway_id:
            raise ValidationError("Cobrança sem id no gateway para estornar.")
        _status, data = self._http(
            "PUT", f"/v2/charge/cancelation/{cobranca.gateway_id}",
            headers={"Authorization": f"Bearer {access}"},
            body={},
        )
        return {"estornado": True, "gateway_id": cobranca.gateway_id, "resposta": data}


def status_credenciais() -> dict:
    """Checklist das chaves Safrapay para a tela do CRM."""
    gateway = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado")
    env = getattr(settings, "SAFRAPAY_ENV", "hml")
    sid = bool((getattr(settings, "SAFRAPAY_ID", "") or "").strip())
    codigo = bool((getattr(settings, "SAFRAPAY_CODIGO_ATIVACAO", "") or "").strip())
    token = bool((getattr(settings, "SAFRAPAY_TOKEN", "") or "").strip())
    avisos = []
    if gateway == "safrapay" and not token:
        avisos.append(
            "Gateway apontado para safrapay, mas SAFRAPAY_TOKEN está vazio. "
            "Aguarde liberação no portal Developers → Keys."
        )
    if not sid:
        avisos.append("SAFRAPAY_ID ainda não preenchido no .env.")
    if not codigo:
        avisos.append("SAFRAPAY_CODIGO_ATIVACAO ainda não preenchido no .env.")
    if not token:
        avisos.append(
            "Token vazio é o esperado agora: a SafraPay só envia o Token "
            "depois das evidências de teste (Pix, cartão, boleto)."
        )
        avisos.append(
            "ID e Código de Ativação NÃO autenticam a API (teste HML → 401). "
            "Use o sandbox do CRM (simulado) para gerar o pacote de evidências."
        )
    pronto = gateway == "safrapay" and token and sid
    return {
        "gateway": gateway,
        "env": env,
        "gateway_url": getattr(settings, "SAFRAPAY_GATEWAY_URL", ""),
        "id_ok": sid,
        "codigo_ativacao_ok": codigo,
        "token_ok": token,
        "pronto_para_api": pronto,
        "avisos": avisos,
        "processo_homologacao": [
            "Integração no CRM já cobre Pix, cartão e boleto (provider Safrapay + sandbox).",
            "Gere o pacote de evidências nesta tela (3 cobranças sandbox + JSON no formato HML).",
            "Anexe prints + JSON no formulário de integração da SafraPay.",
            "Faça os testes que eles pedirem (ex.: cartão do titular deles) quando liberarem acesso HML.",
            "Só então o Token aparece em Developers → Keys.",
            "Cole SAFRAPAY_TOKEN, PAGAMENTOS_GATEWAY=safrapay, webhook /crm/pagamentos/webhook/.",
        ],
        "proximos_passos": [
            "Manter PAGAMENTOS_GATEWAY=simulado até o Token existir.",
            "Clicar em «Gerar evidências (Pix + cartão + boleto)» e baixar o JSON.",
            "Enviar evidências no formulário Safrapay / e-mail de integração.",
            "Quando o Token chegar: colar no .env e ligar o gateway safrapay em HML.",
        ],
    }


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "safrapay": GatewaySafrapay,
}


def get_gateway():
    nome = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"Gateway de pagamento desconhecido: {nome!r}. "
            f"Use um de: {', '.join(sorted(_GATEWAYS))}."
        )
    return cls()

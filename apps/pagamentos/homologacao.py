"""
Pacote de evidências para homologação Safrapay.

O Token da API só é liberado DEPOIS dos testes/evidências. Enquanto isso:
- o gateway ativo permanece `simulado`;
- geramos cobranças reais no CRM (Pix, cartão, boleto) + o JSON dos
  payloads no formato da API HML (`payment-hml.safrapay.com.br`), para
  anexar no formulário de integração da SafraPay.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .gateways import GatewaySafrapay, status_credenciais
from .models import Cobranca
from .services import criar_cobranca

# Pasta do repo: evidencias/safrapay/ (JSON + prints/)
DIR_EVIDENCIAS = Path(settings.BASE_DIR) / "evidencias" / "safrapay"
ARQUIVO_JSON = DIR_EVIDENCIAS / "safrapay-evidencias-homologacao.json"


def _centavos(valor) -> int:
    return int((Decimal(str(valor)) * 100).quantize(Decimal("1")))


def _customer_demo():
    return {
        "name": "Cliente Homologacao Vo Testa",
        "email": "homologacao@pousadavotesta.com.br",
        "documentType": 1,
        "document": "11144477735",
        "phone": {
            "countryCode": "55",
            "areaCode": "49",
            "number": "991438813",
            "type": 5,
        },
    }


def payloads_api_hml(*, valor_pix="10.00", valor_cartao="10.00", valor_boleto="10.00"):
    """Corpos que o CRM enviará à Safrapay HML quando o Token existir."""
    base = getattr(settings, "SAFRAPAY_GATEWAY_URL", "https://payment-hml.safrapay.com.br")
    customer = _customer_demo()
    return {
        "ambiente": getattr(settings, "SAFRAPAY_ENV", "hml"),
        "gateway_base": base,
        "auth": {
            "metodo": "POST",
            "path": "/v2/merchant/auth",
            "header": "Authorization: <SAFRAPAY_TOKEN / Merchant Token mk_…>",
            "nota": "Token só existe após a SafraPay liberar no portal /keys.",
        },
        "testes": [
            {
                "meio": "pix",
                "metodo": "POST",
                "path": "/v2/charge/pix",
                "body": {
                    "charge": {
                        "merchantChargeId": "VT-HML-PIX-DEMO",
                        "customer": customer,
                        "transactions": [{"amount": _centavos(valor_pix), "paymentType": "Pix"}],
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
            },
            {
                "meio": "cartao_credito_avista",
                "metodo": "POST",
                "path": "/v2/charge/authorization",
                "body": {
                    "charge": {
                        "merchantChargeId": "VT-HML-CARD-DEMO",
                        "customer": customer,
                        "transactions": [{
                            "card": {
                                "cardholderName": "CLIENTE HOMOLOGACAO",
                                "cardNumber": "4111111111111111",
                                "expirationMonth": 12,
                                "expirationYear": 2030,
                                "securityCode": "123",
                            },
                            "paymentType": 2,
                            "amount": _centavos(valor_cartao),
                            "installmentNumber": 1,
                            "installmentType": 0,
                            "autoCapture": True,
                        }],
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
                "nota": "Cartão de teste clássico — trocar pelo cartão/titular que a SafraPay pedir na homologação.",
            },
            {
                "meio": "boleto",
                "metodo": "POST",
                "path": "/v2/charge/boleto",
                "body": {
                    "charge": {
                        "merchantChargeId": "VT-HML-BOL-DEMO",
                        "customer": customer,
                        "transactions": [{
                            "amount": _centavos(valor_boleto),
                            "paymentType": "Boleto",
                        }],
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
            },
        ],
        "webhook_esperado": {
            "url_crm": "/crm/pagamentos/webhook/",
            "confirma_quando": "status paid/pago/captured → confirma pré-reserva (sinal)",
        },
        "credenciais_atuais": status_credenciais(),
        "gerado_em": timezone.now().isoformat(),
    }


def gerar_evidencias(operador, *, valor=Decimal("10.00")):
    """
    Cria 3 cobranças no sandbox local (Pix, cartão, boleto) e devolve o pacote
    JSON com os payloads HML + ids das cobranças para print/anexo.
    """
    valor = Decimal(str(valor))
    criadas = []
    for metodo, desc in (
        (Cobranca.Metodo.PIX, "Evidência HML · Pix"),
        (Cobranca.Metodo.CARTAO, "Evidência HML · Cartão à vista"),
        (Cobranca.Metodo.BOLETO, "Evidência HML · Boleto"),
    ):
        cob = criar_cobranca(
            operador,
            valor=valor,
            metodo=metodo,
            descricao=desc,
            finalidade=Cobranca.Finalidade.AVULSO,
        )
        criadas.append({
            "id": cob.pk,
            "metodo": cob.metodo,
            "valor": str(cob.valor),
            "token_publico": str(cob.token),
            "gateway": cob.gateway,
            "gateway_id": cob.gateway_id,
            "url_pagar": f"/crm/pagamentos/pagar/{cob.token}/",
            "pix_copia_cola": (cob.pix_copia_cola or "")[:80],
            "payload_keys": list((cob.payload or {}).keys()),
        })

    pacote = payloads_api_hml(
        valor_pix=str(valor), valor_cartao=str(valor), valor_boleto=str(valor),
    )
    pacote["cobrancas_sandbox_crm"] = criadas
    pacote["instrucoes"] = [
        "1. Anexe este JSON + prints das telas /crm/pagamentos/ e /pagar/<token>/ no formulário Safrapay.",
        "2. Mantenha PAGAMENTOS_GATEWAY=simulado até o Token aparecer em /keys.",
        "3. Com o Token: cole em SAFRAPAY_TOKEN, mude PAGAMENTOS_GATEWAY=safrapay, rode os mesmos meios em HML.",
        "4. Configure o webhook da Safrapay para https://<seu-dominio>/crm/pagamentos/webhook/",
    ]

    # Preview do que GatewaySafrapay montaria (sem chamar a rede).
    gw = GatewaySafrapay()
    pacote["provider_crm_suporta"] = {
        "pix": True,
        "cartao": hasattr(gw, "_criar_cartao"),
        "boleto": hasattr(gw, "_criar_boleto"),
        "bloqueio_atual": "SAFRAPAY_TOKEN vazio → API HML responde 401 (já verificado).",
    }
    DIR_EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    (DIR_EVIDENCIAS / "prints").mkdir(parents=True, exist_ok=True)
    pacote["pasta_evidencias"] = str(DIR_EVIDENCIAS)
    pacote["arquivo_json"] = str(ARQUIVO_JSON)
    ARQUIVO_JSON.write_text(
        json.dumps(pacote, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return pacote

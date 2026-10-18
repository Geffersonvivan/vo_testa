# Evidência — WABA bloqueada para envio (erro 141008)

**Empresa:** POUSADA VO TESTA LTDA — CNPJ 26.003.246/0001-00
**WABA ID:** 1055856203962312  ·  **Portfólio/Business ID:** 1320673763168182
**Número:** +55 49 2055-0000  ·  **Phone Number ID:** 1340621489131251
**App:** Pousada Vô Testa CRM — 28500031722959772
**Coletado em:** 2026-10-14 21:30 -03  ·  **Fonte:** Graph API v21.0

---

## Resumo do problema

A conta está **verificada e com a análise APROVADA**, o número está **registrado e CONNECTED**
no Cloud API, e **recebemos mensagens normalmente** (webhook ativo). **Porém não conseguimos
ENVIAR**: o `health_status` da WABA retorna `can_send_message: BLOCKED` com o **erro 141008 –
"The WABA status is not active"**. As entidades **BUSINESS** e **APP** aparecem como **AVAILABLE**;
somente a **WABA** está **BLOCKED**.

**Pedidos:** (1) ativar a WABA 1055856203962312 para envio (resolver 141008); (2) corrigir/
desvincular o faturamento regional (Índia) para o Brasil (BRL).

---

## 1. WABA — análise, verificação e health_status

```json
{
    "id": "1055856203962312",
    "account_review_status": "APPROVED",
    "business_verification_status": "verified",
    "health_status": {
        "can_send_message": "BLOCKED",
        "entities": [
            {
                "entity_type": "WABA",
                "id": "1055856203962312",
                "can_send_message": "BLOCKED",
                "errors": [
                    {
                        "error_code": 141008,
                        "error_description": "The WABA status is not active.",
                        "possible_solution": "Please contact the WhatsApp support team to activate the account."
                    }
                ]
            },
            {
                "entity_type": "BUSINESS",
                "id": "1320673763168182",
                "can_send_message": "AVAILABLE"
            },
            {
                "entity_type": "APP",
                "id": "28500031722959772",
                "can_send_message": "AVAILABLE"
            }
        ]
    }
}
```

## 2. Número — status e health_status

```json
{
    "status": "CONNECTED",
    "code_verification_status": "VERIFIED",
    "name_status": "AVAILABLE_WITHOUT_REVIEW",
    "quality_rating": "UNKNOWN",
    "health_status": {
        "can_send_message": "BLOCKED",
        "entities": [
            {
                "entity_type": "PHONE_NUMBER",
                "id": "1340621489131251",
                "can_send_message": "LIMITED",
                "can_receive_call_sip": "BLOCKED",
                "errors": [
                    {
                        "error_code": 138024,
                        "error_description": "WhatsApp Business calling cannot use SIP because it is not enabled",
                        "possible_solution": "Configure SIP using {PHONE_NUMBER_ID}/settings API"
                    }
                ],
                "additional_info": [
                    "Your display name has not been approved yet. Your message limit will increase after the display name is approved."
                ]
            },
            {
                "entity_type": "WABA",
                "id": "1055856203962312",
                "can_send_message": "BLOCKED",
                "errors": [
                    {
                        "error_code": 141008,
                        "error_description": "The WABA status is not active.",
                        "possible_solution": "Please contact the WhatsApp support team to activate the account."
                    }
                ]
            },
            {
                "entity_type": "BUSINESS",
                "id": "1320673763168182",
                "can_send_message": "AVAILABLE"
            },
            {
                "entity_type": "APP",
                "id": "28500031722959772",
                "can_send_message": "AVAILABLE",
                "can_receive_call_sip": "BLOCKED",
                "errors": [
                    {
                        "error_code": 138025,
                        "error_description": "This app cannot use SIP for WhatsApp Business calling because it has not configured a SIP server for this business phone number",
                        "possible_solution": "Configure SIP server using {PHONE_NUMBER_ID}/settings API"
                    }
                ]
            }
        ]
    },
    "id": "1340621489131251"
}
```

## 3. App inscrito no webhook (recebimento funciona)

```json
{
    "data": [
        {
            "whatsapp_business_api_data": {
                "link": "https://www.pousadavotesta.com.br/",
                "name": "Pousada V\u00f4 Testa CRM",
                "id": "28500031722959772"
            },
            "override_callback_uri": "https://www.pousadavotesta.com.br/whatsapp/webhook/"
        }
    ]
}
```

## 4. Tentativa de ENVIO recusada pela API (POST /{phone_id}/messages)

```json
{
    "error": {
        "message": "An unknown error has occurred.",
        "code": 1,
        "type": "OAuthException",
        "fbtrace_id": "APPXCe4XGOENCh9vs0B8QMN"
    }
}
```

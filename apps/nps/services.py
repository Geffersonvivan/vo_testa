from .proposta import PROPOSTA


def proposta() -> dict:
    """Contrato público da proposta NPS (UI e API stub)."""
    return PROPOSTA


def payload_stub(endpoint: str) -> dict:
    """Corpo JSON padrão dos endpoints ainda não implementados."""
    p = proposta()
    return {
        "status": "proposta",
        "implementado": False,
        "fase": p["fase"],
        "endpoint": endpoint,
        "mensagem": (
            "API NPS registrada; implementação na fase CRM do Hóspede. "
            "Ver docs/Proposta_NPS.md."
        ),
        "proposta": p["api"],
    }

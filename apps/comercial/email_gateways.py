"""
Gateway de e-mail (trilho 1:1 do lead + futura campanha em massa). Plugável por
`EMAIL_GATEWAY`:
- **simulado** (default): sem rede — MVP/dev/testes. "Envia" via console backend do
  Django (imprime no terminal) e devolve um message-id fake.
- **ses**: Amazon SES (Fase 4) — stub por ora.

Ver docs/Marketing/Gestor_email_leads_funil.md e Gestor_Email_MKT.md. Remetente 1:1 =
`comercial@pousadavotesta.com.br` (transacional); campanha em massa sairá de
`news.pousadavotesta.com.br` (SES) — nunca pelo mesmo remetente.
"""
from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection

logger = logging.getLogger(__name__)


class GatewaySimulado:
    """Envia pelo EMAIL_BACKEND do Django (console em dev, SMTP se EMAIL_HOST setado).

    Sem provedor externo (não é o SES). Se houver credenciais dedicadas do comercial
    (EMAIL_COMERCIAL_HOST_USER/PASSWORD), abre uma conexão SMTP própria e envia de fato
    "de" `comercial@`. Sem elas, cai no remetente global autenticado (ex.: naoresponda@)
    para não bater no anti-relay do provedor — mantendo o Reply-To no comercial@.
    """

    nome = "simulado"

    def enviar(self, *, para, assunto, html, texto, remetente, reply_to=None,
               headers=None) -> dict:
        host_user = getattr(settings, "EMAIL_COMERCIAL_HOST_USER", "")
        conexao = None
        de = remetente
        if host_user:
            conexao = get_connection(
                username=host_user,
                password=getattr(settings, "EMAIL_COMERCIAL_HOST_PASSWORD", ""),
            )
        elif getattr(settings, "EMAIL_HOST", ""):
            # SMTP sem conta dedicada do comercial → usa a conta autenticada global.
            de = getattr(settings, "DEFAULT_FROM_EMAIL", remetente)

        msg = EmailMultiAlternatives(
            subject=assunto, body=texto or "", from_email=de, to=[para],
            reply_to=[reply_to] if reply_to else None, headers=headers or {},
            connection=conexao,
        )
        if html:
            msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
        mid = f"SIM-{uuid.uuid4().hex[:16].upper()}"
        logger.info("EMAIL[simulado] → %s | de=%s | %s | %s", para, de, assunto, mid)
        return {"ok": True, "message_id": mid, "status": "enviado"}


class GatewaySes:
    """Amazon SES — Fase 4 (exige credenciais + domínio verificado)."""

    nome = "ses"

    def enviar(self, *, para, assunto, html, texto, remetente, reply_to=None,
               headers=None) -> dict:
        raise ValidationError(
            "EMAIL_GATEWAY=ses ainda não implementado (Fase 4 — SES real). "
            "Use EMAIL_GATEWAY=simulado por enquanto.")


_GATEWAYS = {"simulado": GatewaySimulado, "ses": GatewaySes}


def get_email_gateway():
    nome = getattr(settings, "EMAIL_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"EMAIL_GATEWAY desconhecido: {nome!r}. Use: {', '.join(sorted(_GATEWAYS))}.")
    return cls()

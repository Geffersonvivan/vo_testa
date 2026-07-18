"""E-mails transacionais do site (confirmação de reserva)."""
from email.mime.image import MIMEImage
from pathlib import Path
from urllib.parse import quote_plus

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats

from apps.site.models import ConfiguracaoSite

_EMAIL_IMG = Path(__file__).resolve().parent / "static" / "site" / "img" / "email"

# Horários padrão da pousada (exibidos no e-mail).
CHECKIN_HORA = "14:00"
CHECKOUT_HORA = "12:00"

# Razão social / CNPJ (rodapé legal do e-mail).
RAZAO_SOCIAL = "POUSADA VO TESTA LTDA"
CNPJ = "26.003.246/0001-00"


def url_recibo_reserva(reserva) -> str:
    """Link público da reserva (token opaco — não usa o código previsível)."""
    path = reverse("core:reserva_confirmada", args=[reserva.token])
    base = getattr(settings, "SITE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}{path}"


def _fmt_data_hora(data, hora: str) -> str:
    """Ex.: Qui., 12 de jul. · 14:00"""
    if not data:
        return "—"
    dia = formats.date_format(data, "D, d \\d\\e M.")
    return f"{dia} · {hora}"


def _ctx_confirmacao(reserva):
    config = ConfiguracaoSite.load()
    link = url_recibo_reserva(reserva)
    endereco = (config.endereco or "").strip()
    maps_q = quote_plus(endereco) if endereco else ""
    pago = reserva.status == "confirmada"
    return {
        "reserva": reserva,
        "config": config,
        "url_reserva": link,
        "metodo": reserva.get_metodo_pagamento_display(),
        "titulo": "Reserva Confirmada" if pago else "Reserva Registrada",
        "pago": pago,
        "chegada": _fmt_data_hora(reserva.data_checkin, CHECKIN_HORA),
        "partida": _fmt_data_hora(reserva.data_checkout, CHECKOUT_HORA),
        "endereco": endereco,
        "url_google_maps": (
            f"https://www.google.com/maps/search/?api=1&query={maps_q}" if maps_q else ""
        ),
        "url_apple_maps": f"https://maps.apple.com/?q={maps_q}" if maps_q else "",
        "url_whatsapp": (
            f"https://wa.me/{config.whatsapp}"
            f"?text={quote_plus(f'Olá! Sobre a reserva {reserva.codigo}')}"
            if config.whatsapp
            else ""
        ),
        "email_contato": config.email or "reservas@pousadavotesta.com.br",
        "instagram_url": config.instagram_url or "",
        "facebook_url": config.facebook_url or "",
        "razao_social": RAZAO_SOCIAL,
        "cnpj": CNPJ,
        "cid_hero": "email-hero",
        "cid_roda": "email-roda",
    }


def _anexar_imagens(msg: EmailMultiAlternatives) -> None:
    """Anexa imagens inline (CID). Hero da prancheta já inclui o brasão."""
    arquivos = [
        ("email-hero", _EMAIL_IMG / "hero.jpg", "jpeg"),
        ("email-roda", _EMAIL_IMG / "roda.png", "png"),
    ]
    for cid, path, subtype in arquivos:
        if not path.is_file():
            continue
        img = MIMEImage(path.read_bytes(), _subtype=subtype)
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=path.name)
        msg.attach(img)


def enviar_confirmacao(reserva, *, fail_silently=True) -> bool:
    """Envia a confirmação da reserva ao hóspede. Por padrão não quebra o fluxo
    de reserva (fail_silently): se o e-mail falhar, a reserva já está registrada."""
    email = getattr(reserva.hospede, "email", "")
    if not email:
        return False
    ctx = _ctx_confirmacao(reserva)
    assunto = f"{ctx['titulo']} {reserva.codigo} — Pousada Vô Testa"
    msg = EmailMultiAlternatives(
        assunto,
        render_to_string("site/emails/confirmacao.txt", ctx),
        settings.DEFAULT_FROM_EMAIL,
        [email],
        reply_to=[ctx["email_contato"]],
    )
    msg.attach_alternative(
        render_to_string("site/emails/confirmacao.html", ctx), "text/html"
    )
    _anexar_imagens(msg)
    msg.send(fail_silently=fail_silently)
    return True

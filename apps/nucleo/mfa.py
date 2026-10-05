"""MFA (TOTP) — helpers (Fase 4).

Opt-in para todos; obrigatório para superusuários. Segredo TOTP + códigos de backup
(guardados com hash do Django) ficam no `Usuario`. QR gerado inline (SVG) como no portal.
"""
import secrets

import pyotp
from django.contrib.auth.hashers import check_password, make_password

EMISSOR = "CRM Vô Testa"


def novo_secret() -> str:
    return pyotp.random_base32()


def uri_provisionamento(usuario, secret: str) -> str:
    """otpauth:// para o app autenticador (Google Authenticator, Authy, 1Password…)."""
    rotulo = usuario.get_username()
    return pyotp.TOTP(secret).provisioning_uri(name=rotulo, issuer_name=EMISSOR)


def verificar_totp(secret: str, codigo: str) -> bool:
    if not secret or not codigo:
        return False
    try:
        return pyotp.TOTP(secret).verify(codigo.strip().replace(" ", ""), valid_window=1)
    except Exception:  # noqa: BLE001 — código malformado
        return False


def gerar_backup_codes(n: int = 8) -> tuple[list[str], list[str]]:
    """Retorna (códigos em claro p/ mostrar UMA vez, hashes p/ gravar)."""
    claros = ["-".join((secrets.token_hex(2), secrets.token_hex(2))) for _ in range(n)]
    hashes = [make_password(c) for c in claros]
    return claros, hashes


def consumir_backup(usuario, codigo: str) -> bool:
    """Confere um código de backup; se bater, invalida (remove) e salva. Uso único."""
    codigo = (codigo or "").strip().lower()
    restantes = list(usuario.mfa_backup_codes or [])
    for h in restantes:
        if check_password(codigo, h):
            restantes.remove(h)
            usuario.mfa_backup_codes = restantes
            usuario.save(update_fields=["mfa_backup_codes"])
            return True
    return False


def qr_svg(uri: str) -> str:
    """SVG do QR do otpauth URI (inline, sem servir arquivo).

    Usa SvgPathImage (como o portal) — gera um <path> com viewBox que renderiza
    embutido no HTML. O SvgImage emite rects + prolog XML que quebram inline.
    """
    import qrcode
    import qrcode.image.svg
    from io import BytesIO

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def mfa_obrigatorio(usuario) -> bool:
    """Hoje: obrigatório para superusuários (decisão do dono). Os demais são opt-in."""
    return bool(getattr(usuario, "is_superuser", False))

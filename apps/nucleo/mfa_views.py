"""Views de MFA (TOTP) — desafio no login, ativação (QR + backup) e desativação.

Em arquivo próprio (não no nucleo/views.py, que está em WIP). Ver apps/nucleo/mfa.py.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import mfa
from .ratelimit import limite_excedido

Usuario = get_user_model()


@require_http_methods(["GET", "POST"])
def mfa_desafio(request):
    """Segundo fator após a senha. O usuário ainda NÃO está logado aqui."""
    uid = request.session.get("mfa_pending_user")
    if not uid:
        return redirect("login")
    user = Usuario.objects.filter(pk=uid, mfa_ativo=True).first()
    if not user:
        request.session.pop("mfa_pending_user", None)
        return redirect("login")
    erro = None
    if request.method == "POST":
        if limite_excedido(request, "mfa", limite=8, janela_seg=300):
            erro = "Muitas tentativas. Aguarde alguns minutos."
        else:
            codigo = request.POST.get("codigo", "")
            ok = mfa.verificar_totp(user.mfa_secret, codigo) or mfa.consumir_backup(user, codigo)
            if ok:
                destino = request.session.pop("mfa_next", None)
                request.session.pop("mfa_pending_user", None)
                auth_login(request, user)
                return redirect(destino or "dashboard")
            erro = "Código inválido. Tente de novo ou use um código de backup."
    return render(request, "registration/mfa_desafio.html", {"erro": erro})


@login_required
@require_http_methods(["GET", "POST"])
def mfa_ativar(request):
    """Ativa o MFA: mostra o QR, confirma com um código e revela os backups uma vez."""
    if request.user.mfa_ativo:
        messages.info(request, "Seu MFA já está ativo.")
        return redirect("mfa_config")
    # O segredo em provisionamento fica na sessão até ser confirmado.
    secret = request.session.get("mfa_secret_novo")
    if not secret:
        secret = mfa.novo_secret()
        request.session["mfa_secret_novo"] = secret
    erro = None
    if request.method == "POST":
        if mfa.verificar_totp(secret, request.POST.get("codigo", "")):
            claros, hashes = mfa.gerar_backup_codes()
            request.user.mfa_secret = secret
            request.user.mfa_ativo = True
            request.user.mfa_backup_codes = hashes
            request.user.save(update_fields=["mfa_secret", "mfa_ativo", "mfa_backup_codes"])
            request.session.pop("mfa_secret_novo", None)
            messages.success(request, "MFA ativado! Guarde os códigos de backup.")
            return render(request, "nucleo/mfa_backup.html", {"codigos": claros})
        erro = "Código inválido — confira o horário do celular e tente de novo."
    uri = mfa.uri_provisionamento(request.user, secret)
    return render(request, "nucleo/mfa_ativar.html", {
        "qr_svg": mfa.qr_svg(uri), "secret": secret, "erro": erro,
    })


@login_required
@require_http_methods(["GET", "POST"])
def mfa_config(request):
    """Status do MFA + desativar (exige senha; superusuário não pode desativar)."""
    erro = None
    if request.method == "POST" and request.user.mfa_ativo:
        if mfa.mfa_obrigatorio(request.user):
            erro = "MFA é obrigatório para a sua conta e não pode ser desativado."
        elif not request.user.check_password(request.POST.get("senha", "")):
            erro = "Senha incorreta."
        else:
            request.user.mfa_ativo = False
            request.user.mfa_secret = ""
            request.user.mfa_backup_codes = []
            request.user.save(update_fields=["mfa_ativo", "mfa_secret", "mfa_backup_codes"])
            messages.success(request, "MFA desativado.")
            return redirect("mfa_config")
    return render(request, "nucleo/mfa_config.html", {
        "erro": erro,
        "obrigatorio": mfa.mfa_obrigatorio(request.user),
        "restantes": len(request.user.mfa_backup_codes or []),
        "ativar_url": reverse("mfa_ativar"),
    })

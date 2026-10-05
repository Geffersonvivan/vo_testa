"""Content-Security-Policy (Fase 4 — defesa em profundidade de XSS).

Começa em REPORT-ONLY (`CSP_REPORT_ONLY=True`): o navegador NÃO bloqueia nada, só
reporta violações no console — dá pra observar o que a política pegaria antes de impor.
Quando estiver limpo, virar `CSP_REPORT_ONLY=False` para passar a bloquear.

A política permite o que o app realmente usa (HTMX/Alpine via unpkg, GTM, Google Fonts,
imagens de qualquer https p/ fotos de quarto e tour 360º). `'unsafe-inline'` em script/style
é necessário hoje (muitos inline + Alpine `x-...`); o passo seguinte do hardening é migrar
para nonce e remover o unsafe-inline.
"""
from django.conf import settings

_POLITICA = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net "
    "https://cdnjs.cloudflare.com https://www.googletagmanager.com https://connect.facebook.net",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' https://www.google-analytics.com https://graph.facebook.com",
    "frame-src 'self' https:",          # tour 360º (Kuula/Matterport/Street View) + GTM
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",           # anti-clickjacking (complementa X-Frame-Options)
    "form-action 'self'",
])


class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resposta = self.get_response(request)
        report_only = getattr(settings, "CSP_REPORT_ONLY", True)
        header = ("Content-Security-Policy-Report-Only" if report_only
                  else "Content-Security-Policy")
        resposta.setdefault(header, _POLITICA)
        return resposta


class MFAObrigatorioMiddleware:
    """Fase 4: superusuário sem MFA ativo é levado a ativar antes de usar o CRM."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.urls import reverse

        from .mfa import mfa_obrigatorio

        if getattr(settings, "TESTING", False):
            return self.get_response(request)
        user = getattr(request, "user", None)
        if (user and user.is_authenticated and mfa_obrigatorio(user) and not user.mfa_ativo):
            livres = {reverse("mfa_ativar"), reverse("login"), reverse("logout")}
            if (request.path not in livres
                    and not request.path.startswith(("/static/", "/media/"))):
                messages.warning(request, "Ative o MFA para continuar — é obrigatório na sua conta.")
                return redirect("mfa_ativar")
        return self.get_response(request)

"""LoginView com rate-limit (S-M1) + passo de MFA (Fase 4).

O login de funcionários (/crm/entrar/) é alvo de alto valor — contas de gerência abrem
caixa, estornam e veem PII/FNRH. Sem limite, fica exposto a brute-force/credential-stuffing.
Aqui limitamos por IP (o mesmo helper já usado em portal/pagamentos/site). Se o usuário tem
MFA ativo, a senha sozinha NÃO loga: redireciona para o desafio TOTP.
"""
from django.conf import settings
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect

from .ratelimit import limite_excedido


class LoginComLimite(LoginView):
    def post(self, request, *args, **kwargs):
        # Testes não passam pelo limite (evita flakiness por cache compartilhado).
        if not getattr(settings, "TESTING", False) and limite_excedido(
            request, "login", limite=10, janela_seg=300
        ):
            form = self.get_form()
            form.add_error(
                None, "Muitas tentativas de login. Aguarde alguns minutos e tente de novo."
            )
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Senha correta. Se o usuário tem MFA, não loga ainda — manda pro desafio."""
        user = form.get_user()
        if user.mfa_ativo and user.mfa_secret:
            self.request.session["mfa_pending_user"] = user.pk
            self.request.session["mfa_next"] = self.get_success_url()
            return redirect("mfa_desafio")
        return super().form_valid(form)

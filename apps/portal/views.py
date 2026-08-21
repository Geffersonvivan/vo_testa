from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo
from apps.nucleo.ratelimit import limite_excedido

from . import services
from .models import SolicitacaoPortal


def _estadia_ou_404(token):
    from apps.nucleo.models import modulo_ativo
    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    estadia = services.resolver(token)
    if not estadia:
        raise Http404()  # token inválido ou estadia encerrada
    return estadia


# ───────────────────────── Público (hóspede, por token) ─────────────────────────

@never_cache
def home(request, token):
    estadia = _estadia_ou_404(token)
    return render(request, "portal/home.html", {
        "token": token, "e": estadia,
        "cardapio": services.cardapio(),
    })


@never_cache
def nps(request, token):
    """Atalho NPS no portal — coleta real na fase CRM do Hóspede."""
    estadia = _estadia_ou_404(token)
    return render(request, "portal/nps.html", {"token": token, "e": estadia})


def pedir(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        pedidos = []
        for chave, valor in request.POST.items():
            if chave.startswith("qtd_") and valor.strip():
                pedidos.append((chave[4:], valor))
        try:
            comanda = services.pedir_restaurante(estadia, pedidos)
            messages.success(request, f"Pedido enviado! Comanda #{comanda.pk}.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("portal:home", token=token)


def solicitar(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        tipo = request.POST.get("tipo")
        if tipo == "limpeza":
            services.solicitar_limpeza(estadia)
            messages.success(request, "Limpeza extra solicitada. Já avisamos a governança.")
        elif tipo == "manutencao":
            services.solicitar_manutencao(estadia, request.POST.get("descricao", ""))
            messages.success(request, "Solicitação registrada. A manutenção vai atender.")
    return redirect("portal:home", token=token)


def checkout(request, token):
    estadia = _estadia_ou_404(token)
    return render(request, "portal/checkout.html", {"token": token, "e": estadia})


def pagar_saldo(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        try:
            cobranca = services.cobrar_saldo(estadia, request.POST.get("metodo") or "pix")
            services.solicitar_checkout(estadia)
            return redirect("pagamentos:pagar", token=cobranca.token)
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("portal:checkout", token=token)


def solicitar_checkout_recepcao(request, token):
    estadia = _estadia_ou_404(token)
    if request.method == "POST":
        services.solicitar_checkout(estadia)
        messages.success(request, "Check-out solicitado. A recepção vai finalizar.")
    return redirect("portal:home", token=token)


# ───────────────────────── Pré check-in (FNRH) — hóspede, por token ─────────────

@never_cache
def checkin(request, token):
    """Check-in online: o hóspede responsável preenche a FNRH de todos num só
    aparelho. Funciona antes da hospedagem (reserva ainda ativa)."""
    from apps.nucleo.models import modulo_ativo

    from apps.reservas import services as reservas_services

    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    # TM-003: rate limit por IP — abranda brute-force de token e abuso da PII.
    if limite_excedido(request, "fnrh_portal", limite=30, janela_seg=60):
        return HttpResponse("Muitas requisições. Aguarde um momento.", status=429)
    acesso = services.acesso_por_token(token)
    if not acesso:
        raise Http404()
    reserva, queryset = reservas_services.preparar_fnrh(acesso.reserva_id)
    if reserva is None or not reserva.ativa:
        raise Http404()

    if request.method == "POST":
        formset = reservas_services.fnrh_formset(data=request.POST, queryset=queryset)
        if formset.is_valid():
            fichas = formset.save()
            reservas_services.marcar_fichas_preenchidas(
                fichas or queryset, origem="portal"
            )
            messages.success(request, "Ficha enviada. Obrigado!")
            return redirect("portal:checkin", token=token)
        messages.error(request, "Confira os campos destacados.")
    else:
        formset = reservas_services.fnrh_formset(queryset=queryset)

    fichas = list(reserva.fichas_fnrh.all())
    return render(request, "portal/checkin.html", {
        "token": token, "formset": formset, "reserva": reserva,
        "pronta": reserva.fnrh_pronta,
        "total": len(fichas),
        "completas": sum(1 for f in fichas if f.completa),
    })


# ───────────────────────── Recepção (staff): QR do hóspede ─────────────────────────

@requer_modulo(Modulo.APPSITE)
def qr(request, reserva_id):
    from apps.reservas.services import estadia_ativa
    if not estadia_ativa(reserva_id):
        raise Http404("Reserva não está hospedada.")
    acesso = services.get_acesso(reserva_id)
    url = request.build_absolute_uri(reverse("portal:home", args=[acesso.token]))
    return render(request, "portal/qr.html", {
        "url": url, "svg": _qr_svg(url), "reserva_id": reserva_id,
    })


@requer_modulo(Modulo.APPSITE)
def qr_fnrh(request, reserva_id):
    """QR do pré check-in: o hóspede lê e preenche a FNRH antes de chegar."""
    from apps.reservas.services import preparar_fnrh
    reserva, _ = preparar_fnrh(reserva_id)
    if reserva is None or not reserva.ativa:
        raise Http404("Reserva não está ativa.")
    acesso = services.get_acesso(reserva_id)
    url = request.build_absolute_uri(reverse("portal:checkin", args=[acesso.token]))
    return render(request, "portal/qr.html", {
        "url": url, "svg": _qr_svg(url), "reserva_id": reserva_id,
        "finalidade": "FNRH (check-in online)",
    })


def _qr_svg(url):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    from io import BytesIO
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@requer_modulo(Modulo.APPSITE)
def solicitacoes(request):
    """Painel interno das solicitações vindas do portal."""
    return render(request, "portal/solicitacoes.html", {
        "solicitacoes": SolicitacaoPortal.objects.all()[:100],
    })

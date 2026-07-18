from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo

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

import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.models import Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .gateways import status_credenciais
from .models import Cobranca, EventoPagamento


def _reservas_para_sinal(request):
    if not request.user.pode_acessar(Modulo.RESERVAS):
        return []
    from apps.reservas.services import pendentes_de_sinal
    return pendentes_de_sinal()


@never_cache
@requer_modulo(Modulo.PAGAMENTOS)
def painel(request):
    return render(request, "pagamentos/painel.html", {
        "cobrancas": Cobranca.objects.select_related("pagador")[:60],
        "pagadores": pessoas_agrupadas(),
        "metodos": Cobranca.Metodo.choices,
        "finalidades": Cobranca.Finalidade.choices,
        "reservas": _reservas_para_sinal(request),
        "conciliacao": services.conciliacao(),
        "safrapay": status_credenciais(),
    })


@never_cache
@requer_modulo(Modulo.PAGAMENTOS)
def safrapay(request):
    """Checklist das chaves Safrapay e próximos passos (sem expor segredos)."""
    return render(request, "pagamentos/safrapay.html", {
        "safrapay": status_credenciais(),
    })


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def safrapay_evidencias(request):
    """Gera cobranças sandbox (Pix/cartão/boleto) + JSON no formato API HML."""
    from django.http import HttpResponse

    from .homologacao import gerar_evidencias

    try:
        pacote = gerar_evidencias(request.user)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("pagamentos:safrapay")
    messages.success(
        request,
        f"Evidências geradas: cobranças "
        f"#{pacote['cobrancas_sandbox_crm'][0]['id']}, "
        f"#{pacote['cobrancas_sandbox_crm'][1]['id']}, "
        f"#{pacote['cobrancas_sandbox_crm'][2]['id']} "
        f"(Pix, cartão, boleto). JSON salvo em evidencias/safrapay/ — "
        f"coloque os prints em evidencias/safrapay/prints/.",
    )
    body = json.dumps(pacote, ensure_ascii=False, indent=2)
    resp = HttpResponse(body, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = (
        'attachment; filename="safrapay-evidencias-homologacao.json"'
    )
    return resp


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def criar(request):
    pagador = Pessoa.objects.filter(pk=request.POST.get("pagador") or None).first()
    try:
        cobranca = services.criar_cobranca(
            request.user,
            valor=request.POST.get("valor"),
            metodo=request.POST.get("metodo"),
            descricao=request.POST.get("descricao", "").strip(),
            finalidade=request.POST.get("finalidade") or Cobranca.Finalidade.AVULSO,
            pagador=pagador,
            reserva_id=request.POST.get("reserva_id") or None,
            parcelas=request.POST.get("parcelas") or 1,
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("pagamentos:painel")
    return redirect("pagamentos:detalhe", pk=cobranca.pk)


@requer_modulo(Modulo.PAGAMENTOS)
def detalhe(request, pk):
    cobranca = get_object_or_404(
        Cobranca.objects.select_related("pagador", "criado_por").prefetch_related("eventos"), pk=pk
    )
    return render(request, "pagamentos/detalhe.html", {
        "cobranca": cobranca, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def simular(request, pk):
    """Simula o webhook do gateway confirmando o pagamento (sandbox)."""
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.confirmar_pagamento(cobranca, request.user, origem="simulado")
        messages.success(request, "Pagamento confirmado (sandbox).")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def cancelar(request, pk):
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.cancelar(cobranca, request.user)
        messages.success(request, "Cobrança cancelada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


@requer_gerencia
@require_POST
def estornar(request, pk):
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.estornar(cobranca, request.user)
        messages.success(request, "Cobrança estornada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


# ───────── Público (link de pagamento) + webhook do gateway ─────────

def pagar(request, token):
    """Página pública do link de pagamento (sem login)."""
    cobranca = get_object_or_404(Cobranca, token=token)
    return render(request, "pagamentos/pagar.html", {
        "cobranca": cobranca,
        "url_recibo_site": _url_recibo_site(cobranca),
    })


@require_POST
def pagar_simular(request, token):
    """Botão 'já paguei' da página pública (sandbox = dispara o webhook)."""
    cobranca = get_object_or_404(Cobranca, token=token)
    try:
        services.confirmar_pagamento(cobranca, cobranca.criado_por, origem="link_publico")
    except ValidationError:
        pass
    cobranca.refresh_from_db()
    # Sinal do site: leva o hóspede de volta ao recibo da reserva.
    destino = _url_recibo_site(cobranca)
    if destino and cobranca.status == Cobranca.Status.PAGO:
        return redirect(destino)
    return redirect("pagamentos:pagar", token=token)


def _url_recibo_site(cobranca):
    """URL da confirmação no site, se a cobrança for sinal de uma reserva do canal."""
    if cobranca.finalidade != Cobranca.Finalidade.SINAL:
        return None
    try:
        from django.urls import reverse
        from apps.site.models import Reserva as SiteReserva
    except Exception:
        return None
    recibo = None
    if cobranca.reserva_id:
        recibo = SiteReserva.objects.filter(crm_reserva_id=cobranca.reserva_id).first()
    if not recibo:
        recibo = SiteReserva.objects.filter(pagamento_id=str(cobranca.token)).first()
    if not recibo:
        return None
    return reverse("core:reserva_confirmada", args=[recibo.token])


# Status que confirmam pagamento (doc SafraPay + sandbox sem status).
_STATUS_PAGO = {
    "paid", "pago", "captured", "authorized", "consolidated",
    "2", "3", "4",
}
_STATUS_PENDENTE = {
    "pending", "pendente", "ordered", "created", "1",
}


@csrf_exempt
@require_POST
def webhook(request):
    """Endpoint do gateway (simulado form ou JSON SafraPay). Idempotente."""
    gid, status_gw, body = _extrair_webhook(request)
    cobranca = Cobranca.objects.filter(gateway_id=gid).first() if gid else None
    if not cobranca:
        return _json({"erro": "cobrança não encontrada"}, 404)
    EventoPagamento.objects.create(
        cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
        origem="webhook", detalhe={"gateway_id": gid, "status": status_gw, "body": body},
    )
    st = str(status_gw).lower() if status_gw is not None else None
    if st in _STATUS_PENDENTE:
        return _json({"ok": True, "status": cobranca.status, "ignorado": "ainda pendente"})
    # Sem status (sandbox) ou status pago → confirma.
    if st is not None and st not in _STATUS_PAGO:
        return _json({"ok": True, "status": cobranca.status, "ignorado": f"status={status_gw}"})
    try:
        services.confirmar_pagamento(cobranca, cobranca.criado_por, origem="webhook")
    except ValidationError as erro:
        return _json({"erro": " ".join(erro.messages)}, 400)
    cobranca.refresh_from_db()
    return _json({"ok": True, "status": cobranca.status})


def _extrair_webhook(request):
    """Aceita form (sandbox) ou JSON SafraPay com charge.id / status."""
    gid = request.POST.get("gateway_id") or request.GET.get("gateway_id")
    status_gw = request.POST.get("status") or request.GET.get("status")
    body = {}
    ctype = request.content_type or ""
    if "json" in ctype:
        try:
            raw = (request.body or b"").strip()
        except Exception:
            raw = b""
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            charge = body.get("charge") if isinstance(body, dict) else None
            if not isinstance(charge, dict):
                charge = body if isinstance(body, dict) else {}
            gid = gid or str(
                charge.get("id") or body.get("gateway_id") or body.get("id") or ""
            )
            status_gw = status_gw or charge.get("status") or body.get("status")
            if isinstance(status_gw, dict):
                status_gw = status_gw.get("name") or status_gw.get("value")
    return gid or None, status_gw, body


def _json(data, status=200):
    from django.http import JsonResponse
    return JsonResponse(data, status=status)

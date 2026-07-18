import json

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import DocumentoFiscal


@never_cache
@requer_modulo(Modulo.FISCAL)
def painel(request):
    docs = DocumentoFiscal.objects.select_related("tomador", "criado_por")[:60]
    return render(request, "fiscal/painel.html", {
        "documentos": docs,
        "gateway": getattr(settings, "FISCAL_GATEWAY", "simulado"),
        "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.FISCAL)
def detalhe(request, pk):
    doc = get_object_or_404(
        DocumentoFiscal.objects.select_related("tomador", "criado_por")
        .prefetch_related("eventos"), pk=pk
    )
    return render(request, "fiscal/detalhe.html", {
        "doc": doc, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.FISCAL)
def emitir_nfse(request):
    """Emite a NFS-e da hospedagem a partir da conta (chamado do detalhe da reserva)."""
    if request.method == "POST":
        try:
            doc = services.emitir_nfse_da_conta(request.POST.get("conta_id"), request.user)
            messages.success(request, f"NFS-e {doc.get_status_display().lower()} (#{doc.pk}).")
            return redirect("fiscal:detalhe", pk=doc.pk)
        except (ValidationError, NotImplementedError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else str(erro)
            messages.error(request, msg)
    return redirect("fiscal:painel")


@csrf_exempt
@require_POST
def webhook(request):
    """Recebe o retorno do Focus NFe (autorização/cancelamento da nota) e atualiza o
    documento (status + PDF/DANFSE + XML). Configurar esta URL no painel do Focus."""
    # Valida o header de autorização (mesmo segredo posto na 'Chave de Autorização' do Focus).
    esperado = getattr(settings, "FISCAL_WEBHOOK_TOKEN", "")
    if esperado and request.headers.get("Authorization") != esperado:
        return JsonResponse({"erro": "não autorizado"}, status=401)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        payload = request.POST.dict()
    doc = services.processar_retorno_focus(payload)
    if not doc:
        return JsonResponse({"erro": "documento (ref) não encontrado"}, status=404)
    return JsonResponse({"ok": True, "status": doc.status})


@requer_gerencia
def cancelar(request, pk):
    doc = get_object_or_404(DocumentoFiscal, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar(doc, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Documento cancelado.")
        except (ValidationError, NotImplementedError) as erro:
            messages.error(request, str(getattr(erro, "messages", [str(erro)])[0]
                                        if isinstance(erro, ValidationError) else erro))
    return redirect("fiscal:detalhe", pk=pk)

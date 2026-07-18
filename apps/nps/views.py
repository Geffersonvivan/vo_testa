from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services


@never_cache
@login_required
def painel(request):
    """Sidebar CRM: proposta registrada (sem coleta real nesta fase)."""
    return render(request, "nps/painel.html", {"proposta": services.proposta()})


def _stub(request, endpoint: str):
    return JsonResponse(services.payload_stub(endpoint), status=501)


@csrf_exempt
@require_http_methods(["POST"])
def api_criar_resposta(request):
    return _stub(request, "POST /api/nps/v1/respostas/")


@login_required
@require_http_methods(["GET"])
def api_resposta_reserva(request, reserva_id: int):
    return _stub(request, f"GET /api/nps/v1/respostas/{reserva_id}/")


@login_required
@require_http_methods(["GET"])
def api_resumo(request):
    return _stub(request, "GET /api/nps/v1/resumo/")

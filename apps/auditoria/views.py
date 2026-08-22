import csv

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.nucleo.models import TrilhaAuditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.periodos import periodo, selecao_periodo
from apps.nucleo.permissoes import requer_modulo

from . import services

Usuario = get_user_model()


@never_cache
@requer_modulo(Modulo.AUDITORIA)
def painel(request):
    achados = services.varrer()
    return render(request, "auditoria/painel.html", {
        "achados": achados,
        "resumo": services.resumo(achados),
    })


def _trilha_filtrada(request):
    """Filtra a trilha por ação, usuário e período (mês/ano ou intervalo)."""
    inicio, fim, rotulo = periodo(request)
    qs = TrilhaAuditoria.objects.select_related("usuario").filter(
        criado_em__date__range=(inicio, fim)
    )
    acao = request.GET.get("acao")
    usuario = request.GET.get("usuario")
    if acao:
        qs = qs.filter(acao=acao)
    if usuario:
        qs = qs.filter(usuario_id=usuario)
    return qs, rotulo


@requer_modulo(Modulo.AUDITORIA)
def trilha(request):
    qs, rotulo = _trilha_filtrada(request)
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="trilha_auditoria.csv"'
        from .formatacao import frase
        w = csv.writer(resp)
        w.writerow(["quando", "usuario", "descricao", "acao", "alvo", "alvo_id", "detalhe"])
        for t in qs[:5000]:
            w.writerow([
                t.criado_em.strftime("%d/%m/%Y %H:%M"),
                t.usuario or "—", frase(t), t.acao, t.alvo, t.alvo_id, t.detalhe,
            ])
        return resp
    return render(request, "auditoria/trilha.html", {
        "registros": qs[:300],
        "rotulo": rotulo,
        "acoes": TrilhaAuditoria.objects.order_by("acao").values_list("acao", flat=True).distinct(),
        "usuarios": Usuario.objects.filter(auditorias__isnull=False).distinct(),
        "f": request.GET,
        **selecao_periodo(request),
    })

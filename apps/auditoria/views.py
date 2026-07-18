import csv
from datetime import datetime

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.nucleo.models import TrilhaAuditoria
from apps.nucleo.modulos import Modulo
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


def _data(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _trilha_filtrada(request):
    qs = TrilhaAuditoria.objects.select_related("usuario")
    acao = request.GET.get("acao")
    usuario = request.GET.get("usuario")
    ini, fim = _data(request.GET.get("de")), _data(request.GET.get("ate"))
    if acao:
        qs = qs.filter(acao=acao)
    if usuario:
        qs = qs.filter(usuario_id=usuario)
    if ini:
        qs = qs.filter(criado_em__date__gte=ini)
    if fim:
        qs = qs.filter(criado_em__date__lte=fim)
    return qs


@requer_modulo(Modulo.AUDITORIA)
def trilha(request):
    qs = _trilha_filtrada(request)
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="trilha_auditoria.csv"'
        w = csv.writer(resp)
        w.writerow(["quando", "usuario", "acao", "alvo", "alvo_id", "detalhe"])
        for t in qs[:5000]:
            w.writerow([
                t.criado_em.strftime("%d/%m/%Y %H:%M"),
                t.usuario or "—", t.acao, t.alvo, t.alvo_id, t.detalhe,
            ])
        return resp
    return render(request, "auditoria/trilha.html", {
        "registros": qs[:300],
        "acoes": TrilhaAuditoria.objects.order_by("acao").values_list("acao", flat=True).distinct(),
        "usuarios": Usuario.objects.filter(auditorias__isnull=False).distinct(),
        "f": request.GET,
    })

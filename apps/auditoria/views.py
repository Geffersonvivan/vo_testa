import csv

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.nucleo.audit import redigir_sensiveis
from apps.nucleo.models import TrilhaAuditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.periodos import periodo, selecao_periodo
from apps.nucleo.permissoes import pode_ver_salario, requer_modulo

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
    # Salário é sensível: quem não tem a área Remuneração vê o valor redigido na
    # trilha (a mudança continua registrada — só o número é mascarado).
    ocultar_sensivel = not pode_ver_salario(request.user)
    if request.GET.get("export") == "csv":
        import json as _json

        from apps.nucleo.export import resposta_csv, sanitizar_celula
        resp = resposta_csv("trilha_auditoria.csv")
        from .formatacao import frase
        w = csv.writer(resp, delimiter=";")
        w.writerow(["quando", "usuario", "descricao", "acao", "alvo", "alvo_id", "detalhe"])
        for t in qs[:5000]:
            if ocultar_sensivel:
                t.detalhe = redigir_sensiveis(t.detalhe)
            w.writerow([sanitizar_celula(x) for x in (
                t.criado_em.strftime("%d/%m/%Y %H:%M"),
                t.usuario or "—", frase(t), t.acao, t.alvo, t.alvo_id,
                _json.dumps(t.detalhe, ensure_ascii=False),
            )])
        return resp
    registros = list(qs[:300])
    if ocultar_sensivel:
        for t in registros:
            t.detalhe = redigir_sensiveis(t.detalhe)
    return render(request, "auditoria/trilha.html", {
        "registros": registros,
        "rotulo": rotulo,
        "acoes": TrilhaAuditoria.objects.order_by("acao").values_list("acao", flat=True).distinct(),
        "usuarios": Usuario.objects.filter(auditorias__isnull=False).distinct(),
        "f": request.GET,
        **selecao_periodo(request),
    })

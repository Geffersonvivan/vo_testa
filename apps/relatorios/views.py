import csv

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views.decorators.cache import never_cache

from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo

from . import services


@never_cache
@requer_modulo(Modulo.RELATORIOS)
@requer_gerencia
def index(request):
    return render(request, "relatorios/index.html", {
        "grupos": services.disponiveis(),
    })


@never_cache
@requer_modulo(Modulo.RELATORIOS)
@requer_gerencia
def relatorio(request, chave):
    r = services.RELATORIOS.get(chave)
    if not r or (r["modulo"] and chave not in _chaves_disponiveis()):
        raise Http404("Relatório indisponível.")
    inicio, fim, rotulo = services.periodo(request)
    dados = r["builder"](inicio, fim)

    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        nome = slugify(r["nome"])
        resp["Content-Disposition"] = f'attachment; filename="{nome}_{inicio}_{fim}.csv"'
        resp.write("﻿")  # BOM p/ Excel pt-BR (padrão do BOH)

        def _celula(v):
            s = "" if v is None else str(v)
            return ("'" + s) if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

        w = csv.writer(resp, delimiter=";")
        for rotulo_kpi, valor in dados["kpis"]:
            w.writerow([_celula(rotulo_kpi), _celula(valor)])
        w.writerow([])
        w.writerow([_celula(c) for c in dados["colunas"]])
        for linha in dados["linhas"]:
            w.writerow([_celula(c) for c in linha])
        return resp

    return render(request, "relatorios/relatorio.html", {
        "chave": chave, "titulo": r["nome"], "grupo": r["grupo"],
        "inicio": inicio, "fim": fim, "rotulo": rotulo,
        "dados": dados, "f": request.GET,
        **services.selecao_periodo(request),
    })


def _chaves_disponiveis():
    return {r["chave"] for grupo in services.disponiveis().values() for r in grupo}

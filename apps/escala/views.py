import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.nucleo.models import Funcionario
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import Atribuicao, Ausencia, HoraExtra, TrocaTurno, Turno


def _data(txt, default=None):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _hora(txt):
    try:
        return datetime.strptime(txt, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _funcionarios(setor=None):
    qs = Funcionario.objects.select_related("pessoa").order_by("pessoa__nome")
    return qs


def _contexto_grade(inicio, setor):
    """Contexto compartilhado pela grade (página cheia e refresh do editor)."""
    from .models import SemanaPublicada

    grade = services.grade_semana(inicio, setor)
    analise = services.analisar_semana(inicio, setor)
    viol = analise["violacoes"]
    fim = inicio + timedelta(days=6)
    hx = HoraExtra.objects.filter(data__range=(inicio, fim)).select_related("funcionario")
    hx_por = {}
    for he in hx:
        hx_por.setdefault((he.funcionario_id, he.data), []).append(he)
    feriados = services.feriados_no_periodo(inicio, fim)
    for linha in grade["linhas"]:                       # selo de violação + horas extras + feriado por chip
        for cel in linha["celulas"]:
            cel["eh_feriado"] = cel["data"] in feriados
            for a in cel["atribs"]:
                a.violacoes = viol.get(a.pk, [])
                a.horas_extras = hx_por.get((a.funcionario_id, a.data), [])
                a.eh_feriado = a.data in feriados
                a.compensacao_efetiva = (
                    a.compensacao_feriado or a.funcionario.compensacao_feriado or "folga"
                )
    pub = SemanaPublicada.objects.filter(inicio=inicio, setor=setor or "").first()
    return {
        "grade": grade,
        "inicio": inicio,
        "setor": setor,
        "hoje": timezone.localdate(),
        "validacao": analise["alertas"],
        "bloqueios": analise["bloqueios"],
        "publicacao": pub,
    }


@requer_modulo(Modulo.ESCALA)
def escala(request):
    inicio = services.inicio_da_semana(_data(request.GET.get("inicio")))
    setor = request.GET.get("setor") or None
    ctx = _contexto_grade(inicio, setor)
    ctx.update({
        "anterior": inicio - timedelta(days=7),
        "proximo": inicio + timedelta(days=7),
        "setores": Turno.Setor.choices,
        "funcionarios": _funcionarios(setor),
        "turnos": Turno.objects.filter(ativo=True),
        "ausencias_json": json.dumps(services.ausencias_da_semana(inicio)),
    })
    return render(request, "escala/grade.html", ctx)


@requer_modulo(Modulo.ESCALA)
@require_POST
def escala_editar(request):
    """Add/mover/remover por arrasto. Devolve o partial da grade (validação +
    tabela) já atualizado; erro de regra volta como JSON 400 (vira toast)."""
    inicio = services.inicio_da_semana(_data(request.POST.get("inicio")))
    setor = request.POST.get("setor") or None
    acao = request.POST.get("acao")
    forcar = request.POST.get("forcar") == "1"
    data = _data(request.POST.get("data"))
    try:
        if acao in ("add", "mover"):
            turno = get_object_or_404(Turno, pk=request.POST.get("turno"))
            if acao == "add":
                func = get_object_or_404(Funcionario, pk=request.POST.get("funcionario"))
                atrib = None
            else:
                atrib = get_object_or_404(Atribuicao, pk=request.POST.get("atribuicao"))
                func = atrib.funcionario
            # Interjornada <11h é risco legal: barra o drop e pede confirmação.
            if not forcar and services.conflito_interjornada(
                func, turno, data, ignora_pk=atrib.pk if atrib else None
            ):
                return JsonResponse(
                    {"confirmar": f"{func.pessoa.nome} ficaria com menos de 11h de descanso "
                                  "(interjornada). Escalar mesmo assim?"}, status=409,
                )
            if acao == "add":
                services.atribuir(turno, func, data, request.user)
            else:
                services.mover(atrib, turno, data, request.user)
            if forcar:
                from apps.nucleo.models.financeiro import registrar_auditoria
                registrar_auditoria(request.user, "escala_forcar_interjornada",
                                    func, {"turno": str(turno), "data": str(data)})
        elif acao == "remover":
            atrib = get_object_or_404(Atribuicao, pk=request.POST.get("atribuicao"))
            services.desatribuir(atrib)
        elif acao == "he_add":
            func = get_object_or_404(Funcionario, pk=request.POST.get("funcionario"))
            services.adicionar_hora_extra(
                func, data, _hora(request.POST.get("he_inicio")), _hora(request.POST.get("he_fim")),
                request.POST.get("tipo"), request.user,
            )
        elif acao == "he_remover":
            he = get_object_or_404(HoraExtra, pk=request.POST.get("hora_extra"))
            services.remover_hora_extra(he)
        elif acao == "feriado_comp":
            atrib = get_object_or_404(Atribuicao, pk=request.POST.get("atribuicao"))
            services.definir_compensacao_feriado(atrib, request.POST.get("valor"))
    except ValidationError as erro:
        return JsonResponse({"erro": " ".join(erro.messages)}, status=400)
    return render(request, "escala/partials/grade_conteudo.html", _contexto_grade(inicio, setor))


@requer_modulo(Modulo.ESCALA)
@requer_gerencia
def relatorio_colaborador(request):
    """Relatório mensal do colaborador (filtros: colaborador + mês/ano)."""
    import csv

    from django.http import HttpResponse

    from apps.nucleo import periodos

    inicio, fim, rotulo = periodos.periodo(request)
    funcs = Funcionario.objects.select_related("pessoa").order_by("pessoa__nome")
    fid = request.GET.get("funcionario")
    func = (funcs.filter(pk=fid).first() if fid else funcs.first())
    dados = services.relatorio_colaborador(func, inicio, fim) if func else None

    if request.GET.get("export") == "csv" and dados:
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp.write("﻿")
        resp["Content-Disposition"] = f'attachment; filename="relatorio_{func.pessoa.nome}_{inicio}.csv"'
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Colaborador", func.pessoa.nome])
        w.writerow(["Período", rotulo])
        w.writerow(["Dias trabalhados", dados["dias_trabalhados"]])
        w.writerow(["Horas normais", dados["horas_normais_txt"]])
        w.writerow(["Hora extra (banco)", dados["banco_txt"]])
        w.writerow(["Hora extra (extra)", dados["extra_txt"]])
        w.writerow(["Dias ausente", dados["dias_ausente"]])
        w.writerow([])
        w.writerow(["Feriado", "Turno", "Compensação"])
        for fe in dados["feriados_trabalhados"]:
            w.writerow([fe["data"].strftime("%d/%m/%Y"), fe["turno"], fe["compensacao"]])
        return resp

    return render(request, "escala/relatorio_colaborador.html", {
        "funcionarios": funcs, "func": func, "dados": dados,
        "inicio": inicio, "fim": fim, "rotulo": rotulo,
        **periodos.selecao_periodo(request),
    })


@requer_gerencia
@require_POST
def publicar(request):
    inicio = services.inicio_da_semana(_data(request.POST.get("inicio")))
    setor = request.POST.get("setor") or None
    try:
        services.publicar_semana(inicio, setor, request.user,
                                 request.POST.get("justificativa", ""))
        messages.success(request, "Escala da semana publicada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    destino = f"{reverse('escala:grade')}?inicio={inicio:%Y-%m-%d}"
    if setor:
        destino += f"&setor={setor}"
    return redirect(destino)


@requer_gerencia
def gerar_semana(request):
    """Gera a escala da semana automaticamente (gestão) e mostra o resultado."""
    inicio = services.inicio_da_semana(_data(request.POST.get("semana")))
    setor = request.POST.get("setor") or None
    if request.method == "POST":
        n = services.gerar_semana(inicio, request.user, setor)
        messages.success(request, f"Escala gerada: {n} atribuições. Ajuste o que precisar.")
    destino = f"{reverse('escala:grade')}?inicio={inicio:%Y-%m-%d}"
    if setor:
        destino += f"&setor={setor}"
    return redirect(destino)


@requer_modulo(Modulo.ESCALA)
def atribuir(request):
    if request.method == "POST":
        turno = get_object_or_404(Turno, pk=request.POST.get("turno"))
        func = get_object_or_404(Funcionario, pk=request.POST.get("funcionario"))
        data = _data(request.POST.get("data"))
        try:
            services.atribuir(turno, func, data, request.user)
            messages.success(request, f"{func.pessoa.nome} escalado(a).")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    semana = request.POST.get("semana")
    return redirect(f"{reverse('escala:grade')}?inicio={semana}" if semana else "escala:grade")


@requer_modulo(Modulo.ESCALA)
def remover_atribuicao(request, pk):
    atrib = get_object_or_404(Atribuicao, pk=pk)
    if request.method == "POST":
        services.desatribuir(atrib)
        messages.success(request, "Atribuição removida.")
    # "voltar" vem como query string (?inicio=…); redirect() reverte nome de rota,
    # então prefixa a URL base da grade para não dar NoReverseMatch.
    voltar = request.POST.get("voltar", "")
    destino = reverse("escala:grade") + voltar if voltar.startswith("?") else reverse("escala:grade")
    return redirect(destino)


@requer_modulo(Modulo.ESCALA)
def minha_escala(request):
    hoje = timezone.localdate()
    fim = hoje + timedelta(days=30)
    atribs = services.minha_escala(request.user, hoje, fim)
    return render(request, "escala/minha.html", {
        "atribs": atribs,
        "tem_funcionario": getattr(request.user, "funcionario", None) is not None,
    })


@requer_modulo(Modulo.ESCALA)
def turnos(request):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        inicio = request.POST.get("inicio")
        fim = request.POST.get("fim")
        if nome and inicio and fim:
            Turno.objects.create(
                nome=nome, setor=request.POST.get("setor") or "geral",
                inicio=inicio, fim=fim,
            )
            messages.success(request, "Turno cadastrado.")
        else:
            messages.error(request, "Preencha nome, início e fim.")
        return redirect("escala:turnos")
    return render(request, "escala/turnos.html", {
        "turnos": Turno.objects.all(),
        "setores": Turno.Setor.choices,
    })


@requer_modulo(Modulo.ESCALA)
def ausencias(request):
    if request.method == "POST":
        func = get_object_or_404(Funcionario, pk=request.POST.get("funcionario"))
        try:
            services.registrar_ausencia(
                func, request.POST.get("tipo") or "folga",
                _data(request.POST.get("inicio")), _data(request.POST.get("fim")),
                request.user, request.POST.get("observacao", ""),
            )
            messages.success(request, "Ausência registrada.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        return redirect("escala:ausencias")
    return render(request, "escala/ausencias.html", {
        "ausencias": Ausencia.objects.select_related("funcionario__pessoa")[:100],
        "funcionarios": _funcionarios(),
        "tipos": Ausencia.Tipo.choices,
    })


@requer_modulo(Modulo.ESCALA)
def trocas(request):
    if request.method == "POST":
        atrib = get_object_or_404(Atribuicao, pk=request.POST.get("atribuicao"))
        substituto = get_object_or_404(Funcionario, pk=request.POST.get("substituto"))
        try:
            services.solicitar_troca(atrib, substituto, request.POST.get("motivo", ""))
            messages.success(request, "Troca solicitada — aguardando aprovação.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        return redirect("escala:trocas")
    hoje = timezone.localdate()
    return render(request, "escala/trocas.html", {
        "pendentes": TrocaTurno.objects.filter(status="pendente").select_related(
            "atribuicao__turno", "solicitante__pessoa", "substituto__pessoa"),
        "recentes": TrocaTurno.objects.exclude(status="pendente").select_related(
            "solicitante__pessoa", "substituto__pessoa")[:20],
        "atribuicoes": Atribuicao.objects.filter(data__gte=hoje).select_related(
            "turno", "funcionario__pessoa").order_by("data")[:60],
        "funcionarios": _funcionarios(),
        "eh_gerente": eh_gerente(request.user),
    })


@requer_gerencia
def decidir_troca(request, pk):
    troca = get_object_or_404(TrocaTurno, pk=pk)
    if request.method == "POST":
        try:
            services.decidir_troca(troca, request.user, request.POST.get("acao") == "aprovar")
            messages.success(request, "Troca decidida.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("escala:trocas")

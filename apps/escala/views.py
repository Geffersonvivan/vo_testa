from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import Funcionario
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import Atribuicao, Ausencia, TrocaTurno, Turno


def _data(txt, default=None):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _funcionarios():
    return Funcionario.objects.select_related("pessoa").order_by("pessoa__nome")


@requer_modulo(Modulo.ESCALA)
def escala(request):
    inicio = services.inicio_da_semana(_data(request.GET.get("inicio")))
    setor = request.GET.get("setor") or None
    grade = services.grade_semana(inicio, setor)
    return render(request, "escala/grade.html", {
        "grade": grade,
        "inicio": inicio,
        "anterior": inicio - timedelta(days=7),
        "proximo": inicio + timedelta(days=7),
        "setor": setor,
        "setores": Turno.Setor.choices,
        "funcionarios": _funcionarios(),
        "turnos": Turno.objects.filter(ativo=True),
        "hoje": timezone.localdate(),
    })


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
    destino = request.POST.get("voltar") or "escala:grade"
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

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.nucleo.models import UH, Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .models import OrdemServico

Usuario = get_user_model()


def _valor(txt):
    try:
        return Decimal(str(txt).replace(",", ".")) if txt not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _data(txt):
    if not txt:
        return None
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


def _prestadores_data():
    externos = Pessoa.objects.filter(ativo=True).filter(
        Q(fornecedor__isnull=False) | Q(agencia__isnull=False)
    )
    return pessoas_agrupadas(externos)


@requer_modulo(Modulo.MANUTENCAO)
def painel(request):
    abertas = (
        OrdemServico.objects.filter(
            status__in=[OrdemServico.Status.ABERTA, OrdemServico.Status.EM_ANDAMENTO]
        )
        .select_related("uh", "responsavel")
    )
    return render(request, "manutencao/painel.html", {
        "abertas": abertas,
        "bloqueados": UH.objects.filter(status=UH.Status.BLOQUEADA).count(),
        "quartos": UH.objects.exclude(status=UH.Status.INATIVA).select_related("tipo"),
        "responsaveis": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        "prestadores_data": _prestadores_data(),
        "prioridades": OrdemServico.Prioridade.choices,
        "tipos": OrdemServico.Tipo.choices,
    })


@requer_modulo(Modulo.MANUTENCAO)
def nova(request):
    if request.method != "POST":
        return redirect("manutencao:painel")
    uh = UH.objects.filter(pk=request.POST.get("uh") or None).first()
    responsavel = Usuario.objects.filter(pk=request.POST.get("responsavel") or None).first()
    prestador = Pessoa.objects.filter(pk=request.POST.get("prestador") or None).first()
    try:
        ordem = services.abrir_os(
            request.user,
            uh=uh,
            area=request.POST.get("area", ""),
            titulo=request.POST.get("titulo", ""),
            descricao=request.POST.get("descricao", ""),
            tipo=request.POST.get("tipo") or OrdemServico.Tipo.CORRETIVA,
            prioridade=request.POST.get("prioridade") or OrdemServico.Prioridade.MEDIA,
            responsavel=responsavel,
            prestador=prestador,
            previsto_para=_data(request.POST.get("previsto_para")),
            bloquear=request.POST.get("bloquear") == "1",
            recorrencia_meses=(int(request.POST["recorrencia_meses"])
                               if request.POST.get("recorrencia_meses") else None),
            agendada_para=_data(request.POST.get("agendada_para")),
        )
    except (ValidationError, ValueError) as erro:
        msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Dados inválidos."
        messages.error(request, msg)
        return redirect("manutencao:painel")
    messages.success(request, f"OS #{ordem.pk} aberta.")
    return redirect("manutencao:detalhe", pk=ordem.pk)


@requer_modulo(Modulo.MANUTENCAO)
def detalhe(request, pk):
    ordem = get_object_or_404(
        OrdemServico.objects.select_related("uh", "responsavel", "criado_por"), pk=pk
    )
    return render(request, "manutencao/os_detalhe.html", {
        "os": ordem, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.MANUTENCAO)
def iniciar(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        try:
            services.iniciar_os(ordem, request.user)
            messages.success(request, "OS em andamento.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)


@requer_modulo(Modulo.MANUTENCAO)
def concluir(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        try:
            proxima = services.concluir_os(
                ordem, request.user,
                resolucao=request.POST.get("resolucao", ""),
                custo_maodeobra=_valor(request.POST.get("custo_maodeobra")),
                custo_pecas=_valor(request.POST.get("custo_pecas")),
                nota_fiscal=request.POST.get("nota_fiscal", ""),
                garantia_ate=_data(request.POST.get("garantia_ate")),
            )
            if proxima:
                messages.success(
                    request,
                    f"OS concluída. Próxima preventiva agendada para {proxima.agendada_para:%d/%m/%Y}.",
                )
            else:
                messages.success(request, "OS concluída.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)


@requer_gerencia
def cancelar(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_os(ordem, request.user, request.POST.get("motivo", ""))
            messages.success(request, "OS cancelada.")
            return redirect("manutencao:painel")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)

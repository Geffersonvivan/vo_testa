from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from apps.nucleo.models import UH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo

from . import services
from .models import StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


@requer_modulo(Modulo.GOVERNANCA)
def painel(request):
    # Situação de cada quarto (garante um StatusLimpeza para todos).
    quartos = []
    for uh in UH.objects.select_related("tipo").exclude(status=UH.Status.INATIVA):
        quartos.append({"uh": uh, "status": services.situacao_uh(uh)})
    return render(request, "governanca/painel.html", {
        "quartos": quartos,
        "tarefas": services.tarefas_ativas(),
        "camareiras": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        "tipos": TarefaGovernanca.Tipo.choices,
    })


@requer_modulo(Modulo.GOVERNANCA)
def nova_tarefa(request):
    if request.method == "POST":
        uh = get_object_or_404(UH, pk=request.POST.get("uh"))
        tipo = request.POST.get("tipo") or TarefaGovernanca.Tipo.FAXINA
        services.abrir_faxina(uh, tipo=tipo, usuario=request.user, origem="manual")
        messages.success(request, f"Faxina aberta para o {uh.numero}.")
    return redirect("governanca:painel")


@requer_modulo(Modulo.GOVERNANCA)
def tarefa_acao(request, pk):
    if request.method != "POST":
        return redirect("governanca:painel")
    tarefa = get_object_or_404(TarefaGovernanca, pk=pk)
    acao = request.POST.get("acao")
    if acao == "atribuir":
        tarefa.camareira = Usuario.objects.filter(
            pk=request.POST.get("camareira")
        ).first()
        tarefa.save()
        messages.success(request, "Camareira atribuída.")
    elif acao == "iniciar":
        services.iniciar_tarefa(tarefa, request.user)
        messages.success(request, f"Faxina do {tarefa.uh.numero} iniciada.")
    elif acao == "concluir":
        services.concluir_tarefa(tarefa, request.user)
        messages.success(request, f"{tarefa.uh.numero} limpo. Boa!")
    return redirect("governanca:painel")


@requer_modulo(Modulo.GOVERNANCA)
def status_marcar(request, pk):
    if request.method != "POST":
        return redirect("governanca:painel")
    uh = get_object_or_404(UH, pk=pk)
    situacao = request.POST.get("situacao")
    if situacao in StatusLimpeza.Situacao.values:
        services.definir_status(uh, situacao, request.user)
        messages.success(request, f"{uh.numero}: {dict(StatusLimpeza.Situacao.choices)[situacao].lower()}.")
    return redirect("governanca:painel")

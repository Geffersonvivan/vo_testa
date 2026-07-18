
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from apps.nucleo.models import LocalEstoque, Produto, TipoUH, saldo
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import Conferencia, ItemComposicao


def _local():
    return (
        LocalEstoque.objects.filter(modulo=Modulo.FRIGOBAR, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


def _contas_abertas(request):
    if not request.user.pode_acessar(Modulo.RESERVAS):
        return []
    from apps.reservas.services import contas_abertas
    return list(contas_abertas())


@never_cache
@requer_modulo(Modulo.FRIGOBAR)
def painel(request):
    contas = [
        {"id": c.pk, "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}"}
        for c in _contas_abertas(request)
    ]
    recentes = (
        Conferencia.objects.select_related("uh", "criado_por").prefetch_related("itens")[:30]
    )
    return render(request, "frigobar/painel.html", {
        "contas": contas,
        "recentes": recentes,
        "reposicao": services.lista_reposicao(),
        "momentos": Conferencia.Momento.choices,
        "sem_reservas": not request.user.pode_acessar(Modulo.RESERVAS),
    })


@requer_modulo(Modulo.FRIGOBAR)
def conferir(request):
    """Formulário de conferência de uma conta aberta (mostra o kit do TipoUH)."""
    conta_id = request.GET.get("conta") or request.POST.get("conta")
    from apps.reservas.services import conta_aberta
    conta = conta_aberta(conta_id)
    if not conta:
        messages.error(request, "Selecione uma conta do quarto aberta.")
        return redirect("frigobar:painel")

    tipo = conta.reserva.uh.tipo
    composicao = services.composicao_do_tipo(tipo)

    if request.method == "POST":
        consumos = []
        for item in composicao:
            qtd = request.POST.get(f"consumo_{item.produto_id}") or 0
            consumos.append((item.produto, qtd))
        try:
            conf = services.registrar_conferencia(
                request.user, conta, request.POST.get("momento") or "arrumacao", consumos
            )
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return redirect("frigobar:painel")
        messages.success(request, f"Conferência #{conf.pk} registrada (R$ {conf.total()}).")
        return redirect("frigobar:conferencia", pk=conf.pk)

    linhas = [{"item": i, "saldo_central": saldo(i.produto, _local())} for i in composicao]
    return render(request, "frigobar/conferir.html", {
        "conta": conta,
        "rotulo": f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}",
        "tipo": tipo,
        "linhas": linhas,
        "momentos": Conferencia.Momento.choices,
    })


@requer_modulo(Modulo.FRIGOBAR)
def conferencia(request, pk):
    conf = get_object_or_404(
        Conferencia.objects.select_related("uh", "criado_por").prefetch_related("itens"), pk=pk
    )
    return render(request, "frigobar/conferencia.html", {
        "conf": conf, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.FRIGOBAR)
def repor(request, pk):
    conf = get_object_or_404(Conferencia, pk=pk)
    if request.method == "POST":
        local = _local()
        if not local:
            messages.error(request, "Cadastre um depósito de frigobar em Estoque → Locais.")
            return redirect("frigobar:conferencia", pk=pk)
        try:
            services.repor(conf, request.user, local)
            messages.success(request, "Reposição feita — estoque central baixado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("frigobar:conferencia", pk=pk)


@requer_modulo(Modulo.FRIGOBAR)
def composicoes(request):
    if request.method == "POST":
        tipo = TipoUH.objects.filter(pk=request.POST.get("tipo_uh") or None).first()
        produto = Produto.objects.filter(pk=request.POST.get("produto") or None).first()
        qtd = int(request.POST.get("quantidade") or 0)
        if tipo and produto and qtd > 0:
            ItemComposicao.objects.update_or_create(
                tipo_uh=tipo, produto=produto, defaults={"quantidade": qtd}
            )
            messages.success(request, "Composição atualizada.")
        else:
            messages.error(request, "Preencha tipo, produto e quantidade.")
        return redirect("frigobar:composicoes")

    tipos = []
    for t in TipoUH.objects.all():
        tipos.append({"tipo": t, "itens": services.composicao_do_tipo(t)})
    return render(request, "frigobar/composicoes.html", {
        "tipos": tipos,
        "todos_tipos": TipoUH.objects.all(),
        "produtos": Produto.objects.filter(ativo=True, preco_venda__gt=0),
    })


@requer_gerencia
def remover_composicao(request, pk):
    item = get_object_or_404(ItemComposicao, pk=pk)
    if request.method == "POST":
        item.delete()
        messages.success(request, "Item removido da composição.")
    return redirect("frigobar:composicoes")

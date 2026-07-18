from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from apps.nucleo.models import (
    FormaPagamento,
    LocalEstoque,
    Pessoa,
    Produto,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .models import Comanda, ItemComanda, Mesa


def _local(request):
    return (
        LocalEstoque.objects.filter(modulo=Modulo.RESTAURANTE, ativo=True).first()
        or LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


@never_cache
@requer_modulo(Modulo.RESTAURANTE)
def comandas(request):
    abertas = (
        Comanda.objects.filter(status=Comanda.Status.ABERTA)
        .select_related("mesa", "cliente")
    )
    return render(request, "restaurante/comandas.html", {
        "abertas": abertas,
        "mesas": Mesa.objects.filter(ativa=True),
        "clientes": pessoas_agrupadas(),
        "tem_local": _local(request) is not None,
    })


@requer_modulo(Modulo.RESTAURANTE)
def abrir(request):
    if request.method != "POST":
        return redirect("restaurante:comandas")
    local = _local(request)
    if not local:
        messages.error(request, "Cadastre um depósito do Restaurante em Estoque → Locais.")
        return redirect("restaurante:comandas")
    mesa = Mesa.objects.filter(pk=request.POST.get("mesa") or None).first()
    cliente = Pessoa.objects.filter(pk=request.POST.get("cliente") or None).first()
    try:
        comanda = services.abrir_comanda(
            request.user, local, mesa=mesa, cliente=cliente,
            rotulo=request.POST.get("rotulo", "").strip(),
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("restaurante:comandas")
    return redirect("restaurante:comanda", pk=comanda.pk)


def _contexto_comanda(request, comanda):
    local = comanda.local
    cardapio = [
        {"id": p.pk, "nome": p.nome, "preco": p.preco_venda, "saldo": saldo(p, local)}
        for p in Produto.objects.filter(ativo=True, preco_venda__gt=0)
    ]
    contas = []
    if request.user.pode_acessar(Modulo.RESERVAS):
        from apps.reservas.services import contas_abertas

        contas = [
            {"id": c.pk, "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}"}
            for c in contas_abertas()
        ]
    return {
        "comanda": comanda,
        "cardapio": cardapio,
        "formas": FormaPagamento.objects.filter(ativo=True),
        "contas": contas,
        "mesas": Mesa.objects.filter(ativa=True),
        "eh_gerente": eh_gerente(request.user),
    }


@requer_modulo(Modulo.RESTAURANTE)
def comanda(request, pk):
    c = get_object_or_404(
        Comanda.objects.select_related("mesa", "cliente", "local"), pk=pk
    )
    return render(request, "restaurante/comanda.html", _contexto_comanda(request, c))


@requer_modulo(Modulo.RESTAURANTE)
def historico(request):
    """Comandas já fechadas e canceladas (as abertas ficam na tela principal)."""
    filtro = request.GET.get("status", "")
    qs = (
        Comanda.objects.exclude(status=Comanda.Status.ABERTA)
        .select_related("mesa", "cliente", "forma_pagamento", "criado_por")
        .prefetch_related("itens")
    )
    base = Comanda.objects.exclude(status=Comanda.Status.ABERTA)
    filtros = [
        {"chave": "", "rotulo": "Todas", "total": base.count()},
        {"chave": "fechada", "rotulo": "Fechadas",
         "total": base.filter(status=Comanda.Status.FECHADA).count()},
        {"chave": "cancelada", "rotulo": "Canceladas",
         "total": base.filter(status=Comanda.Status.CANCELADA).count()},
    ]
    if filtro in (Comanda.Status.FECHADA, Comanda.Status.CANCELADA):
        qs = qs.filter(status=filtro)
    return render(request, "restaurante/historico.html", {
        "comandas": qs[:200],
        "filtro": filtro,
        "filtros": filtros,
    })


@requer_modulo(Modulo.RESTAURANTE)
def add_item(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        produto = Produto.objects.filter(pk=request.POST.get("produto_id") or None).first()
        try:
            services.adicionar_item(
                c, produto, request.POST.get("quantidade", 1), request.user
            )
        except (ValidationError, AttributeError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Produto inválido."
            return render(request, "restaurante/partials/itens.html",
                          {"comanda": c, "erro": msg})
    return render(request, "restaurante/partials/itens.html", {"comanda": c})


@requer_modulo(Modulo.RESTAURANTE)
def remover_item(request, pk, item_pk):
    c = get_object_or_404(Comanda, pk=pk)
    item = get_object_or_404(ItemComanda, pk=item_pk, comanda=c)
    if request.method == "POST":
        try:
            services.remover_item(item, request.user)
        except ValidationError:
            pass
    return render(request, "restaurante/partials/itens.html", {"comanda": c})


@requer_modulo(Modulo.RESTAURANTE)
def fechar(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method != "POST":
        return redirect("restaurante:comanda", pk=pk)
    forma = FormaPagamento.objects.filter(pk=request.POST.get("forma") or None).first()
    try:
        services.fechar_comanda(
            c, request.user, request.POST.get("destino"),
            forma=forma, conta_id=request.POST.get("conta_id") or None,
            desconto=Decimal(request.POST.get("desconto") or 0),
        )
        messages.success(request, f"Comanda #{c.pk} fechada.")
        return redirect("restaurante:comandas")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("restaurante:comanda", pk=pk)


@requer_modulo(Modulo.RESTAURANTE)
def transferir(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        mesa = Mesa.objects.filter(pk=request.POST.get("mesa") or None).first()
        try:
            services.transferir_mesa(c, mesa)
            messages.success(request, "Comanda transferida de ponto.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:comanda", pk=pk)


@requer_gerencia
def cancelar(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_comanda(c, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Comanda cancelada — estoque devolvido.")
            return redirect("restaurante:comandas")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:comanda", pk=pk)


@requer_modulo(Modulo.RESTAURANTE)
def mesas(request):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        if nome:
            Mesa.objects.get_or_create(nome=nome)
            messages.success(request, "Ponto cadastrado.")
        return redirect("restaurante:mesas")
    return render(request, "restaurante/mesas.html", {"mesas": Mesa.objects.all()})

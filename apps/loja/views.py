import json
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.nucleo.models import (
    FormaPagamento,
    LocalEstoque,
    Pessoa,
    Produto,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import Venda


def _local_da_loja(request):
    local_id = request.GET.get("local")
    if local_id:
        return get_object_or_404(LocalEstoque, pk=local_id, ativo=True)
    return (
        LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


@requer_modulo(Modulo.LOJA)
def pdv(request):
    local = _local_da_loja(request)
    produtos = []
    if local:
        vendaveis = Produto.objects.filter(
            ativo=True, preco_venda__gt=0
        ).select_related("categoria")
        for p in vendaveis:
            produtos.append({
                "id": p.pk, "nome": p.nome,
                "categoria": p.categoria.nome,
                "preco": float(p.preco_venda),
                "saldo": float(saldo(p, local)),
                "unidade": p.get_unidade_display(),
            })

    contas = []
    if request.user.pode_acessar(Modulo.RESERVAS):
        from apps.reservas.services import contas_abertas

        for c in contas_abertas():
            contas.append({
                "id": c.pk,
                "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}",
            })

    return render(request, "loja/pdv.html", {
        "local": local,
        "locais": LocalEstoque.objects.filter(ativo=True),
        "produtos_json": json.dumps(produtos),
        "formas": FormaPagamento.objects.filter(ativo=True),
        "clientes": Pessoa.objects.filter(ativo=True),
        "contas": contas,
        "url_finalizar": reverse("loja:finalizar"),
    })


@requer_modulo(Modulo.LOJA)
def finalizar(request):
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido."}, status=405)
    try:
        dados = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"erro": "Dados inválidos."}, status=400)

    local = get_object_or_404(LocalEstoque, pk=dados.get("local_id"))
    forma = None
    if dados.get("forma_id"):
        forma = FormaPagamento.objects.filter(pk=dados["forma_id"]).first()
    cliente = None
    if dados.get("cliente_id"):
        cliente = Pessoa.objects.filter(pk=dados["cliente_id"]).first()
    try:
        venda = services.finalizar_venda(
            operador=request.user, local=local, itens=dados.get("itens", []),
            destino=dados.get("destino"), forma=forma, cliente=cliente,
            conta_id=dados.get("conta_id"),
            desconto=Decimal(str(dados.get("desconto") or 0)),
        )
    except ValidationError as erro:
        return JsonResponse({"erro": " ".join(erro.messages)}, status=400)
    return JsonResponse({
        "ok": True, "url": reverse("loja:venda", args=[venda.pk]),
    })


@requer_modulo(Modulo.LOJA)
def vendas(request):
    lista = Venda.objects.select_related("cliente", "criado_por")[:200]
    return render(request, "loja/vendas.html", {"vendas": lista})


@requer_modulo(Modulo.LOJA)
def venda(request, pk):
    v = get_object_or_404(
        Venda.objects.select_related("cliente", "forma_pagamento", "criado_por"), pk=pk
    )
    return render(request, "loja/venda.html", {
        "venda": v, "itens": v.itens.all(), "eh_gerente": eh_gerente(request.user),
    })


@requer_gerencia
def cancelar(request, pk):
    v = get_object_or_404(Venda, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_venda(v, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Venda cancelada — estoque e caixa revertidos.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("loja:venda", pk=pk)

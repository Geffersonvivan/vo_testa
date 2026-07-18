"""Serviços do Restaurante: comanda aberta, itens (baixa estoque) e fechamento."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import (
    ajustar,
    receber_no_caixa,
    registrar_auditoria,
    registrar_saida,
    saldo,
)

from .models import Comanda, ItemComanda

ZERO = Decimal("0.00")


def abrir_comanda(operador, local, mesa=None, cliente=None, rotulo=""):
    if not (mesa or cliente or rotulo):
        raise ValidationError("Informe o ponto, o hóspede ou uma identificação.")
    return Comanda.objects.create(
        local=local, mesa=mesa, cliente=cliente, rotulo=rotulo, criado_por=operador
    )


@transaction.atomic
def adicionar_item(comanda, produto, quantidade, operador):
    """Lança um item na comanda e baixa o estoque na hora (o produto saiu)."""
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    quantidade = Decimal(str(quantidade))
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    if saldo(produto, comanda.local) < quantidade:
        raise ValidationError(
            f"Saldo insuficiente de {produto.nome} em {comanda.local.nome}."
        )
    registrar_saida(
        produto, comanda.local, quantidade, operador,
        documento=f"Comanda #{comanda.pk}",
    )
    item = comanda.itens.filter(produto=produto).first()
    if item:
        item.quantidade += quantidade
        item.save(update_fields=["quantidade"])
        return item
    return ItemComanda.objects.create(
        comanda=comanda, produto=produto, descricao=produto.nome,
        natureza=produto.natureza, quantidade=quantidade,
        preco_unitario=produto.preco_venda,
    )


@transaction.atomic
def remover_item(item, operador):
    """Remove um item da comanda e devolve o estoque (ajuste)."""
    if not item.comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    atual = saldo(item.produto, item.comanda.local)
    ajustar(item.produto, item.comanda.local, atual + item.quantidade, operador,
            motivo=f"Remoção de item — comanda #{item.comanda.pk}")
    item.delete()


@transaction.atomic
def fechar_comanda(comanda, operador, destino, forma=None, conta_id=None, desconto=ZERO):
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    if not comanda.itens.exists():
        raise ValidationError("A comanda está vazia.")
    desconto = Decimal(desconto or 0)
    if desconto < 0 or desconto > comanda.subtotal():
        raise ValidationError("Desconto inválido.")
    comanda.desconto = desconto
    total = comanda.total()

    if destino == Comanda.Destino.CAIXA:
        if not forma:
            raise ValidationError("Escolha a forma de pagamento.")
        mov = receber_no_caixa(operador, forma, total, f"Comanda #{comanda.pk}")
        comanda.forma_pagamento = forma
        comanda.movimento_caixa = mov
    else:
        from apps.reservas import services as reservas

        conta = reservas.conta_aberta(conta_id)
        if not conta:
            raise ValidationError("Selecione uma conta do quarto aberta.")
        for item in comanda.itens.all():
            reservas.lancar_na_conta(
                conta, "consumo", item.natureza,
                f"Restaurante: {item.descricao}", item.subtotal, operador,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", "consumo", "Restaurante: desconto", desconto, operador
            )
        comanda.conta_ref = f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}"

    comanda.destino = destino
    comanda.status = Comanda.Status.FECHADA
    comanda.fechada_em = timezone.now()
    comanda.save()
    return comanda


@transaction.atomic
def cancelar_comanda(comanda, usuario, motivo):
    """Cancela a comanda aberta e devolve todo o estoque consumido."""
    if not comanda.aberta:
        raise ValidationError("Só comandas abertas podem ser canceladas.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo do cancelamento.")
    for item in comanda.itens.select_related("produto"):
        atual = saldo(item.produto, comanda.local)
        ajustar(item.produto, comanda.local, atual + item.quantidade, usuario,
                motivo=f"Cancelamento comanda #{comanda.pk}")
    comanda.status = Comanda.Status.CANCELADA
    comanda.fechada_em = timezone.now()
    comanda.motivo_cancelamento = motivo
    comanda.save()
    registrar_auditoria(usuario, "cancelamento_comanda", comanda, {"motivo": motivo})
    return comanda


def transferir_mesa(comanda, nova_mesa):
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    comanda.mesa = nova_mesa
    comanda.save(update_fields=["mesa"])
    return comanda


def pendencias_auditoria():
    """Comandas abertas há muito tempo, para a Auditoria (read-only)."""
    from datetime import timedelta

    from django.urls import reverse
    achados = []
    limite = timezone.now() - timedelta(hours=12)
    for c in Comanda.objects.filter(status=Comanda.Status.ABERTA, aberta_em__lt=limite):
        achados.append({
            "area": "Restaurante", "tipo": "comanda_antiga", "gravidade": "media",
            "descricao": f"Comanda #{c.pk} ({c.titulo}) aberta desde {c.aberta_em:%d/%m %H:%M}.",
            "url": reverse("restaurante:comanda", args=[c.pk]),
        })
    return achados

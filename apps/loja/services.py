"""Serviços da Loja: fechar venda (dois destinos) e cancelar."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import (
    Produto,
    ajustar,
    estornar_movimento,
    receber_no_caixa,
    registrar_auditoria,
    registrar_saida,
    saldo,
)

from .models import ItemVenda, Venda

ZERO = Decimal("0.00")


@transaction.atomic
def finalizar_venda(operador, local, itens, destino, forma=None, cliente=None,
                    conta_id=None, desconto=ZERO):
    """
    itens: lista de dicts {produto_id, quantidade}. Valida saldo, baixa estoque
    e cobra pelo destino escolhido (caixa OU conta do quarto).
    """
    desconto = Decimal(desconto or 0)
    if not itens:
        raise ValidationError("Adicione ao menos um item à venda.")

    # Monta as linhas com preço e valida saldo no local.
    linhas = []
    subtotal = ZERO
    for item in itens:
        produto = Produto.objects.filter(pk=item.get("produto_id"), ativo=True).first()
        if not produto:
            raise ValidationError("Produto inválido na venda.")
        qtd = Decimal(str(item.get("quantidade") or 0))
        if qtd <= 0:
            raise ValidationError(f"Quantidade inválida para {produto.nome}.")
        if saldo(produto, local) < qtd:
            raise ValidationError(
                f"Saldo insuficiente de {produto.nome} em {local.nome} "
                f"(disponível: {saldo(produto, local)})."
            )
        valor = (produto.preco_venda * qtd).quantize(Decimal("0.01"))
        subtotal += valor
        linhas.append((produto, qtd, valor))

    if desconto < 0 or desconto > subtotal:
        raise ValidationError("Desconto inválido.")
    total = subtotal - desconto

    if destino == Venda.Destino.CAIXA and not forma:
        raise ValidationError("Escolha a forma de pagamento.")

    venda = Venda.objects.create(
        local=local, destino=destino, cliente=cliente, forma_pagamento=forma,
        desconto=desconto, total=total, criado_por=operador,
    )
    for produto, qtd, valor in linhas:
        ItemVenda.objects.create(
            venda=venda, produto=produto, descricao=produto.nome,
            natureza=produto.natureza, quantidade=qtd,
            preco_unitario=produto.preco_venda, subtotal=valor,
        )
        registrar_saida(
            produto, local, qtd, operador,
            documento=f"Venda Loja #{venda.pk}",
        )

    if destino == Venda.Destino.CAIXA:
        mov = receber_no_caixa(
            operador, forma, total, f"Venda Loja #{venda.pk}"
        )
        venda.movimento_caixa = mov
        venda.save(update_fields=["movimento_caixa"])
    else:
        from apps.reservas import services as reservas

        conta = reservas.conta_aberta(conta_id)
        if not conta:
            raise ValidationError("Selecione uma conta do quarto aberta.")
        for produto, qtd, valor in linhas:
            reservas.lancar_na_conta(
                conta, "consumo", produto.natureza,
                f"Loja: {produto.nome}", valor, operador,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", "consumo", "Loja: desconto", desconto, operador
            )
        venda.conta_ref = f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}"
        venda.save(update_fields=["conta_ref"])

    return venda


@transaction.atomic
def cancelar_venda(venda, usuario, motivo):
    """Cancela uma venda de pagamento imediato: devolve estoque e estorna o caixa."""
    if venda.status != Venda.Status.FECHADA:
        raise ValidationError("Esta venda não está aberta para cancelamento.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo do cancelamento.")
    if venda.destino == Venda.Destino.CONTA:
        raise ValidationError(
            "Venda lançada na conta do quarto — ajuste pela conta da hospedagem."
        )
    # Devolve o estoque (ajuste, sem mexer no custo médio).
    for item in venda.itens.select_related("produto"):
        atual = saldo(item.produto, venda.local)
        ajustar(item.produto, venda.local, atual + item.quantidade, usuario,
                motivo=f"Cancelamento venda Loja #{venda.pk}")
    # Estorna o recebimento no caixa (exige o caixa aberto).
    if venda.movimento_caixa:
        estornar_movimento(
            venda.movimento_caixa, venda.movimento_caixa.sessao, usuario, motivo
        )
    venda.status = Venda.Status.CANCELADA
    venda.cancelada_em = timezone.now()
    venda.motivo_cancelamento = motivo
    venda.save()
    registrar_auditoria(usuario, "cancelamento_venda", venda, {"motivo": motivo})
    return venda


def vendas_do_dia():
    """Total e contagem de vendas fechadas hoje (para o dashboard)."""
    from django.db.models import Sum

    hoje = timezone.localdate()
    qs = Venda.objects.filter(status=Venda.Status.FECHADA, criado_em__date=hoje)
    return {"quantidade": qs.count(), "total": qs.aggregate(t=Sum("total"))["t"] or ZERO}

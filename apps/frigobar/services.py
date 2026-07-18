"""
Regras do Frigobar. Conferência lança o consumo na conta do quarto (via
`reservas.lancar_na_conta`, natureza CONSUMO) e a reposição baixa o estoque
central (via `nucleo.registrar_saida`). Só conversa com Reservas por services.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, registrar_saida

from .models import Conferencia, ItemComposicao, ItemConferencia


def composicao_do_tipo(tipo_uh):
    return (
        ItemComposicao.objects.filter(tipo_uh=tipo_uh)
        .select_related("produto")
    )


def conferencia_checkout_feita(*, uh=None, conta=None, desde=None) -> bool:
    """True se há conferência de check-out (não cancelada) para a estadia.

    Preferir `conta` (ID gravado na conferência). Sem conta, aceita UH +
    `desde` (ex.: checkin_real) — usado pelo guard de saída em Reservas.
    """
    qs = Conferencia.objects.filter(
        momento=Conferencia.Momento.CHECKOUT,
    ).exclude(status=Conferencia.Status.CANCELADA)
    if conta is not None:
        return qs.filter(conta_id=conta.pk).exists()
    if uh is None:
        return False
    qs = qs.filter(uh=uh)
    if desde is not None:
        qs = qs.filter(criado_em__gte=desde)
    return qs.exists()


@transaction.atomic
def registrar_conferencia(operador, conta, momento, consumos):
    """`consumos`: iterável de (produto, quantidade). Lança o consumido na conta
    do quarto e cria a conferência (base da lista de reposição)."""
    from apps.reservas import services as reservas

    uh = conta.reserva.uh
    conf = Conferencia.objects.create(
        uh=uh, momento=momento, criado_por=operador,
        conta_ref=f"{uh.numero} — {conta.reserva.hospede.nome}",
        conta_id=conta.pk,
    )
    for produto, quantidade in consumos:
        quantidade = int(quantidade or 0)
        if quantidade <= 0:
            continue
        item = ItemConferencia.objects.create(
            conferencia=conf, produto=produto, descricao=produto.nome,
            quantidade=quantidade, preco_unitario=produto.preco_venda,
            natureza=produto.natureza or NaturezaFiscal.CONSUMO,
        )
        reservas.lancar_na_conta(
            conta, "consumo", item.natureza,
            f"Frigobar: {item.descricao}", item.subtotal, operador,
        )
    return conf


@transaction.atomic
def repor(conferencia, operador, local):
    """Baixa o estoque central para repor o que foi consumido."""
    if conferencia.status != Conferencia.Status.CONFERIDA:
        raise ValidationError("Esta conferência já foi reposta ou cancelada.")
    if not conferencia.itens.exists():
        raise ValidationError("Nada a repor (nenhum consumo registrado).")
    for item in conferencia.itens.all():
        registrar_saida(
            item.produto, local, item.quantidade, operador,
            documento=f"Reposição frigobar #{conferencia.pk}",
        )
    conferencia.status = Conferencia.Status.REPOSTA
    conferencia.reposto_em = timezone.now()
    conferencia.reposto_por = operador
    conferencia.save(update_fields=["status", "reposto_em", "reposto_por"])
    return conferencia


def lista_reposicao():
    """Consumo agregado por produto das conferências ainda não repostas."""
    agregado = (
        ItemConferencia.objects
        .filter(conferencia__status=Conferencia.Status.CONFERIDA)
        .values("produto__id", "produto__nome")
        .annotate(total=Sum("quantidade"))
        .order_by("produto__nome")
    )
    return list(agregado)

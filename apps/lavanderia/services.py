"""
Regras do módulo Lavanderia. Interface pública para as views e integrações.
Cobrança reusa `receber_no_caixa` (núcleo) e `reservas.lancar_na_conta` (folio),
sempre com natureza SERVIÇO. A rouparia é um livro-razão por estado do enxoval.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, receber_no_caixa, registrar_auditoria

from .models import (
    ItemEnxoval,
    ItemOrdemLavanderia,
    MovimentoEnxoval,
    OrdemLavanderia,
)

ZERO = Decimal("0.00")


# ───────────────────────── (a) Serviço ao hóspede ─────────────────────────

def abrir_ordem(operador, cliente=None, rotulo="", prazo=None):
    rotulo = (rotulo or "").strip()
    if not (cliente or rotulo):
        raise ValidationError("Informe o hóspede/cliente ou uma identificação.")
    return OrdemLavanderia.objects.create(
        cliente=cliente, rotulo=rotulo, prazo=prazo, criado_por=operador
    )


def adicionar_item(ordem, servico, quantidade, operador):
    if not ordem.em_producao:
        raise ValidationError("Só é possível lançar itens antes da entrega.")
    quantidade = Decimal(str(quantidade))
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    existente = ordem.itens.filter(servico=servico).first()
    if existente:
        existente.quantidade += quantidade
        existente.save(update_fields=["quantidade"])
        return existente
    return ItemOrdemLavanderia.objects.create(
        ordem=ordem, servico=servico, descricao=servico.nome,
        quantidade=quantidade, preco_unitario=servico.preco,
        natureza=NaturezaFiscal.SERVICO,
    )


def remover_item(item):
    if not item.ordem.em_producao:
        raise ValidationError("A ordem já foi entregue.")
    item.delete()


def avancar_status(ordem):
    """Avança um passo no fluxo recebida → lavando → pronta."""
    fluxo = OrdemLavanderia.FLUXO
    if ordem.status not in fluxo or ordem.status == fluxo[-1]:
        raise ValidationError("A ordem já está pronta para entrega.")
    ordem.status = fluxo[fluxo.index(ordem.status) + 1]
    ordem.save(update_fields=["status"])
    return ordem


@transaction.atomic
def entregar(ordem, operador, destino, forma=None, conta_id=None, desconto=ZERO):
    if not ordem.em_producao:
        raise ValidationError("Esta ordem já foi encerrada.")
    if not ordem.itens.exists():
        raise ValidationError("A ordem está vazia.")
    desconto = Decimal(desconto or 0)
    if desconto < 0 or desconto > ordem.subtotal():
        raise ValidationError("Desconto inválido.")
    ordem.desconto = desconto
    total = ordem.total()

    if destino == OrdemLavanderia.Destino.CAIXA:
        if not forma:
            raise ValidationError("Escolha a forma de pagamento.")
        ordem.movimento_caixa = receber_no_caixa(
            operador, forma, total, f"Lavanderia #{ordem.pk}"
        )
        ordem.forma_pagamento = forma
    else:
        from apps.reservas import services as reservas

        conta = reservas.conta_aberta(conta_id)
        if not conta:
            raise ValidationError("Selecione uma conta do quarto aberta.")
        for item in ordem.itens.all():
            reservas.lancar_na_conta(
                conta, "servico", item.natureza,
                f"Lavanderia: {item.descricao}", item.subtotal, operador,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", NaturezaFiscal.SERVICO,
                "Lavanderia: desconto", desconto, operador,
            )
        ordem.conta_ref = f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}"

    ordem.destino = destino
    ordem.status = OrdemLavanderia.Status.ENTREGUE
    ordem.entregue_em = timezone.now()
    ordem.save()
    return ordem


def cancelar_ordem(ordem, operador, motivo=""):
    if ordem.status == OrdemLavanderia.Status.ENTREGUE:
        raise ValidationError("Ordem entregue não pode ser cancelada (já cobrada).")
    if ordem.status == OrdemLavanderia.Status.CANCELADA:
        raise ValidationError("Ordem já cancelada.")
    ordem.status = OrdemLavanderia.Status.CANCELADA
    ordem.motivo_cancelamento = motivo or ""
    ordem.save(update_fields=["status", "motivo_cancelamento"])
    registrar_auditoria(operador, "cancelamento_lavanderia", ordem, {"motivo": motivo or ""})
    return ordem


# ───────────────────────── (b) Rouparia interna ─────────────────────────

Estado = MovimentoEnxoval.Estado


def saldo_enxoval(item, estado) -> int:
    total = item.movimentos.filter(estado=estado).aggregate(s=Sum("quantidade"))["s"]
    return total or 0


def _mov(item, estado, quantidade, motivo, usuario, uh=None):
    MovimentoEnxoval.objects.create(
        item=item, estado=estado, quantidade=quantidade,
        motivo=motivo, criado_por=usuario, uh=uh,
    )


@transaction.atomic
def _transferir(item, de, para, quantidade, motivo, usuario, uh=None):
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    if saldo_enxoval(item, de) < quantidade:
        raise ValidationError(
            f"Saldo insuficiente de {item} em '{de}' ({saldo_enxoval(item, de)})."
        )
    _mov(item, de, -quantidade, motivo, usuario, uh)
    _mov(item, para, quantidade, motivo, usuario, uh)


def adquirir(item, quantidade, usuario):
    """Entrada de enxoval novo direto na rouparia (limpa)."""
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    _mov(item, Estado.LIMPA, quantidade, "aquisicao", usuario)


def distribuir(item, quantidade, usuario, uh=None):
    _transferir(item, Estado.LIMPA, Estado.EM_USO, quantidade, "distribuicao", usuario, uh)


def coletar_suja(item, quantidade, usuario, uh=None, origem="coleta"):
    _transferir(item, Estado.EM_USO, Estado.SUJA, quantidade, origem, usuario, uh)


def enviar_lavar(item, quantidade, usuario):
    _transferir(item, Estado.SUJA, Estado.LAVANDO, quantidade, "envio_lavagem", usuario)


def receber_limpo(item, quantidade, usuario):
    _transferir(item, Estado.LAVANDO, Estado.LIMPA, quantidade, "retorno_lavagem", usuario)


def baixar(item, quantidade, estado, motivo, usuario):
    """Baixa por desgaste/dano — sai do estado sem destino. Auditada."""
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    if saldo_enxoval(item, estado) < quantidade:
        raise ValidationError("Saldo insuficiente para baixa.")
    _mov(item, estado, -quantidade, f"baixa:{motivo}"[:40], usuario)
    registrar_auditoria(usuario, "baixa_enxoval", item,
                        {"quantidade": quantidade, "estado": estado, "motivo": motivo})


def posicao_enxoval():
    """Situação de cada item por estado + alerta de mínimo (sobre a rouparia limpa)."""
    linhas = []
    for item in ItemEnxoval.objects.filter(ativo=True):
        estados = {e.value: saldo_enxoval(item, e) for e in Estado}
        limpa = estados[Estado.LIMPA]
        linhas.append({
            "item": item,
            "estados": estados,
            "total": sum(estados.values()),
            "abaixo_minimo": limpa < item.minimo,
        })
    return linhas


def coletar_faxina(uh, usuario):
    """Chamado pela conclusão da faxina (Governança): recolhe o kit padrão de cada
    item (por_faxina) de 'em uso' para 'suja', limitado ao saldo em uso."""
    for item in ItemEnxoval.objects.filter(ativo=True, por_faxina__gt=0):
        qtd = min(item.por_faxina, saldo_enxoval(item, Estado.EM_USO))
        if qtd > 0:
            coletar_suja(item, qtd, usuario, uh=uh, origem="faxina")


def pendencias_auditoria():
    """Ordens de lavanderia atrasadas / abertas há muito, para a Auditoria (read-only)."""
    from datetime import timedelta

    from django.urls import reverse
    achados = []
    hoje = timezone.localdate()
    limite = timezone.now() - timedelta(days=3)
    for o in OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO):
        if o.prazo and o.prazo < hoje:
            achados.append({
                "area": "Lavanderia", "tipo": "lavanderia_atrasada", "gravidade": "alta",
                "descricao": f"Ordem #{o.pk} ({o.titulo}): prazo {o.prazo:%d/%m} venceu e não foi entregue.",
                "url": reverse("lavanderia:ordem", args=[o.pk]),
            })
        elif o.recebida_em < limite:
            achados.append({
                "area": "Lavanderia", "tipo": "lavanderia_antiga", "gravidade": "media",
                "descricao": f"Ordem #{o.pk} ({o.titulo}) em produção há mais de 3 dias.",
                "url": reverse("lavanderia:ordem", args=[o.pk]),
            })
    return achados

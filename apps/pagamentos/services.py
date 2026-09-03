"""
Regras de Pagamentos Online. Cria cobranças no gateway, processa a confirmação
(webhook) de forma idempotente e, quando a cobrança é sinal de reserva, confirma a
reserva (via reservas.services). Estorno pelo gateway. Tudo auditado por eventos.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .gateways import get_gateway
from .models import Cobranca, EventoPagamento

# Finalidades expostas para outros módulos (evita importar o model lá fora).
FINALIDADE_SINAL = Cobranca.Finalidade.SINAL
FINALIDADE_SALDO = Cobranca.Finalidade.SALDO
FINALIDADE_AVULSO = Cobranca.Finalidade.AVULSO


@transaction.atomic
def criar_cobranca(operador, *, valor, metodo, descricao, finalidade=Cobranca.Finalidade.AVULSO,
                   pagador=None, reserva_id=None, grupo_id=None, parcelas=1):
    valor = Decimal(str(valor or 0))
    if valor <= 0:
        raise ValidationError("O valor deve ser positivo.")
    if not descricao:
        raise ValidationError("Descreva a cobrança.")
    cobranca = Cobranca.objects.create(
        valor=valor, metodo=metodo, parcelas=int(parcelas or 1),
        descricao=descricao, finalidade=finalidade, pagador=pagador,
        reserva_id=reserva_id or None, grupo_id=grupo_id or None, criado_por=operador,
    )
    dados = get_gateway().criar_cobranca(cobranca)
    for campo in ("gateway", "gateway_id", "pix_copia_cola", "expira_em", "payload"):
        if campo in dados:
            setattr(cobranca, campo, dados[campo])
    cobranca.save()
    EventoPagamento.objects.create(cobranca=cobranca, tipo="criada",
                                   origem="sistema", detalhe={"gateway": cobranca.gateway})
    return cobranca


@transaction.atomic
def confirmar_pagamento(cobranca, usuario=None, origem="webhook"):
    """Confirmação (idempotente) — o webhook do gateway chama por aqui."""
    if cobranca.status == Cobranca.Status.PAGO:
        return cobranca  # idempotência: já processado
    if cobranca.status not in (Cobranca.Status.PENDENTE,):
        raise ValidationError("Cobrança não está pendente.")
    cobranca.status = Cobranca.Status.PAGO
    cobranca.pago_em = timezone.now()
    cobranca.save(update_fields=["status", "pago_em"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="paga", origem=origem)

    # Sinal pago → confirma a reserva (ou o grupo inteiro), se Reservas ativo.
    if cobranca.finalidade == Cobranca.Finalidade.SINAL and modulo_ativo(Modulo.RESERVAS):
        if cobranca.reserva_id:
            from apps.reservas.services import confirmar_reserva
            confirmar_reserva(cobranca.reserva_id, usuario or cobranca.criado_por)
            _sincronizar_recibo_site(cobranca)
        elif cobranca.grupo_id:
            from apps.reservas.services import confirmar_grupo
            confirmar_grupo(cobranca.grupo_id, usuario or cobranca.criado_por)
    return cobranca


def _sincronizar_recibo_site(cobranca):
    """Atualiza o recibo do canal (site.Reserva) quando o sinal CRM é pago."""
    try:
        from apps.site.models import Reserva as SiteReserva
    except Exception:
        return
    qs = SiteReserva.objects.filter(
        crm_reserva_id=cobranca.reserva_id, status="aguardando",
    )
    for recibo in qs:
        recibo.status = "confirmada"
        if not recibo.pagamento_id:
            recibo.pagamento_id = str(cobranca.token)
        recibo.expira_em = None
        recibo.save(update_fields=["status", "pagamento_id", "expira_em", "atualizado_em"])


@transaction.atomic
def estornar(cobranca, operador):
    if cobranca.status != Cobranca.Status.PAGO:
        raise ValidationError("Só é possível estornar uma cobrança paga.")
    resultado = get_gateway().estornar(cobranca)
    cobranca.status = Cobranca.Status.ESTORNADO
    cobranca.save(update_fields=["status"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="estornada",
                                   origem="gateway", detalhe=resultado)
    registrar_auditoria(operador, "estorno_pagamento", cobranca,
                        {"valor": str(cobranca.valor)})
    return cobranca


def cancelar(cobranca, operador):
    if cobranca.status != Cobranca.Status.PENDENTE:
        raise ValidationError("Só cobranças pendentes podem ser canceladas.")
    cobranca.status = Cobranca.Status.CANCELADO
    cobranca.save(update_fields=["status"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="cancelada", origem="operador")
    return cobranca


def conciliacao():
    """Resumo por status para conferência gateway × sistema."""
    from django.db.models import Count, Sum
    return list(
        Cobranca.objects.values("status")
        .annotate(qtd=Count("id"), total=Sum("valor"))
        .order_by("status")
    )


@transaction.atomic
def registrar_liquidacao(cobranca, *, valor_liquido=None, taxa=None,
                         data_liquidacao=None, id_liquidacao="", origem="webhook"):
    """Marca o dinheiro como caído na conta (liquidação bancária).

    Idempotente: rechamar com os mesmos dados não duplica. Só cobranças pagas
    liquidam. `valor_liquido`/`taxa` são o depósito real (bruto − taxa da
    adquirente); `data_liquidacao`/`id_liquidacao` amarram na linha do extrato."""
    if cobranca.status != Cobranca.Status.PAGO:
        raise ValidationError("Só uma cobrança paga pode ser liquidada.")
    valor_liquido = Decimal(str(valor_liquido)) if valor_liquido is not None else None
    taxa = Decimal(str(taxa)) if taxa is not None else None
    if valor_liquido is not None and taxa is None:
        taxa = (cobranca.valor - valor_liquido)
    if taxa is not None and valor_liquido is None:
        valor_liquido = (cobranca.valor - taxa)
    ja_liquidada = cobranca.liquidado
    cobranca.liquidado = True
    cobranca.valor_liquido = valor_liquido
    cobranca.taxa = taxa
    cobranca.data_liquidacao = data_liquidacao
    cobranca.id_liquidacao = id_liquidacao or cobranca.id_liquidacao
    cobranca.save(update_fields=[
        "liquidado", "valor_liquido", "taxa", "data_liquidacao", "id_liquidacao",
    ])
    if not ja_liquidada:
        EventoPagamento.objects.create(
            cobranca=cobranca, tipo=EventoPagamento.Tipo.LIQUIDADA, origem=origem,
            detalhe={
                "valor_liquido": str(valor_liquido) if valor_liquido is not None else None,
                "taxa": str(taxa) if taxa is not None else None,
                "data_liquidacao": data_liquidacao.isoformat() if data_liquidacao else None,
                "id_liquidacao": id_liquidacao,
            },
        )
    return cobranca


def recebimentos(*, inicio=None, fim=None, metodo="", status="", liquidacao=""):
    """Lista de cobranças para a tela de conciliação (recebimentos × banco).

    Filtra por período de pagamento, método, status e situação de liquidação;
    devolve as cobranças + totais (bruto, taxa, líquido, quantidade)."""
    from django.db.models import Count, Sum

    qs = Cobranca.objects.select_related("pagador")
    # Recebimentos pagos → filtra pela data de pagamento; senão pela de criação.
    campo_data = "pago_em__date" if status == Cobranca.Status.PAGO else "criado_em__date"
    if inicio:
        qs = qs.filter(**{f"{campo_data}__gte": inicio})
    if fim:
        qs = qs.filter(**{f"{campo_data}__lte": fim})
    if metodo:
        qs = qs.filter(metodo=metodo)
    if status:
        qs = qs.filter(status=status)
    if liquidacao == "liquidado":
        qs = qs.filter(liquidado=True)
    elif liquidacao == "a_liquidar":
        qs = qs.filter(status=Cobranca.Status.PAGO, liquidado=False)

    agg = qs.aggregate(
        qtd=Count("id"), bruto=Sum("valor"),
        taxa=Sum("taxa"), liquido=Sum("valor_liquido"),
    )
    pagas = qs.filter(status=Cobranca.Status.PAGO)
    totais = {
        "qtd": agg["qtd"] or 0,
        "bruto": agg["bruto"] or Decimal("0"),
        "taxa": agg["taxa"] or Decimal("0"),
        "liquido": agg["liquido"] or Decimal("0"),
        "recebido": pagas.aggregate(t=Sum("valor"))["t"] or Decimal("0"),
        "liquidado_qtd": pagas.filter(liquidado=True).count(),
        "a_liquidar_qtd": pagas.filter(liquidado=False).count(),
    }
    return list(qs[:300]), totais


def autorizar_cartao_online(cobranca, card: dict, usuario=None):
    """Autoriza o cartão digitado pelo hóspede na página pública e, se aprovado,
    confirma o pagamento. Retorna (ok: bool, mensagem: str). Nunca guarda o PAN:
    o cartão só transita para o gateway — o payload persistido é o do provedor."""
    if cobranca.metodo != Cobranca.Metodo.CARTAO:
        return False, "Esta cobrança não é de cartão."
    if cobranca.status != Cobranca.Status.PENDENTE:
        return False, "Cobrança não está pendente."
    gw = get_gateway()
    if not hasattr(gw, "autorizar_cartao"):
        return False, "Gateway não suporta autorização de cartão."
    try:
        dados = gw.autorizar_cartao(cobranca, card)
    except ValidationError as erro:
        EventoPagamento.objects.create(
            cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
            origem="cartao", detalhe={"erro": " ".join(erro.messages)},
        )
        return False, " ".join(erro.messages)
    # Persiste só o retorno do gateway (sem o cartão cru).
    gid = dados.get("gateway_id")
    if gid:
        cobranca.gateway_id = gid
    payload = dict(dados.get("payload") or {})
    payload.pop("card", None)  # nunca persistir o PAN
    cobranca.payload = payload
    cobranca.save(update_fields=["gateway_id", "payload"])

    # A requisição pode ter sido aceita (HTTP 200) e a transação RECUSADA. Só confirma
    # em status inequívoco de pago; recusa/desconhecido NÃO confirma (fail-safe).
    from .gateways import status_negado, status_pago
    status_raw = dados.get("status_raw")
    if status_pago(status_raw) is True:
        confirmar_pagamento(cobranca, usuario or cobranca.criado_por, origem="cartao")
        return True, "Pagamento aprovado."
    EventoPagamento.objects.create(
        cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
        origem="cartao", detalhe={"status_raw": status_raw, "aprovado": False},
    )
    if status_negado(status_raw):
        return False, "Cartão não autorizado pela operadora. Tente outro cartão."
    return False, ("Não foi possível confirmar o pagamento agora. "
                   "Se o valor foi debitado, ele será conciliado automaticamente.")

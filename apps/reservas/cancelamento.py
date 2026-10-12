"""Política de cancelamento — única (Fase 6, decisão do dono 09-10/10/2026).

Reagendar é sempre a 1ª opção (não é cancelamento — ver `services.transferir_datas`).
Quando o hóspede cancela de verdade:

- **Estadia NÃO iniciada:** janela de arrependimento (CDC art. 49) de
  `CANCELAMENTO_ARREPENDIMENTO_DIAS` a partir da **confirmação** (pagamento dos 30%).
  Dentro da janela → devolve 100%. Depois → retém `CANCELAMENTO_RETENCAO_PCT`% do valor
  total da reserva (devolve o resto).
- **Estadia já iniciada:** cobra as **diárias consumidas** (valor cheio) + a retenção; a
  janela de 7 dias NÃO se aplica.

Não há mais tarifa não-reembolsável — esta é a única regra. Base da retenção = valor da
hospedagem (diárias), sem as taxas (ISS/turismo são repasse, pagos no check-out).
Funções puras: a execução do estorno (devolver via caixa/pagamentos) fica na camada de UI.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.utils import timezone

CENTAVO = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _retencao_pct() -> Decimal:
    return Decimal(str(settings.CANCELAMENTO_RETENCAO_PCT)) / 100


def valor_total(reserva) -> Decimal:
    """Valor da hospedagem (base da retenção) = diária × noites."""
    return _q(reserva.valor_diaria * reserva.noites)


def politica_cancelamento(reserva, quando=None) -> dict:
    """Calcula o que a pousada retém e o cenário do cancelamento de `reserva` na data
    `quando` (default agora). Puro — não grava nem estorna. Campos:

    - `cenario`: 'nao_iniciada' | 'em_hospedagem'
    - `dentro_arrependimento`: bool (só faz sentido em 'nao_iniciada')
    - `dias_consumidos`, `diarias_consumidas`: noites já usadas e seu valor
    - `retencao_pct`, `retencao_valor`: a multa (sobre o valor total)
    - `valor_total`: hospedagem
    - `cobranca`: o que a pousada FICA (diárias consumidas + retenção)
    """
    quando = quando or timezone.now()
    hoje = timezone.localdate(quando)
    total = valor_total(reserva)
    pct = _retencao_pct()
    retencao = _q(total * pct)

    Status = reserva.Status
    if reserva.status == Status.HOSPEDADA:
        noites = reserva.noites
        # Já hospedado: cobra ao menos 1 diária (ocupou o quarto na noite), até o total.
        dias = min(noites, max(1, (hoje - reserva.checkin).days))
        diarias = _q(dias * reserva.valor_diaria)
        return {
            "cenario": "em_hospedagem",
            "dentro_arrependimento": False,
            "dias_consumidos": dias,
            "diarias_consumidas": diarias,
            "retencao_pct": pct * 100,
            "retencao_valor": retencao,
            "valor_total": total,
            "cobranca": _q(diarias + retencao),
        }

    # Não iniciada: janela de arrependimento a partir da confirmação; sem confirmação,
    # conta do pagamento (1º adiantamento) ou da criação da reserva — assim a janela
    # sempre começa e, passada ela, a retenção de 10% se aplica.
    janela = settings.CANCELAMENTO_ARREPENDIMENTO_DIAS
    ref = reserva.confirmada_em
    if ref is None:
        primeiro = reserva.adiantamentos.order_by("criado_em").first()
        ref = primeiro.criado_em if primeiro else reserva.criado_em
    dentro = (hoje - timezone.localdate(ref)).days <= janela
    retido = Decimal("0.00") if dentro else retencao
    return {
        "cenario": "nao_iniciada",
        "dentro_arrependimento": dentro,
        "dias_consumidos": 0,
        "diarias_consumidas": Decimal("0.00"),
        "retencao_pct": pct * 100,
        "retencao_valor": retido,
        "valor_total": total,
        "cobranca": retido,
    }


def devolucao(reserva, total_pago: Decimal, quando=None) -> Decimal:
    """Quanto devolver ao hóspede = o que ele pagou − o que a pousada fica (nunca < 0)."""
    pol = politica_cancelamento(reserva, quando=quando)
    return max(Decimal("0.00"), _q(Decimal(total_pago) - pol["cobranca"]))


def total_pago(reserva) -> Decimal:
    """Total já pago pelo hóspede = adiantamentos + pagamentos na conta (se houver)."""
    from django.db.models import Sum

    pago = reserva.adiantamentos.aggregate(t=Sum("valor"))["t"] or Decimal("0.00")
    conta = getattr(reserva, "conta", None)
    if conta:
        pago += conta.total_pago()
    return _q(pago)


def resumo_cancelamento(reserva, quando=None) -> dict:
    """Política + total pago + valor a devolver, prontos para a UI (CRM) e a trilha."""
    pol = politica_cancelamento(reserva, quando=quando)
    pago = total_pago(reserva)
    return {**pol, "pago": pago, "devolver": devolucao(reserva, pago, quando=quando)}


def descricao_politica() -> dict:
    """Texto/numeros da política para exibir no site e no CRM (estruturado)."""
    return {
        "arrependimento_dias": settings.CANCELAMENTO_ARREPENDIMENTO_DIAS,
        "retencao_pct": _retencao_pct() * 100,
        "resumo": (
            f"Cancelamento grátis até {settings.CANCELAMENTO_ARREPENDIMENTO_DIAS} dias "
            f"após a confirmação da reserva. Depois desse prazo, retemos "
            f"{(_retencao_pct() * 100).normalize()}% do valor total (devolvemos o restante). "
            "Se a estadia já começou, cobramos as diárias usadas mais a retenção. "
            "Você também pode transferir sua reserva para outra data."
        ),
    }

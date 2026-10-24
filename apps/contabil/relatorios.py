"""
Relatórios da camada Contábil (Etapa 5): DRE gerencial, fluxo de caixa e
fila de órfãos. Tudo por SOMA dos lançamentos classificados (sem partidas
dobradas). O `conta_contabil` carimbado é a fonte da verdade da DRE.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    LancamentoFinanceiro,
    MovimentoCaixa,
)

from .models import MapeamentoContabil

ZERO = Decimal("0.00")


def periodo(ano: int, mes: int) -> tuple[date, date]:
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


def _totais_por_conta(ano: int, mes: int) -> dict[str, Decimal]:
    ini, fim = periodo(ano, mes)
    qs = (
        LancamentoFinanceiro.objects.filter(data__range=(ini, fim))
        .values("conta_contabil")
        .annotate(total=Sum("valor"))
    )
    return {r["conta_contabil"]: (r["total"] or ZERO) for r in qs}


def dre(ano: int, mes: int) -> dict:
    """Demonstração de Resultado do mês, por competência."""
    t = _totais_por_conta(ano, mes)

    def v(classif: str) -> Decimal:
        return t.get(classif, ZERO) or ZERO

    receita_bruta = v("3.1.01.01") + v("3.1.01.03")
    deducoes = v("3.1.02.01") + v("3.1.02.02")
    receita_liquida = receita_bruta - deducoes
    custos = v("4.2.01.01") + v("4.2.01.02") + v("4.2.01.03") + v("4.5.01.01")
    lucro_bruto = receita_liquida - custos
    desp_vendas = v("5.1.01.02")
    desp_adm = v("5.1.02.02")
    desp_fin = v("5.1.03.02")
    rec_fin = v("5.1.03.01")
    despesas = desp_vendas + desp_adm + desp_fin
    resultado = lucro_bruto - despesas + rec_fin
    nao_classificado = v("")

    def pct(valor: Decimal) -> str:
        if receita_bruta <= 0:
            return "—"
        return f"{(valor / receita_bruta * 100):.0f}%"

    # linhas: (nivel, rotulo, valor, estilo)  estilo ∈ grupo/sub/resultado
    linhas = [
        ("grupo", "RECEITA BRUTA", receita_bruta, "grupo"),
        ("sub", "Prestação de Serviços (hospedagem, day use, eventos)", v("3.1.01.03"), "sub"),
        ("sub", "Revenda de Mercadorias (restaurante, loja)", v("3.1.01.01"), "sub"),
        ("grupo", "(−) Deduções", -deducoes, "grupo"),
        ("sub", "Simples Nacional (DAS)", v("3.1.02.01"), "sub"),
        ("sub", "Devoluções e abatimentos", v("3.1.02.02"), "sub"),
        ("resultado", "= RECEITA LÍQUIDA", receita_liquida, "resultado"),
        ("grupo", "(−) Custos dos Serviços e Mercadorias", -custos, "grupo"),
        ("sub", "Gastos com Pessoal (operação)", v("4.2.01.01"), "sub"),
        ("sub", "Materiais aplicados nos serviços", v("4.2.01.02"), "sub"),
        ("sub", "Gastos gerais dos serviços", v("4.2.01.03"), "sub"),
        ("sub", "CMV — Custo das Mercadorias Vendidas", v("4.5.01.01"), "sub"),
        ("resultado", "= LUCRO BRUTO", lucro_bruto, "resultado"),
        ("grupo", "(−) Despesas Operacionais", -despesas, "grupo"),
        ("sub", "Despesas com Vendas (comercial, OTA, propaganda)", desp_vendas, "sub"),
        ("sub", "Despesas Administrativas", desp_adm, "sub"),
        ("sub", "Despesas Financeiras (juros, taxas de cartão)", desp_fin, "sub"),
        ("sub", "(+) Receitas Financeiras", rec_fin, "sub"),
        ("resultado", "= RESULTADO DO PERÍODO", resultado, "resultado"),
    ]
    return {
        "linhas": linhas,
        "receita_bruta": receita_bruta,
        "receita_liquida": receita_liquida,
        "lucro_bruto": lucro_bruto,
        "despesas": despesas,
        "resultado": resultado,
        "margem": pct(resultado),
        "nao_classificado": nao_classificado,
    }


def fluxo_caixa(ano: int, mes: int) -> dict:
    """Realizado (MovimentoCaixa) + projetado (contas em aberto no período)."""
    ini, fim = periodo(ano, mes)
    # Só movimentos de NEGÓCIO: recebimento (entra) e estorno (sai, devolução).
    # Reforço e sangria são internos (troco/cofre) — não são fluxo do negócio.
    movs = MovimentoCaixa.objects.filter(
        criado_em__date__range=(ini, fim),
        tipo__in=[MovimentoCaixa.Tipo.RECEBIMENTO, MovimentoCaixa.Tipo.ESTORNO],
    )

    entradas = movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO).aggregate(
        s=Sum("valor"))["s"] or ZERO
    saidas = movs.filter(tipo=MovimentoCaixa.Tipo.ESTORNO).aggregate(
        s=Sum("valor"))["s"] or ZERO

    abertas = ContaPagarReceber.objects.filter(
        status=ContaPagarReceber.Status.ABERTA, vencimento__range=(ini, fim)
    )
    a_receber = abertas.filter(tipo=ContaPagarReceber.Tipo.RECEBER).aggregate(
        s=Sum("valor"))["s"] or ZERO
    a_pagar = abertas.filter(tipo=ContaPagarReceber.Tipo.PAGAR).aggregate(
        s=Sum("valor"))["s"] or ZERO

    return {
        "entradas": entradas,
        "saidas": saidas,
        "liquido": entradas - saidas,
        "a_receber": a_receber,
        "a_pagar": a_pagar,
        "projetado": (entradas - saidas) + a_receber - a_pagar,
        "movimentos": movs.order_by("criado_em")[:200],
        "titulos": abertas.order_by("vencimento"),
    }


def orfaos() -> dict:
    """O que ainda não está classificado — alimenta a fila de 'a classificar'."""
    lancamentos = LancamentoFinanceiro.objects.filter(
        conta_contabil=""
    ).select_related("categoria").order_by("-data")
    com_depara = MapeamentoContabil.objects.filter(
        categoria__isnull=False
    ).values_list("categoria_id", flat=True)
    categorias = CategoriaFinanceira.objects.exclude(id__in=com_depara)
    return {
        "lancamentos": lancamentos,
        "categorias": categorias,
        "total": lancamentos.count() + categorias.count(),
    }

"""
Interface pública da camada Contábil (Etapa 1).

Os outros módulos NUNCA importam os models daqui — conversam por estes services.
Nesta etapa o essencial é `resolver_conta`: dada a origem de um lançamento/
movimento, devolve a conta contábil pelo de-para (prioridade + especificidade),
com fallback por tipo para nunca ficar órfão.
"""

from __future__ import annotations

from apps.nucleo.models.financeiro import CategoriaFinanceira

from .models import ContaContabil, MapeamentoContabil


def resolver_conta(
    *,
    tipo: str | None = None,
    categoria: CategoriaFinanceira | None = None,
    centro: str = "",
    natureza_folio: str = "",
    origem_sistema: str = "",
) -> ContaContabil | None:
    """
    Resolve a conta contábil para uma entrada de dinheiro.

    `tipo` é o tipo do lançamento (CategoriaFinanceira.Tipo: receita/despesa),
    usado só para o fallback quando nenhuma regra específica casa.
    """
    categoria_id = categoria.id if categoria else None

    candidatos: list[MapeamentoContabil] = []
    for m in (
        MapeamentoContabil.objects.filter(ativo=True)
        .select_related("conta", "categoria")
    ):
        if m.categoria_id and m.categoria_id != categoria_id:
            continue
        if m.centro and m.centro != centro:
            continue
        if m.natureza_folio and m.natureza_folio != natureza_folio:
            continue
        if m.origem_sistema and m.origem_sistema != origem_sistema:
            continue
        # Fallbacks não entram na disputa normal; só se nada mais casar.
        if m.origem_sistema in (
            MapeamentoContabil.FALLBACK_RECEITA,
            MapeamentoContabil.FALLBACK_DESPESA,
        ):
            continue
        candidatos.append(m)

    if candidatos:
        candidatos.sort(key=lambda m: (m.prioridade, m.especificidade), reverse=True)
        return candidatos[0].conta

    return _fallback(tipo)


def _fallback(tipo: str | None) -> ContaContabil | None:
    chave = None
    if tipo == CategoriaFinanceira.Tipo.RECEITA:
        chave = MapeamentoContabil.FALLBACK_RECEITA
    elif tipo == CategoriaFinanceira.Tipo.DESPESA:
        chave = MapeamentoContabil.FALLBACK_DESPESA
    if not chave:
        return None
    m = (
        MapeamentoContabil.objects.filter(ativo=True, origem_sistema=chave)
        .select_related("conta")
        .first()
    )
    return m.conta if m else None


def plano_de_contas():
    """Todas as contas ativas, em ordem de classificação (para a árvore/telas)."""
    return ContaContabil.objects.filter(ativa=True).order_by("classificacao")

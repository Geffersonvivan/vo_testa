"""
Capturas automáticas (Etapa 3) — trazer pra DRE o que hoje some.

Geram `LancamentoFinanceiro` por COMPETÊNCIA, classificados e idempotentes
(chave `referencia`). Leem os módulos-fonte pelos services públicos deles
(pagamentos, estoque) — não importam models de outros módulos (núcleo ok).

- Taxa de cartão (adquirente): Pagamentos → 5.1.03.02. Um lançamento por cobrança.
- CMV: motor de Estoque → 4.5.01.01. Um lançamento por módulo/mês (recomputável).
- Comissão de OTA: 5.1.01.02 — STUB: o sistema ainda NÃO registra comissão
  (virá com o módulo Canais/OTAs). Governado por `CONTABIL_COMISSAO_OTA_PCT`
  (default 0 = no-op).
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings

from apps.nucleo.models.estoque import cmv_por_modulo
from apps.nucleo.models.financeiro import (
    CENTRO_NUCLEO,
    CategoriaFinanceira,
    LancamentoFinanceiro,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.sistema import usuario_de_sistema

from .services import resolver_conta

# origem -> (nome da categoria, origem_sistema p/ resolver a conta)
CATEGORIAS = {
    "taxa_cartao": ("Taxa de cartão (adquirente)", "pagamento_taxa"),
    "cmv": ("Custo das mercadorias vendidas (CMV)", "cmv"),
    "comissao_ota": ("Comissão de canal (OTA)", "comissao_ota"),
}


def _robo():
    return usuario_de_sistema("_contabil", "Contábil (automático)")


def categoria_automatica(nome: str, tipo: str) -> CategoriaFinanceira:
    """Categoria gerida pelo sistema (marcada `automatica` → fora do lançamento manual)."""
    cat, criada = CategoriaFinanceira.objects.get_or_create(
        nome=nome, tipo=tipo, defaults={"automatica": True}
    )
    if not criada and not cat.automatica:
        cat.automatica = True
        cat.save(update_fields=["automatica"])
    return cat


def _categoria(origem: str) -> CategoriaFinanceira:
    nome, _ = CATEGORIAS[origem]
    return categoria_automatica(nome, CategoriaFinanceira.Tipo.DESPESA)


def _conta_classif(origem: str) -> str:
    conta = resolver_conta(origem_sistema=CATEGORIAS[origem][1])
    return conta.classificacao if conta else ""


def _ultimo_dia(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def capturar_taxas_cartao(ano: int, mes: int) -> int:
    """Um lançamento de despesa por cobrança liquidada com taxa no mês."""
    from apps.pagamentos.services import taxas_do_periodo

    criados = 0
    cat = None
    for item in taxas_do_periodo(ano, mes):
        ref = f"taxa_cartao:cobranca:{item['id']}"
        if LancamentoFinanceiro.objects.filter(referencia=ref).exists():
            continue
        cat = cat or _categoria("taxa_cartao")
        LancamentoFinanceiro.objects.create(
            tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat, centro=CENTRO_NUCLEO,
            descricao=f"Taxa da adquirente — cobrança #{item['id']}",
            valor=item["taxa"], data=item["data"], criado_por=_robo(),
            origem="taxa_cartao", referencia=ref,
            conta_contabil=_conta_classif("taxa_cartao"),
        )
        criados += 1
    return criados


def capturar_cmv(ano: int, mes: int) -> int:
    """Um lançamento de CMV por módulo/mês (recomputável: atualiza o valor)."""
    data = _ultimo_dia(ano, mes)
    classif = _conta_classif("cmv")
    cat = None
    tocados = 0
    for modulo, total in cmv_por_modulo(ano, mes).items():
        ref = f"cmv:{ano:04d}-{mes:02d}:{modulo}"
        cat = cat or _categoria("cmv")
        setor = dict(Modulo.choices).get(modulo, modulo)
        LancamentoFinanceiro.objects.update_or_create(
            referencia=ref,
            defaults=dict(
                tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat, centro=modulo,
                descricao=f"CMV {setor} — {ano:04d}/{mes:02d}",
                valor=total, data=data, criado_por=_robo(),
                origem="cmv", conta_contabil=classif,
            ),
        )
        tocados += 1
    return tocados


def capturar_receita(ano: int, mes: int) -> int:
    """
    Receita por competência, lida dos módulos (NUNCA digitada à mão) — elimina a
    dupla contagem do lançamento manual. Usa os services públicos que o Relatórios
    já usa (sem sobreposição: diárias + total vendido por setor).

      diárias e lavanderia  → serviço    → 3.1.01.03
      loja e restaurante    → mercadoria → 3.1.01.01

    1 lançamento por setor/mês, recomputável (update_or_create).
    """
    from apps.nucleo.models import modulo_ativo

    ini = date(ano, mes, 1)
    fim = _ultimo_dia(ano, mes)
    itens = []  # (centro, nome_categoria, classificação, valor)

    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import diarias_periodo
        itens.append((Modulo.RESERVAS, "Hospedagem", "3.1.01.03", diarias_periodo(ini, fim)))
    if modulo_ativo(Modulo.LOJA):
        from apps.loja.services import faturamento_periodo as f_loja
        f = f_loja(ini, fim)
        itens.append((Modulo.LOJA, "Loja", "3.1.01.01", f["caixa"] + f["quarto"]))
    if modulo_ativo(Modulo.RESTAURANTE):
        from apps.restaurante.services import faturamento_periodo as f_rest
        f = f_rest(ini, fim)
        itens.append((Modulo.RESTAURANTE, "Restaurante", "3.1.01.01", f["caixa"] + f["quarto"]))
    if modulo_ativo(Modulo.LAVANDERIA):
        from apps.lavanderia.services import faturamento_periodo as f_lav
        f = f_lav(ini, fim)
        itens.append((Modulo.LAVANDERIA, "Lavanderia", "3.1.01.03", f["caixa"] + f["quarto"]))

    tocados = 0
    for centro, nome_cat, classif, valor in itens:
        ref = f"receita:{centro}:{ano:04d}-{mes:02d}"
        valor = valor or Decimal("0")
        if valor > 0:
            cat = categoria_automatica(nome_cat, CategoriaFinanceira.Tipo.RECEITA)
            LancamentoFinanceiro.objects.update_or_create(
                referencia=ref,
                defaults=dict(
                    tipo=CategoriaFinanceira.Tipo.RECEITA, categoria=cat, centro=centro,
                    descricao=f"Receita {nome_cat} — {ano:04d}/{mes:02d}",
                    valor=valor, data=fim, criado_por=_robo(),
                    origem="receita", conta_contabil=classif,
                ),
            )
            tocados += 1
        else:
            LancamentoFinanceiro.objects.filter(referencia=ref).delete()
    return tocados


def capturar_comissoes_ota(ano: int, mes: int) -> int:
    """
    STUB: o CRM ainda não registra comissão de OTA (virá com o módulo Canais/OTAs).
    Governado por `CONTABIL_COMISSAO_OTA_PCT`. Com 0 (default), é no-op.
    """
    pct = Decimal(str(getattr(settings, "CONTABIL_COMISSAO_OTA_PCT", 0) or 0))
    if pct <= 0:
        return 0
    # Sem fonte de dado de comissão ainda; mecanismo pronto para quando houver.
    return 0


def capturar_mes(ano: int, mes: int) -> dict[str, int]:
    """Orquestra todas as capturas do mês. Idempotente."""
    return {
        "receita": capturar_receita(ano, mes),
        "taxa_cartao": capturar_taxas_cartao(ano, mes),
        "cmv": capturar_cmv(ano, mes),
        "comissao_ota": capturar_comissoes_ota(ano, mes),
    }

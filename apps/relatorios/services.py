"""
Relatórios do CRM (ESPECIFICACAO §4.6). Framework simples: cada relatório é uma
função que recebe (início, fim) e devolve `{kpis, colunas, linhas}`; uma view
genérica renderiza/exporta. **Read-only** e desacoplado — consome services dos
módulos e models do núcleo, nunca models internos de outros módulos.

Dois grupos: **Consolidados** (cruzam módulos) e **Por módulo** (individuais).
"""
from decimal import Decimal

from django.db.models import Sum

from apps.nucleo.modulos import Modulo
# Seletor de período compartilhado (mês/ano) — mesmo controle da Trilha de auditoria.
from apps.nucleo.periodos import periodo, selecao_periodo  # noqa: F401


def _rs(v):
    return f"R$ {Decimal(v or 0):.2f}"


# ───────────────────────── Consolidados (cruzados) ─────────────────────────

def _movimentos_por_forma(inicio, fim):
    from apps.nucleo.models import MovimentoCaixa
    return (
        MovimentoCaixa.objects
        .filter(criado_em__date__range=(inicio, fim),
                tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("forma_pagamento__nome")
        .annotate(total=Sum("valor")).order_by("-total")
    )


def rel_producao(inicio, fim):
    from apps.reservas.services import relatorio_producao
    p = relatorio_producao(inicio, fim)
    linhas = [[m["forma_pagamento__nome"] or "—", _rs(m["total"])]
              for m in _movimentos_por_forma(inicio, fim)]
    return {
        "kpis": [("Serviço", _rs(p["servico"])), ("Consumo", _rs(p["consumo"])),
                 ("Receita total", _rs(p["total"]))],
        "colunas": ["Recebido por forma de pagamento", "Valor"],
        "linhas": linhas,
    }


def rel_ocupacao(inicio, fim):
    from apps.reservas.services import relatorio_ocupacao
    o = relatorio_ocupacao(inicio, fim)
    linhas = [[tipo, str(n)] for tipo, n in sorted(o["por_tipo"].items())]
    return {
        "kpis": [("Ocupação", f"{o['taxa']}%"), ("Diária média (ADR)", _rs(o["adr"])),
                 ("RevPAR", _rs(o["revpar"])),
                 ("Diárias-quarto", f"{o['ocupadas']}/{o['disponiveis']}")],
        "colunas": ["Tipo de quarto", "Diárias-quarto ocupadas"],
        "linhas": linhas,
    }


def rel_caixa(inicio, fim):
    from apps.nucleo.models import MovimentoCaixa
    movs = MovimentoCaixa.objects.filter(criado_em__date__range=(inicio, fim))
    por_forma = list(
        movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("forma_pagamento__nome").annotate(total=Sum("valor")).order_by("-total")
    )
    recebido = sum((m["total"] for m in por_forma), Decimal("0"))
    por_operador = (
        movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("sessao__operador__username").annotate(total=Sum("valor")).order_by("-total")
    )
    linhas = [[m["forma_pagamento__nome"] or "—", _rs(m["total"])] for m in por_forma]
    linhas += [[f"Operador: {m['sessao__operador__username']}", _rs(m["total"])]
               for m in por_operador]
    return {
        "kpis": [("Recebido no período", _rs(recebido)),
                 ("Nº de recebimentos", str(movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO).count()))],
        "colunas": ["Forma / operador", "Valor"],
        "linhas": linhas,
    }


def rel_faturamento_modulos(inicio, fim):
    """
    Faturamento por setor, separando ONDE o dinheiro é recebido:
      - "no caixa do setor" = venda paga na hora, entra na gaveta do próprio setor;
      - "lançado no quarto" = foi pro folio; quem recebe é a RECEPÇÃO (caixa Reservas).
    Fecha o ciclo do caixa por módulo: a soma da coluna "lançado no quarto" é
    exatamente o que a recepção coleta de outros setores (+ as diárias).
    """
    from apps.nucleo.models import modulo_ativo

    rng = (inicio, fim)
    linhas = []
    tot_caixa = tot_quarto = Decimal("0")

    def add(setor, no_caixa, no_quarto):
        nonlocal tot_caixa, tot_quarto
        linhas.append([setor, _rs(no_caixa), _rs(no_quarto), _rs(no_caixa + no_quarto)])
        tot_caixa += no_caixa
        tot_quarto += no_quarto

    # Hospedagem — as diárias são sempre folio (recebidas pela recepção).
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.models import LancamentoConta
        diarias = LancamentoConta.objects.filter(
            criado_em__date__range=rng, tipo=LancamentoConta.Tipo.DIARIA
        ).aggregate(t=Sum("valor"))["t"] or Decimal("0")
        add("Hospedagem (diárias)", Decimal("0"), diarias)

    # Loja — Venda.total é campo: dá para somar no banco.
    if modulo_ativo(Modulo.LOJA):
        from apps.loja.models import Venda
        v = Venda.objects.filter(criado_em__date__range=rng, status=Venda.Status.FECHADA)
        no_caixa = v.filter(destino=Venda.Destino.CAIXA).aggregate(t=Sum("total"))["t"] or Decimal("0")
        no_quarto = v.filter(destino=Venda.Destino.CONTA).aggregate(t=Sum("total"))["t"] or Decimal("0")
        add("Loja", no_caixa, no_quarto)

    # Restaurante — total é método; soma em Python.
    if modulo_ativo(Modulo.RESTAURANTE):
        from apps.restaurante.models import Comanda
        c1 = c2 = Decimal("0")
        for c in Comanda.objects.filter(
            fechada_em__date__range=rng, status=Comanda.Status.FECHADA
        ):
            if c.destino == Comanda.Destino.CAIXA:
                c1 += c.total()
            else:
                c2 += c.total()
        add("Restaurante", c1, c2)

    # Lavanderia — total é método; soma em Python.
    if modulo_ativo(Modulo.LAVANDERIA):
        from apps.lavanderia.models import OrdemLavanderia
        l1 = l2 = Decimal("0")
        for o in OrdemLavanderia.objects.filter(
            entregue_em__date__range=rng, status=OrdemLavanderia.Status.ENTREGUE
        ):
            if o.destino == OrdemLavanderia.Destino.CAIXA:
                l1 += o.total()
            else:
                l2 += o.total()
        add("Lavanderia", l1, l2)

    return {
        "kpis": [
            ("Faturamento total", _rs(tot_caixa + tot_quarto)),
            ("Recebido na gaveta do setor", _rs(tot_caixa)),
            ("Lançado nos quartos (recepção recebe)", _rs(tot_quarto)),
        ],
        "colunas": ["Setor", "No caixa do setor", "Lançado no quarto", "Total vendido"],
        "linhas": linhas,
    }


# ───────────────────────── Por módulo (individuais) ─────────────────────────

def rel_estoque_consumo(inicio, fim):
    """Curva de consumo (ABC) — saídas por produto no período."""
    from apps.nucleo.models import MovimentoEstoque
    saidas = (
        MovimentoEstoque.objects
        .filter(criado_em__date__range=(inicio, fim), quantidade__lt=0)
        .values("produto__nome").annotate(qtd=Sum("quantidade")).order_by("qtd")
    )
    linhas = [[s["produto__nome"], f"{-s['qtd']:.0f}"] for s in saidas]
    total = sum((-s["qtd"] for s in saidas), Decimal("0"))
    return {
        "kpis": [("Itens consumidos (qtd)", f"{total:.0f}"),
                 ("Produtos movimentados", str(len(linhas)))],
        "colunas": ["Produto", "Qtd. consumida"],
        "linhas": linhas,
    }


def rel_comercial(inicio, fim):
    """Funil de vendas — oportunidades criadas, conversão e funil em aberto por etapa."""
    from apps.comercial.services import relatorio_funil
    f = relatorio_funil(inicio, fim)
    linhas = [[e["etapa__nome"], str(e["n"]), _rs(e["valor"])] for e in f["por_etapa"]]
    return {
        "kpis": [("Oportunidades criadas", str(f["total"])),
                 ("Ganhas", str(f["ganhas"])), ("Perdidas", str(f["perdidas"])),
                 ("Taxa de conversão", f"{f['conversao']}%"),
                 ("Valor ganho", _rs(f["valor_ganho"]))],
        "colunas": ["Etapa (em aberto)", "Qtd.", "Valor no funil"],
        "linhas": linhas,
    }


def rel_reservas(inicio, fim):
    from apps.reservas.models import Reserva
    from apps.reservas.services import relatorio_reservas
    r = relatorio_reservas(inicio, fim)
    canais = dict(Reserva.Canal.choices)
    status = dict(Reserva.Status.choices)
    linhas = [["Canal: " + canais.get(k, k), str(v)] for k, v in r["por_canal"].items()]
    linhas += [["Status: " + status.get(k, k), str(v)] for k, v in r["por_status"].items()]
    return {
        "kpis": [("Reservas criadas", str(r["total"]))],
        "colunas": ["Categoria", "Quantidade"],
        "linhas": linhas,
    }


# Registro central. grupo = "Consolidados" | "Por módulo". `modulo` = exige ativo.
RELATORIOS = {
    "producao": {"nome": "Produção / Receita", "grupo": "Consolidados",
                 "builder": rel_producao, "modulo": Modulo.RESERVAS},
    "ocupacao": {"nome": "Ocupação & Diárias (ADR/RevPAR)", "grupo": "Consolidados",
                 "builder": rel_ocupacao, "modulo": Modulo.RESERVAS},
    "caixa": {"nome": "Caixa / Financeiro", "grupo": "Consolidados",
              "builder": rel_caixa, "modulo": None},
    "faturamento_modulos": {"nome": "Faturamento por setor (caixa × quarto)",
                            "grupo": "Consolidados",
                            "builder": rel_faturamento_modulos, "modulo": None},
    "estoque": {"nome": "Estoque — consumo (curva ABC)", "grupo": "Por módulo",
                "builder": rel_estoque_consumo, "modulo": Modulo.ESTOQUE},
    "reservas": {"nome": "Reservas — canal e status", "grupo": "Por módulo",
                 "builder": rel_reservas, "modulo": Modulo.RESERVAS},
    "comercial": {"nome": "Comercial — funil e conversão", "grupo": "Por módulo",
                  "builder": rel_comercial, "modulo": Modulo.COMERCIAL},
}


def disponiveis():
    """Relatórios cujo módulo está ativo (ou sem dependência), agrupados."""
    from apps.nucleo.models import modulo_ativo
    grupos = {}
    for chave, r in RELATORIOS.items():
        if r["modulo"] and not modulo_ativo(r["modulo"]):
            continue
        grupos.setdefault(r["grupo"], []).append({"chave": chave, "nome": r["nome"]})
    return grupos

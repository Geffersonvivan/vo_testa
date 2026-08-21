"""Estrutura física derivada: capacidade e frase de camas por quarto (UH).

Fonte única da lotação e da descrição de camas. Capacidade é composição de camas
da **unidade** (não número do tipo) e a frase é **gerada** da estrutura, nunca
digitada — senão site, recepção e governança passam a ter três versões da verdade.

Interface pública lida por site, mapa de quartos, governança e nova reserva:
`capacidade(uh)`, `descricao_camas(uh)`, `faixa_do_tipo(tipo_uh)`.
"""
from __future__ import annotations


def _eh_day_use(uh) -> bool:
    tipo = uh.tipo
    return tipo.modalidade == tipo.Modalidade.DAY_USE


def eh_duplo(uh) -> bool:
    """Quarto de dois cômodos (mais de uma posição de cama) — cobra acréscimo."""
    return uh.posicoes_cama.count() > 1


def _vazia() -> dict:
    return {
        "fixa": 0, "sofa_adultos": 0, "sofa_criancas": 0, "extras": 0,
        "maxima": 0, "maxima_criancas": 0, "idade_sofa": 15,
    }


def capacidade(uh) -> dict:
    """Composição de lotação de um quarto.

    `maxima` = só adultos; `maxima_criancas` = teto com as vagas de sofá ocupadas
    por crianças até `idade_sofa`. **Use `maxima_criancas` para disponibilidade** —
    é o número que o hóspede vê como "acomoda até N".
    """
    if _eh_day_use(uh):
        return _vazia()
    fixa = uh.posicoes_cama.count() * 2
    cfg = getattr(uh, "config", None)
    tem_sofa = bool(cfg and cfg.tem_sofa_cama)
    sofa_a = cfg.sofa_adultos if tem_sofa else 0
    sofa_c = cfg.sofa_criancas if tem_sofa else 0
    extras = cfg.max_colchoes_extras if cfg else 0
    idade = cfg.sofa_idade_maxima if cfg else 15
    return {
        "fixa": fixa,
        "sofa_adultos": sofa_a,
        "sofa_criancas": sofa_c,
        "extras": extras,
        "maxima": fixa + sofa_a + extras,
        "maxima_criancas": fixa + max(sofa_a, sofa_c) + extras,
        "idade_sofa": idade,
    }


def descricao_camas(uh) -> str:
    """Frase de camas gerada da estrutura (nunca de um campo de texto).

    Ex.: «Quarto 1 com 1 cama de casal · Quarto 2 com 1 cama de casal · sofá-cama
    para 1 adulto ou 2 crianças até 15 anos · até 2 colchões de solteiro extras».
    """
    if _eh_day_use(uh):
        return "Sem pernoite · acesso à estrutura no período"
    posicoes = list(uh.posicoes_cama.all())
    if not posicoes:
        return "Sem pernoite · acesso à estrutura no período"

    varias = len(posicoes) > 1
    partes = []
    for pos in posicoes:
        montagem = pos.get_montagem_padrao_display().lower()
        partes.append(f"{pos.nome} com {montagem}" if varias else montagem)

    cfg = getattr(uh, "config", None)
    if cfg and cfg.tem_sofa_cama:
        a = cfg.sofa_adultos
        c = cfg.sofa_criancas
        adulto = "adulto" if a == 1 else "adultos"
        crianca = "criança" if c == 1 else "crianças"
        partes.append(
            f"sofá-cama para {a} {adulto} ou {c} {crianca} "
            f"até {cfg.sofa_idade_maxima} anos"
        )
    if cfg and cfg.max_colchoes_extras:
        n = cfg.max_colchoes_extras
        if n > 1:
            partes.append(f"até {n} colchões de solteiro extras")
        else:
            partes.append("até 1 colchão de solteiro extra")
    return " · ".join(partes)


def extras_para(uh, pessoas: int) -> int:
    """Quantos colchões extras uma lotação exige nesta unidade.

    Incluídos sem cobrança: as camas fixas (posições × 2) e o sofá-cama (1 adulto
    ou 2 crianças). Só o que passa disso vira colchão extra, limitado ao máximo do
    quarto. Berço é gratuito e não entra aqui.
    """
    if _eh_day_use(uh):
        return 0
    cap = capacidade(uh)
    incluido = cap["fixa"] + cap["sofa_adultos"]
    return max(0, min(pessoas - incluido, cap["extras"]))


def faixa_do_tipo(tipo_uh) -> str:
    """Faixa de lotação das unidades de um tipo (usa `maxima_criancas`).

    "até N pessoas" quando todas iguais; "N a M pessoas" quando variam — assim o
    Quarto 03 não herda a promessa do Quarto 17.
    """
    caps = [
        capacidade(uh).get("maxima_criancas", 0)
        for uh in tipo_uh.uhs.all()
    ]
    caps = [c for c in caps if c]
    if not caps:
        return "—"
    menor, maior = min(caps), max(caps)
    if menor == maior:
        return f"até {maior} pessoas"
    return f"{menor} a {maior} pessoas"

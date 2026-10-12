"""Domínio do estoque de colchões — arranjo de camas por reserva (Fase 2).

Ver docs/Reservas/PLANO_ESTOQUE_COLCHOES.md. Aqui ficam as funções PURAS de arranjo
(sugerir, conferir estrutura, consumo de extra, presets) — reutilizáveis por recepção,
site, admin e API. A **validação dura** (raise) e a **trava global por noite** entram na
Fase 3 (apps/reservas/services.py).

Conceito (a regra do motor): **cada quarto tem suas camas FIXAS** — a base de casal
(2×casais_max colchões) é sempre daquele quarto e **nunca disputa estoque**. **35 posições
de casal = 70 colchões de solteiro fixos**: a posição vira 1 casal OU 2 solteiros — a
**montagem muda, a quantidade não**. **Só os 10 colchões EXTRAS** são compartilhados (pool
global): entram quando um quarto monta mais solteiros do que sua base. O **sofá-cama**
acomoda 1 adulto OU 2 crianças ≤15 e **não** consome colchão.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.nucleo.estrutura import _eh_day_use, camas_solteiro, casais_max


@dataclass(frozen=True)
class Arranjo:
    casais: int
    solteiros: int
    usa_sofa_cama: bool = False

    @property
    def camas(self) -> int:
        """Colchões ocupados pelas camas (casal = 2, solteiro = 1). Sofá não entra."""
        return 2 * self.casais + self.solteiros


def _cfg(uh):
    return getattr(uh, "config", None)


def configurado(uh) -> bool:
    """O quarto participa do modelo de colchões? Só quartos com posição de cama
    cadastrada (`casais_max > 0`). Day use e quartos ainda sem configuração de camas
    (ex.: cenários antigos) ficam de fora — não consomem nem disputam colchão."""
    return not _eh_day_use(uh) and casais_max(uh) > 0


def tem_sofa(uh) -> bool:
    cfg = _cfg(uh)
    return bool(cfg and cfg.tem_sofa_cama)


def capacidade_sofa(uh) -> dict:
    """Capacidade do sofá-cama: {adultos, criancas, idade}. Zerado se não tem sofá."""
    cfg = _cfg(uh)
    if not (cfg and cfg.tem_sofa_cama):
        return {"adultos": 0, "criancas": 0, "idade": 15}
    return {"adultos": cfg.sofa_adultos, "criancas": cfg.sofa_criancas,
            "idade": cfg.sofa_idade_maxima}


def consumo_extra(uh, casais: int, solteiros: int) -> int:
    """Colchões que ESTE arranjo tira do pool de extras (acima da base garantida)."""
    if not configurado(uh):
        return 0
    return max(0, (2 * casais + solteiros) - 2 * casais_max(uh))


def sugerir_arranjo(uh, adultos: int, criancas: int = 0) -> Arranjo:
    """Arranjo PADRÃO que acomoda (adultos+crianças) minimizando colchão extra:
    preenche casais (base, grátis) → sofá (grátis, p/ o excedente) → solteiros (extra).

    É só a sugestão inicial — o atendente pode alterar. Não valida estoque nem limite do
    quarto (isso é a validação); se o quarto não comportar, a sugestão satura e a
    validação acusa.
    """
    if not configurado(uh):
        return Arranjo(0, 0, False)
    pessoas = max(0, adultos) + max(0, criancas)
    cm = casais_max(uh)

    # Casais suficientes p/ sentar (arredonda p/ cima), limitado ao máximo do quarto.
    casais = min(cm, (pessoas + 1) // 2)
    falta = max(0, pessoas - 2 * casais)

    usa_sofa = False
    if falta > 0 and tem_sofa(uh):
        cap = capacidade_sofa(uh)
        # Prefere 2 crianças no sofá; senão 1 adulto.
        absorve = min(cap["criancas"], falta) if criancas >= 2 and falta >= 2 else min(cap["adultos"], falta)
        if absorve > 0:
            usa_sofa = True
            falta -= absorve

    solteiros = max(0, falta)
    return Arranjo(casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa)


def cabe_no_quarto(uh, casais: int, solteiros: int, usa_sofa_cama: bool,
                   adultos: int, criancas: int) -> list[str]:
    """Confere a ESTRUTURA do quarto (não o estoque global). Retorna lista de erros
    (vazia = ok). Pura — sem raise, sem tocar no banco de outras reservas.
    """
    erros: list[str] = []
    if not configurado(uh):
        return erros
    cm = casais_max(uh)
    cs = camas_solteiro(uh)
    cap = capacidade_sofa(uh)

    if casais > cm:
        erros.append(f"{casais} casais excede o máximo do quarto ({cm}).")
    if (2 * casais + solteiros) > cs:
        erros.append(f"{2 * casais + solteiros} camas excede o quarto ({cs} de solteiro).")
    if usa_sofa_cama and not tem_sofa(uh):
        erros.append("Este quarto não tem sofá-cama.")

    # Capacidade de pessoas: camas + sofá (1 adulto OU 2 crianças).
    sofa = max(cap["adultos"], cap["criancas"]) if usa_sofa_cama else 0
    if (adultos + criancas) > (2 * casais + solteiros) + sofa:
        erros.append(
            f"{adultos + criancas} hóspedes não cabem em "
            f"{2 * casais + solteiros} camas" + (" + sofá" if usa_sofa_cama else "") + "."
        )
    return erros


def presets(uh) -> list[dict]:
    """Presets de arranjo para a interface (base só casais · completa · só solteiros).
    Combinações intermediárias seguem válidas pela regra geral."""
    if not configurado(uh):
        return []
    cm = casais_max(uh)
    cs = camas_solteiro(uh)
    opcoes = [
        {"rotulo": "Base (só casais)", "casais": cm, "solteiros": 0},
        {"rotulo": "Só solteiros", "casais": 0, "solteiros": cs},
    ]
    completa_solteiros = cs - 2 * cm  # casais no máximo + extras na sala/quarto
    if completa_solteiros > 0:
        opcoes.insert(1, {"rotulo": "Completa (casais + extras)",
                          "casais": cm, "solteiros": completa_solteiros})
    for o in opcoes:
        o["colchoes_extra"] = consumo_extra(uh, o["casais"], o["solteiros"])
    return opcoes

"""Motor de preço ao hóspede — Manual de Vendas §2 + taxas (Fase 6).

Fonte única do preço itemizado, reutilizada por recepção, site, funil (Comercial) e
pelo lançamento no check-in. Regras (docs/Descritivo_Quartos/Parametros_CRM.md §2):

- base = diária de 2 pax da categoria × temporada (motor de tarifa já existente).
- adultos (16+): 1 sozinho → 70% da base (single); 2+ → base + (N−2)×pessoa_adicional.
- crianças: ≤5 não pagam · 6-15 pagam metade da pessoa_adicional · 16+ entram em adultos.
- **colchão extra NÃO cobra** — virou só disponibilidade (a pessoa extra paga via adicional).

Taxas (por fora, exibidas embutidas no total, cada uma desmarcável):
- ISS: acréscimo de `PRECO_ISS_ALIQUOTA`% sobre a hospedagem (após o −12%).
- Taxa de turismo: `PRECO_TAXA_TURISMO_DIARIA` × nº de diárias (por reserva, não por pessoa).

Day use: preço = `tipo.preco_day_use` × pessoas pagantes (adultos + crianças 6-15; ≤5
não pagam); 1 diária para a taxa de turismo; ISS e turismo incidem igual.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.nucleo.models import TipoUH

CENTAVO = Decimal("0.01")


def _q(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _cfg(nome: str) -> Decimal:
    return Decimal(str(getattr(settings, nome)))


def taxas(hospedagem: Decimal, *, cobra_iss: bool = True,
          cobra_taxa_turismo: bool = True, diarias: int = 1) -> dict:
    """ISS (% sobre a hospedagem) + taxa de turismo (valor fixo × nº de diárias).
    **Fonte única** das taxas — usada pela cotação, pelo lançamento no check-in
    (`ContaHospedagem.lancar_taxas`) e pelo resumo do site, para não divergirem.
    Valores vêm da `ConfiguracaoReservas` (editáveis na Tabela de Preços).
    O mesmo cálculo está espelhado no JS de `resumo.html` (toggles ao vivo)."""
    from apps.nucleo.models import ConfiguracaoReservas
    cfg = ConfiguracaoReservas.carregar()
    iss_aliq = cfg.iss_aliquota
    taxa_un = cfg.taxa_turismo_diaria
    return {
        "iss_aliquota": iss_aliq,
        "iss": _q(hospedagem * iss_aliq / 100) if cobra_iss else Decimal("0.00"),
        "taxa_turismo_unitaria": taxa_un,
        "taxa_turismo": _q(taxa_un * diarias) if cobra_taxa_turismo else Decimal("0.00"),
    }


def diaria_por_pessoas(base_noite: Decimal, pessoa_adicional: Decimal, *,
                       adultos: int, criancas_6_15: int, meia: Decimal = None) -> Decimal:
    """Diária de uma noite ajustada pela lotação (Manual §2). `base_noite` = diária de
    2 pax já resolvida. `meia` = valor da criança 6-15 (vazio = metade do adicional).
    O fator do hóspede sozinho vem da `ConfiguracaoReservas`."""
    from apps.nucleo.models import ConfiguracaoReservas

    if meia is None:
        meia = pessoa_adicional / 2
    if adultos <= 1 and criancas_6_15 <= 0:
        valor = base_noite * ConfiguracaoReservas.carregar().single_fator  # hóspede sozinho
    else:
        extra_adultos = max(0, adultos - 2)
        valor = (base_noite
                 + extra_adultos * pessoa_adicional
                 + criancas_6_15 * meia)                           # 6-15 = meia
    return _q(valor)


def cotacao(*, uh=None, tipo=None, checkin: date, checkout: date,
            adultos: int = 2, criancas_0_5: int = 0, criancas_6_15: int = 0,
            cobra_iss: bool = True, cobra_taxa_turismo: bool = True,
            nao_reembolsavel: bool = False) -> dict:
    """Cotação itemizada: diárias (por pessoa) + ISS + taxa de turismo. Passe `uh`
    (venda por unidade) OU `tipo` (venda por tipo). `nao_reembolsavel` aplica o
    desconto pré-pago sobre a hospedagem (antes das taxas). Pura — não grava."""
    from apps.nucleo.models import ConfiguracaoReservas
    from apps.reservas.services import (
        preco_unidade_noite,
        tarifa_day_use,
        tarifa_do_dia,
    )

    o_tipo = tipo or (uh.tipo if uh else None)
    if o_tipo is None:
        raise ValidationError("Informe a unidade (uh) ou o tipo para cotar.")

    adultos = max(0, int(adultos))
    criancas_6_15 = max(0, int(criancas_6_15))
    criancas_0_5 = max(0, int(criancas_0_5))
    pa = o_tipo.pessoa_adicional or Decimal("0.00")
    noites = (checkout - checkin).days

    if o_tipo.modalidade == TipoUH.Modalidade.DAY_USE:
        du = tarifa_day_use(checkin)                               # (adulto, meia) × temporada
        if du:
            v_ad, v_meia = du
        else:                                                      # fallback: preço do tipo
            v_ad = o_tipo.preco_day_use or Decimal("0.00")
            v_meia = v_ad / 2
        hospedagem = _q(adultos * v_ad + criancas_6_15 * v_meia)   # ≤5 não pagam
        diarias = [{"dia": checkin, "valor": hospedagem}]
        diarias_qtd = 1
    else:
        if noites <= 0:
            raise ValidationError("Período inválido: a saída deve ser após a entrada.")
        diarias = []
        for n in range(noites):
            dia = checkin + timedelta(days=n)
            # Venda por unidade: base, pessoa-adicional e meia por noite (variam por
            # temporada/feriado). Venda por tipo: base do tipo + adicional do tipo.
            if uh:
                base_noite, pa_noite, meia_noite = preco_unidade_noite(uh, dia)
            else:
                base_noite, pa_noite, meia_noite = tarifa_do_dia(o_tipo, dia), pa, pa / 2
            diarias.append({"dia": dia, "valor": diaria_por_pessoas(
                base_noite, pa_noite, adultos=adultos,
                criancas_6_15=criancas_6_15, meia=meia_noite)})
        hospedagem = sum((d["valor"] for d in diarias), Decimal("0.00"))
        diarias_qtd = noites

    # Tarifa não-reembolsável: desconto pré-pago sobre a hospedagem (antes das taxas).
    desconto_nr = Decimal("0.00")
    if nao_reembolsavel:
        pct = ConfiguracaoReservas.carregar().nao_reembolsavel_desconto
        desconto_nr = _q(hospedagem * pct)
        hospedagem = _q(hospedagem - desconto_nr)

    t = taxas(hospedagem, cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
              diarias=diarias_qtd)
    total = hospedagem + t["iss"] + t["taxa_turismo"]
    media = _q(hospedagem / diarias_qtd) if diarias_qtd else Decimal("0.00")

    return {
        "diarias": diarias,
        "diarias_qtd": diarias_qtd,
        "noites": noites,
        "hospedagem": hospedagem,
        "media_noite": media,
        "cobra_iss": cobra_iss,
        "cobra_taxa_turismo": cobra_taxa_turismo,
        "nao_reembolsavel": nao_reembolsavel,
        "desconto_nao_reembolsavel": desconto_nr,
        "total": total,
        **t,
    }

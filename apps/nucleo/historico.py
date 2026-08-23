"""
Histórico do funcionário (Fase 1) — read-only, montado do que já temos:
  - tempo de casa: cálculo sobre a admissão;
  - progressão salarial e movimentações (cargo/setor): lidas da Trilha de auditoria
    (já registramos `editar Funcionario: salario/cargo/setor [antigo→novo]`);
  - presença: eventos login/logout na trilha (últimos 30 dias).

Nada de model novo. Dados sensíveis (salário) → a view só monta para gerência.
Fase 2 (dias/horas/ausências via Escala; produtividade por papel) fica de fora daqui.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone


def _dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def tempo_de_casa(admissao):
    """Texto 'X anos, Y meses' desde a admissão (ou None)."""
    if not admissao:
        return None
    hoje = timezone.localdate()
    meses = (hoje.year - admissao.year) * 12 + (hoje.month - admissao.month)
    if hoje.day < admissao.day:
        meses -= 1
    meses = max(0, meses)
    anos, m = divmod(meses, 12)
    partes = []
    if anos:
        partes.append(f"{anos} ano{'s' if anos > 1 else ''}")
    if m:
        partes.append(f"{m} {'meses' if m > 1 else 'mês'}")
    return ", ".join(partes) or "menos de 1 mês"


def _trilha_do_funcionario(func):
    from apps.nucleo.models import TrilhaAuditoria
    return (
        TrilhaAuditoria.objects
        .filter(alvo="Funcionario", alvo_id=str(func.pk))
        .order_by("criado_em")
    )


def progressao_salarial(func):
    """Lista {data, valor, delta_pct, motivo} a partir dos registros de salário na trilha."""
    itens, anterior = [], None
    for r in _trilha_do_funcionario(func):
        d = r.detalhe or {}
        valor, motivo = None, ""
        if r.acao == "criar":
            valor = (d.get("valores") or {}).get("salario")
            motivo = "admissão"
        elif r.acao == "editar":
            alt = (d.get("alteracoes") or {}).get("salario")
            if alt:
                valor = alt[1]
        valor = _dec(valor)
        if valor is None or valor <= 0:
            continue
        delta = None
        if anterior and anterior > 0:
            delta = round(float((valor - anterior) / anterior * 100), 1)
        itens.append({"data": r.criado_em, "valor": valor, "delta": delta, "motivo": motivo})
        anterior = valor
    return itens


def movimentacoes(func):
    """Marcos do funcionário (admissão + mudanças de cargo/setor/salário) da trilha."""
    ROTULOS = {"cargo": "Cargo", "setor": "Setor", "salario": "Salário"}
    movs = []
    for r in _trilha_do_funcionario(func):
        d = r.detalhe or {}
        if r.acao == "criar":
            movs.append({"data": r.criado_em, "texto": f"Cadastrado como {func.cargo}"})
        elif r.acao == "editar":
            for campo, rot in ROTULOS.items():
                alt = (d.get("alteracoes") or {}).get(campo)
                if alt:
                    a, b = (alt + [None, None])[:2]
                    movs.append({"data": r.criado_em, "texto": f"{rot}: {a or '—'} → {b or '—'}"})
    return movs


def presenca(func):
    """Dias com acesso nos últimos 30 dias (proxy de presença), da trilha login/logout."""
    if not func.usuario_id:
        return None
    from apps.nucleo.models import TrilhaAuditoria
    desde = timezone.now() - timedelta(days=30)
    dias = set(
        TrilhaAuditoria.objects
        .filter(usuario_id=func.usuario_id, acao="login", criado_em__gte=desde)
        .values_list("criado_em__date", flat=True)
    )
    return {"dias_com_acesso": len(dias)}


def historico_funcionario(func):
    return {
        "admissao": func.admissao,
        "tempo_de_casa": tempo_de_casa(func.admissao),
        "progressao": progressao_salarial(func),
        "movimentacoes": movimentacoes(func),
        "presenca": presenca(func),
    }

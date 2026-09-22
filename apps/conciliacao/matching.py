"""Motor de conciliação — funções PURAS (sem Django/DB), 100% testáveis.

Duas conciliações independentes:
  1. **NSU (cartão):** casa a transação da adquirente (SafraPay, por NSU) com o
     recebimento de cartão no caixa (`MovimentoCaixa.autorizacao`). Sinaliza a
     divergência de valor (bruto da adquirente − valor cobrado no caixa).
  2. **Valor+data (banco):** casa uma linha do extrato bancário (OFX) com um registro
     do CRM (recebimento em dinheiro/Pix, conta paga) por **valor exato + janela de data**.

Nada aqui altera dados — só produz pareamentos. A camada de models/services aplica o
resultado (vínculo, status, fila de pendências). Sinal do valor no extrato: **> 0 = crédito
(entrada), < 0 = débito (saída)**. Nos itens do CRM o valor é sempre positivo e `entrada`
define o sentido.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


# ── Entradas ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ItemExtrato:
    """Uma linha do extrato bancário. valor > 0 = crédito; valor < 0 = débito."""
    id: object
    data: date
    valor: Decimal
    descricao: str = ""


@dataclass(frozen=True)
class ItemCrm:
    """Registro do CRM a conciliar. `valor` sempre POSITIVO; `entrada` dá o sentido."""
    id: object
    data: date
    valor: Decimal
    entrada: bool  # True = recebimento (crédito no banco) · False = pagamento (débito)


@dataclass(frozen=True)
class ItemCartao:
    """Transação da adquirente (SafraPay), identificada por NSU."""
    id: object
    nsu: str
    bruto: Decimal
    liquido: Decimal
    data_venda: date


@dataclass(frozen=True)
class ItemCaixaCartao:
    """Recebimento em cartão no caixa (MovimentoCaixa): traz o NSU e o valor cobrado."""
    id: object
    nsu: str
    valor: Decimal


# ── Saídas ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Par:
    extrato_id: object
    crm_id: object
    confianca: str  # "exata" (mesma data) | "provavel" (dentro da janela)


@dataclass(frozen=True)
class ParNsu:
    cartao_id: object
    caixa_id: object
    divergencia_valor: Decimal  # bruto (adquirente) − valor (caixa); 0 = bate


@dataclass
class ResultadoBanco:
    pares: list = field(default_factory=list)
    sem_par_extrato: list = field(default_factory=list)
    sem_par_crm: list = field(default_factory=list)


@dataclass
class ResultadoNsu:
    pares: list = field(default_factory=list)
    sem_par_cartao: list = field(default_factory=list)
    sem_par_caixa: list = field(default_factory=list)


# ── Motor ───────────────────────────────────────────────────────────────────
def casar_por_valor_data(extrato, crm, janela_dias: int = 2) -> ResultadoBanco:
    """Casa linhas do extrato com registros do CRM por |valor| igual + data próxima.

    Regras:
      - **sentido** tem de bater: crédito (valor > 0) só casa com `entrada=True`;
        débito (valor < 0) só com `entrada=False`;
      - **valor** absoluto exatamente igual (centavos);
      - prioriza a **mesma data** ("exata"); depois a menor diferença de dias dentro da
        janela ("provavel");
      - **1:1** — cada registro do CRM casa no máximo uma vez (guloso, do mais próximo
        em data para o mais distante).
    """
    pares: list[Par] = []
    usados: set[int] = set()  # índices de `crm` já pareados
    sem_par_extrato: list = []
    for e in extrato:
        entrada_esperada = e.valor > 0
        alvo = abs(e.valor)
        candidatos = [
            (i, c)
            for i, c in enumerate(crm)
            if i not in usados
            and c.entrada == entrada_esperada
            and c.valor == alvo
            and abs((c.data - e.data).days) <= janela_dias
        ]
        if not candidatos:
            sem_par_extrato.append(e)
            continue
        i, melhor = min(candidatos, key=lambda ic: abs((ic[1].data - e.data).days))
        usados.add(i)
        confianca = "exata" if melhor.data == e.data else "provavel"
        pares.append(Par(extrato_id=e.id, crm_id=melhor.id, confianca=confianca))
    sem_par_crm = [c for i, c in enumerate(crm) if i not in usados]
    return ResultadoBanco(pares=pares, sem_par_extrato=sem_par_extrato, sem_par_crm=sem_par_crm)


def casar_por_nsu(cartao, caixa) -> ResultadoNsu:
    """Casa transações da adquirente com recebimentos de cartão no caixa pelo NSU.

    NSU igual → par, com `divergencia_valor = bruto_adquirente − valor_caixa` (0 = bate).
    NSU vazio nunca casa. O que sobra dos dois lados vira fila de pendência.
    """
    caixa_por_nsu: dict[str, list[int]] = {}
    for i, k in enumerate(caixa):
        if k.nsu:
            caixa_por_nsu.setdefault(k.nsu, []).append(i)

    pares: list[ParNsu] = []
    usados: set[int] = set()
    sem_par_cartao: list = []
    for t in cartao:
        indice = None
        if t.nsu:
            for i in caixa_por_nsu.get(t.nsu, []):
                if i not in usados:
                    indice = i
                    break
        if indice is None:
            sem_par_cartao.append(t)
            continue
        usados.add(indice)
        k = caixa[indice]
        pares.append(ParNsu(cartao_id=t.id, caixa_id=k.id,
                            divergencia_valor=t.bruto - k.valor))
    sem_par_caixa = [k for i, k in enumerate(caixa) if i not in usados]
    return ResultadoNsu(pares=pares, sem_par_cartao=sem_par_cartao, sem_par_caixa=sem_par_caixa)

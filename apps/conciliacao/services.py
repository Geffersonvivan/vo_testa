"""Serviços da conciliação: importar arquivos e casar com os dados reais do CRM.

Fica **entre** os arquivos importados e o motor puro (`matching.py`): monta os itens a
partir dos models, roda o pareamento e persiste o vínculo/status. Não altera nenhum
movimento do CRM — só grava a conciliação (e, no cartão, lança a taxa como despesa para
o líquido bater no extrato).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.nucleo.models.financeiro import (
    CENTRO_NUCLEO,
    CategoriaFinanceira,
    ContaPagarReceber,
    FormaPagamento,
    LancamentoFinanceiro,
    MovimentoCaixa,
)

from .matching import (
    ItemCaixaCartao,
    ItemCartao,
    ItemCrm,
    ItemExtrato,
    casar_por_nsu,
    casar_por_valor_data,
)
from .models import (
    ExtratoBancario,
    LancamentoExtrato,
    LoteCartao,
    TransacaoCartao,
)


# ── Parsing de OFX (sem dependência externa) ─────────────────────────────────
_TRN_FECHADO = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)


def _blocos_stmttrn(texto: str) -> list[str]:
    fechados = _TRN_FECHADO.findall(texto)
    if fechados:
        return fechados
    # OFX 1.x (SGML sem tags de fechamento): quebra por <STMTTRN>
    partes = re.split(r"<STMTTRN>", texto, flags=re.IGNORECASE)[1:]
    blocos = []
    for p in partes:
        corte = re.split(r"</STMTTRN>|<STMTTRN>|</BANKTRANLIST>", p, flags=re.IGNORECASE)[0]
        blocos.append(corte)
    return blocos


def _tag(bloco: str, tag: str) -> str:
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse_ofx(texto: str) -> list[dict]:
    linhas = []
    for bloco in _blocos_stmttrn(texto):
        dt = _tag(bloco, "DTPOSTED")[:8]
        val = _tag(bloco, "TRNAMT").replace(",", ".")
        if not dt or not val:
            continue
        try:
            data = date(int(dt[0:4]), int(dt[4:6]), int(dt[6:8]))
            valor = Decimal(val)
        except (ValueError, InvalidOperation):
            continue
        linhas.append({
            "data": data, "valor": valor,
            "fitid": _tag(bloco, "FITID"),
            "descricao": _tag(bloco, "NAME") or _tag(bloco, "MEMO"),
        })
    return linhas


@transaction.atomic
def importar_ofx(*, conteudo, banco="Banco Safra", conta="", arquivo_nome="", usuario=None):
    """Importa um extrato OFX. Dedupe por FITID na mesma conta (reimportar não duplica)."""
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("latin-1", "replace")
    linhas = _parse_ofx(conteudo)
    if not linhas:
        raise ValidationError("Nenhuma transação encontrada no arquivo OFX.")
    datas = [x["data"] for x in linhas]
    extrato = ExtratoBancario.objects.create(
        banco=banco, conta=conta, arquivo_nome=arquivo_nome,
        periodo_inicio=min(datas), periodo_fim=max(datas), importado_por=usuario,
    )
    existentes = set()
    if conta:
        existentes = set(
            LancamentoExtrato.objects.filter(extrato__conta=conta)
            .exclude(fitid="").values_list("fitid", flat=True)
        )
    novos = ignorados = 0
    for x in linhas:
        if x["fitid"] and x["fitid"] in existentes:
            ignorados += 1
            continue
        LancamentoExtrato.objects.create(
            extrato=extrato, data=x["data"], valor=x["valor"],
            descricao=x["descricao"], fitid=x["fitid"],
        )
        novos += 1
        if x["fitid"]:
            existentes.add(x["fitid"])
    return {"extrato": extrato, "novos": novos, "ignorados": ignorados}


# ── Parsing do CSV da adquirente (SafraPay) ──────────────────────────────────
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


_COLUNAS = {
    "nsu": ["nsu", "nsu/doc", "numero nsu", "doc"],
    "bruto": ["valor bruto", "bruto", "valor da venda", "valor venda", "valor"],
    "taxa": ["taxa", "valor taxa", "valor mdr", "mdr", "desconto"],
    "liquido": ["valor liquido", "liquido", "valor a receber", "liquido a receber"],
    "data_venda": ["data da venda", "data venda", "data"],
    "data_liquidacao": ["data da liquidacao", "data liquidacao", "previsao de pagamento",
                         "data pagamento", "data de pagamento"],
    "bandeira": ["bandeira"],
    "autorizacao": ["autorizacao", "codigo de autorizacao", "cod autorizacao"],
}


def _valor(s) -> Decimal | None:
    s = (s or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:  # BR: 1.234,56 → 1234.56
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _data(s) -> date | None:
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@transaction.atomic
def importar_cartao_csv(*, conteudo, arquivo_nome="", adquirente="SafraPay", usuario=None):
    """Importa o CSV de vendas da adquirente. Mapeia colunas por nome (tolerante a acento)."""
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("latin-1", "replace")
    amostra = conteudo[:2000]
    delim = ";" if amostra.count(";") >= amostra.count(",") else ","
    reader = csv.DictReader(io.StringIO(conteudo), delimiter=delim)
    headers = {_norm(h): h for h in (reader.fieldnames or [])}
    mapa = {}
    for campo, aliases in _COLUNAS.items():
        for a in aliases:
            if a in headers:
                mapa[campo] = headers[a]
                break
    faltando = [c for c in ("nsu", "bruto") if c not in mapa]
    if faltando:
        raise ValidationError(
            f"CSV sem as colunas obrigatórias {faltando}. Cabeçalhos lidos: {reader.fieldnames}")

    lote = LoteCartao.objects.create(
        adquirente=adquirente, arquivo_nome=arquivo_nome, importado_por=usuario)
    novos = 0
    for row in reader:
        nsu = (row.get(mapa["nsu"]) or "").strip()
        bruto = _valor(row.get(mapa["bruto"]))
        if not nsu or bruto is None:
            continue
        liquido = _valor(row.get(mapa["liquido"])) if "liquido" in mapa else None
        taxa = _valor(row.get(mapa["taxa"])) if "taxa" in mapa else None
        if liquido is None:
            liquido = bruto - (taxa or Decimal("0"))
        if taxa is None:
            taxa = bruto - liquido
        TransacaoCartao.objects.create(
            lote=lote, nsu=nsu, bruto=bruto, taxa=taxa, liquido=liquido,
            data_venda=(_data(row.get(mapa["data_venda"])) if "data_venda" in mapa else None)
            or timezone.localdate(),
            data_liquidacao=_data(row.get(mapa["data_liquidacao"])) if "data_liquidacao" in mapa else None,
            bandeira=((row.get(mapa["bandeira"]) or "").strip() if "bandeira" in mapa else ""),
            autorizacao=((row.get(mapa["autorizacao"]) or "").strip() if "autorizacao" in mapa else ""),
        )
        novos += 1
    return {"lote": lote, "novos": novos}


# ── Conciliação bancária (extrato × CRM) ─────────────────────────────────────
def _crm_usados():
    mc = set(LancamentoExtrato.objects.exclude(movimento_caixa=None)
             .values_list("movimento_caixa_id", flat=True))
    mc |= set(TransacaoCartao.objects.exclude(movimento_caixa=None)
              .values_list("movimento_caixa_id", flat=True))
    cpr = set(LancamentoExtrato.objects.exclude(conta=None).values_list("conta_id", flat=True))
    return mc, cpr


@transaction.atomic
def conciliar_banco(*, extrato=None, janela_dias=2, usuario=None):
    """Casa linhas pendentes do extrato com recebimentos de caixa e contas baixadas."""
    qs = LancamentoExtrato.objects.filter(status=LancamentoExtrato.Status.PENDENTE)
    if extrato:
        qs = qs.filter(extrato=extrato)
    itens_ext = [ItemExtrato(id=x.id, data=x.data, valor=x.valor, descricao=x.descricao)
                 for x in qs]

    mc_usados, cpr_usados = _crm_usados()
    crm = []
    for m in (MovimentoCaixa.objects
              .filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
              .exclude(id__in=mc_usados)
              .select_related(None)):
        crm.append(ItemCrm(id=("mc", m.id), data=m.criado_em.date(), valor=m.valor, entrada=True))
    for c in (ContaPagarReceber.objects
              .filter(status=ContaPagarReceber.Status.BAIXADA, baixada_em__isnull=False)
              .exclude(id__in=cpr_usados)):
        crm.append(ItemCrm(id=("cpr", c.id), data=c.baixada_em, valor=c.valor,
                           entrada=(c.tipo == ContaPagarReceber.Tipo.RECEBER)))

    resultado = casar_por_valor_data(itens_ext, crm, janela_dias=janela_dias)
    agora = timezone.now()
    for par in resultado.pares:
        lanc = LancamentoExtrato.objects.get(id=par.extrato_id)
        origem, pk = par.crm_id
        if origem == "mc":
            lanc.movimento_caixa_id = pk
        else:
            lanc.conta_id = pk
        lanc.status = LancamentoExtrato.Status.CONCILIADO
        lanc.confianca = par.confianca
        lanc.conciliado_em = agora
        lanc.conciliado_por = usuario
        lanc.save(update_fields=["movimento_caixa", "conta", "status", "confianca",
                                 "conciliado_em", "conciliado_por"])
    return {"conciliados": len(resultado.pares), "pendentes": len(resultado.sem_par_extrato)}


# ── Conciliação de cartão (adquirente × caixa, por NSU) ──────────────────────
@transaction.atomic
def conciliar_cartao(*, lote=None, usuario=None):
    """Casa transações pendentes com recebimentos de cartão no caixa (por NSU) e lança a taxa."""
    qs = TransacaoCartao.objects.filter(status=TransacaoCartao.Status.PENDENTE)
    if lote:
        qs = qs.filter(lote=lote)
    cartao = [ItemCartao(id=t.id, nsu=t.nsu, bruto=t.bruto, liquido=t.liquido,
                         data_venda=t.data_venda) for t in qs]

    mc_usados = set(TransacaoCartao.objects.exclude(movimento_caixa=None)
                    .values_list("movimento_caixa_id", flat=True))
    formas = [FormaPagamento.Tipo.CARTAO_CREDITO, FormaPagamento.Tipo.CARTAO_DEBITO]
    caixa = [
        ItemCaixaCartao(id=m.id, nsu=m.autorizacao, valor=m.valor)
        for m in (MovimentoCaixa.objects
                  .filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO, forma_pagamento__tipo__in=formas)
                  .exclude(autorizacao="").exclude(id__in=mc_usados))
    ]

    resultado = casar_por_nsu(cartao, caixa)
    agora = timezone.now()
    for par in resultado.pares:
        t = TransacaoCartao.objects.get(id=par.cartao_id)
        t.movimento_caixa_id = par.caixa_id
        t.divergencia_valor = par.divergencia_valor
        t.status = TransacaoCartao.Status.CONCILIADO
        t.conciliado_em = agora
        t.conciliado_por = usuario
        _lancar_taxa(t, usuario)
        t.save()
    return {"conciliados": len(resultado.pares), "sem_venda": len(resultado.sem_par_cartao)}


def _lancar_taxa(transacao, usuario):
    """Lança a taxa do cartão (bruto − líquido) como despesa, para o líquido bater no banco."""
    taxa = transacao.bruto - transacao.liquido
    if taxa > 0 and transacao.lancamento_taxa_id is None and usuario is not None:
        cat, _ = CategoriaFinanceira.objects.get_or_create(
            nome="Taxa de cartão", tipo=CategoriaFinanceira.Tipo.DESPESA)
        transacao.lancamento_taxa = LancamentoFinanceiro.objects.create(
            tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat, centro=CENTRO_NUCLEO,
            descricao=f"Taxa de cartão — NSU {transacao.nsu}", valor=taxa,
            data=transacao.data_liquidacao or transacao.data_venda, criado_por=usuario,
        )


# ── Conciliação manual (casar o que sobrou, ignorar, desfazer) ───────────────
@dataclass(frozen=True)
class Candidato:
    origem: str  # "mc" (movimento de caixa) | "cpr" (conta a pagar/receber)
    id: int
    rotulo: str
    valor: Decimal
    data: date
    exato: bool  # bate valor (banco) ou NSU (cartão) — sobe no topo da lista


def candidatos_para_extrato(lancamento, limite: int = 20) -> list[Candidato]:
    """Registros do CRM livres que o operador pode casar com uma linha do extrato.

    Crédito → recebimentos de caixa + contas a receber baixadas;
    débito → contas a pagar baixadas. Ordena: valor exato primeiro, depois data próxima.
    """
    mc_usados, cpr_usados = _crm_usados()
    alvo = abs(lancamento.valor)
    cands: list[Candidato] = []
    if lancamento.valor > 0:
        for m in (MovimentoCaixa.objects
                  .filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO).exclude(id__in=mc_usados)):
            cands.append(Candidato("mc", m.id, f"Caixa: {m.descricao}", m.valor,
                                   m.criado_em.date(), m.valor == alvo))
        for c in (ContaPagarReceber.objects
                  .filter(tipo=ContaPagarReceber.Tipo.RECEBER,
                          status=ContaPagarReceber.Status.BAIXADA).exclude(id__in=cpr_usados)):
            cands.append(Candidato("cpr", c.id, f"A receber: {c.descricao}", c.valor,
                                   c.baixada_em or c.vencimento, c.valor == alvo))
    else:
        for c in (ContaPagarReceber.objects
                  .filter(tipo=ContaPagarReceber.Tipo.PAGAR,
                          status=ContaPagarReceber.Status.BAIXADA).exclude(id__in=cpr_usados)):
            cands.append(Candidato("cpr", c.id, f"A pagar: {c.descricao}", c.valor,
                                   c.baixada_em or c.vencimento, c.valor == alvo))
    cands.sort(key=lambda x: (not x.exato, abs((x.data - lancamento.data).days), abs(x.valor - alvo)))
    return cands[:limite]


@transaction.atomic
def conciliar_manual_extrato(*, lancamento, origem, pk, usuario=None):
    """Casa manualmente uma linha do extrato com um registro do CRM escolhido."""
    mc_usados, cpr_usados = _crm_usados()
    if origem == "mc":
        if int(pk) in mc_usados:
            raise ValidationError("Esse recebimento de caixa já foi conciliado.")
        lancamento.movimento_caixa_id = int(pk)
        lancamento.conta = None
    elif origem == "cpr":
        if int(pk) in cpr_usados:
            raise ValidationError("Essa conta já foi conciliada.")
        lancamento.conta_id = int(pk)
        lancamento.movimento_caixa = None
    else:
        raise ValidationError("Origem inválida.")
    lancamento.status = LancamentoExtrato.Status.CONCILIADO
    lancamento.confianca = "manual"
    lancamento.conciliado_em = timezone.now()
    lancamento.conciliado_por = usuario
    lancamento.save()
    return lancamento


@transaction.atomic
def ignorar_extrato(*, lancamento, usuario=None):
    """Marca a linha como ignorada (tarifa, transferência entre contas próprias, etc.)."""
    lancamento.status = LancamentoExtrato.Status.IGNORADO
    lancamento.movimento_caixa = None
    lancamento.conta = None
    lancamento.confianca = ""
    lancamento.conciliado_em = timezone.now()
    lancamento.conciliado_por = usuario
    lancamento.save()
    return lancamento


@transaction.atomic
def desfazer_extrato(*, lancamento, usuario=None):
    """Volta a linha para pendente, desfazendo o vínculo."""
    lancamento.status = LancamentoExtrato.Status.PENDENTE
    lancamento.movimento_caixa = None
    lancamento.conta = None
    lancamento.confianca = ""
    lancamento.conciliado_em = None
    lancamento.conciliado_por = None
    lancamento.save()
    return lancamento


def candidatos_para_cartao(transacao, limite: int = 20) -> list[Candidato]:
    """Recebimentos de cartão no caixa livres. NSU igual sobe ao topo (`exato`)."""
    usados = set(TransacaoCartao.objects.exclude(movimento_caixa=None)
                 .values_list("movimento_caixa_id", flat=True))
    formas = [FormaPagamento.Tipo.CARTAO_CREDITO, FormaPagamento.Tipo.CARTAO_DEBITO]
    cands: list[Candidato] = []
    for m in (MovimentoCaixa.objects
              .filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO, forma_pagamento__tipo__in=formas)
              .exclude(id__in=usados)):
        cands.append(Candidato("mc", m.id, f"{m.descricao} — NSU {m.autorizacao or '—'}",
                               m.valor, m.criado_em.date(), m.autorizacao == transacao.nsu))
    cands.sort(key=lambda x: (not x.exato, abs(x.valor - transacao.bruto)))
    return cands[:limite]


@transaction.atomic
def conciliar_manual_cartao(*, transacao, mc_id, usuario=None):
    """Casa manualmente uma transação de cartão com um recebimento de caixa e lança a taxa."""
    usados = set(TransacaoCartao.objects.exclude(movimento_caixa=None)
                 .values_list("movimento_caixa_id", flat=True))
    if int(mc_id) in usados:
        raise ValidationError("Esse recebimento de cartão já foi conciliado.")
    mc = MovimentoCaixa.objects.get(id=int(mc_id))
    transacao.movimento_caixa = mc
    transacao.divergencia_valor = transacao.bruto - mc.valor
    transacao.status = TransacaoCartao.Status.CONCILIADO
    transacao.conciliado_em = timezone.now()
    transacao.conciliado_por = usuario
    _lancar_taxa(transacao, usuario)
    transacao.save()
    return transacao


@transaction.atomic
def marcar_sem_venda_cartao(*, transacao, usuario=None):
    """Marca a transação como sem venda correspondente no caixa (para conferência)."""
    transacao.status = TransacaoCartao.Status.SEM_VENDA
    transacao.conciliado_em = timezone.now()
    transacao.conciliado_por = usuario
    transacao.save()
    return transacao


@transaction.atomic
def desfazer_cartao(*, transacao, usuario=None):
    """Volta a transação para pendente e remove o lançamento de taxa criado por ela."""
    lanc = transacao.lancamento_taxa
    transacao.movimento_caixa = None
    transacao.divergencia_valor = None
    transacao.lancamento_taxa = None
    transacao.status = TransacaoCartao.Status.PENDENTE
    transacao.conciliado_em = None
    transacao.conciliado_por = None
    transacao.save()
    if lanc:
        lanc.delete()
    return transacao


def posicao_conciliacao() -> dict:
    """Resumo para o painel."""
    le = LancamentoExtrato.objects
    tc = TransacaoCartao.objects
    return {
        "extrato_total": le.count(),
        "extrato_conciliado": le.filter(status=LancamentoExtrato.Status.CONCILIADO).count(),
        "extrato_pendente": le.filter(status=LancamentoExtrato.Status.PENDENTE).count(),
        "cartao_total": tc.count(),
        "cartao_conciliado": tc.filter(status=TransacaoCartao.Status.CONCILIADO).count(),
        "cartao_pendente": tc.filter(status=TransacaoCartao.Status.PENDENTE).count(),
    }


# ── Relatório de fechamento (por mês/ano ou período) ─────────────────────────
def fechamento(inicio, fim) -> dict:
    """Resumo da conciliação no período: extrato (por `data`) e cartão (por `data_venda`).

    Contagens por status + valores (créditos/débitos conciliados; bruto/líquido/taxa do
    cartão) + % conciliado + nº de divergências. `kpis` é lista (rótulo, valor) para CSV.
    """
    le = LancamentoExtrato.objects.filter(data__gte=inicio, data__lte=fim)
    ext_total = le.count()
    ext_conc = le.filter(status=LancamentoExtrato.Status.CONCILIADO).count()
    ext_pend = le.filter(status=LancamentoExtrato.Status.PENDENTE).count()
    ext_ign = le.filter(status=LancamentoExtrato.Status.IGNORADO).count()
    creditos = (le.filter(status=LancamentoExtrato.Status.CONCILIADO, valor__gt=0)
                .aggregate(s=Sum("valor"))["s"] or Decimal("0.00"))
    debitos = (le.filter(status=LancamentoExtrato.Status.CONCILIADO, valor__lt=0)
               .aggregate(s=Sum("valor"))["s"] or Decimal("0.00"))
    base_ext = ext_total - ext_ign
    pct_ext = round(ext_conc / base_ext * 100, 1) if base_ext else 0.0

    tc = TransacaoCartao.objects.filter(data_venda__gte=inicio, data_venda__lte=fim)
    c_total = tc.count()
    c_conc = tc.filter(status=TransacaoCartao.Status.CONCILIADO).count()
    c_pend = tc.filter(status=TransacaoCartao.Status.PENDENTE).count()
    c_sv = tc.filter(status=TransacaoCartao.Status.SEM_VENDA).count()
    bruto = tc.aggregate(s=Sum("bruto"))["s"] or Decimal("0.00")
    liquido = tc.aggregate(s=Sum("liquido"))["s"] or Decimal("0.00")
    taxa = bruto - liquido
    diverg = tc.exclude(divergencia_valor=None).exclude(divergencia_valor=Decimal("0")).count()
    pct_cartao = round(c_conc / c_total * 100, 1) if c_total else 0.0

    return {
        "extrato": {"total": ext_total, "conciliado": ext_conc, "pendente": ext_pend,
                    "ignorado": ext_ign, "creditos": creditos, "debitos": debitos, "pct": pct_ext},
        "cartao": {"total": c_total, "conciliado": c_conc, "pendente": c_pend,
                   "sem_venda": c_sv, "bruto": bruto, "liquido": liquido, "taxa": taxa,
                   "divergencias": diverg, "pct": pct_cartao},
        "kpis": [
            ("Extrato — linhas", ext_total),
            ("Extrato — conciliadas", ext_conc),
            ("Extrato — pendentes", ext_pend),
            ("Extrato — ignoradas", ext_ign),
            ("Extrato — % conciliado", f"{pct_ext}%"),
            ("Créditos conciliados (R$)", creditos),
            ("Débitos conciliados (R$)", debitos),
            ("Cartão — transações", c_total),
            ("Cartão — conciliadas", c_conc),
            ("Cartão — sem venda", c_sv),
            ("Cartão bruto (R$)", bruto),
            ("Cartão líquido (R$)", liquido),
            ("Taxa de cartão (R$)", taxa),
            ("Cartão — divergências", diverg),
        ],
    }

"""
Interface pública do módulo Reservas.

Outros módulos (Loja, Restaurante, APP/Site...) consultam disponibilidade e
lançam consumo na conta SOMENTE por estas funções — nunca importando os
models internos.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    MovimentoCaixa,
    Temporada,
    TipoUH,
    registrar_auditoria,
)

from .models import (
    Adiantamento,
    ColchoesExtra,
    ContaHospedagem,
    GrupoReserva,
    LancamentoConta,
    PagamentoConta,
    Reserva,
    Tarifa,
)

# Quando duas temporadas cobrem a mesma data (ex.: feriado dentro da alta),
# vale a de maior precedência.
PRECEDENCIA_TEMPORADA = [
    Temporada.Classificacao.FERIADO,
    Temporada.Classificacao.SUPER_ALTA,
    Temporada.Classificacao.ALTA,
    Temporada.Classificacao.MEDIA,
    Temporada.Classificacao.BAIXA,
]


def classificacao_do_dia(dia: date) -> str | None:
    """Classificação de temporada vigente na data (ou None = fora de temporada).

    Precedência: feriado automático (calendário nacional + Itá, se ligado) →
    temporadas cadastradas (cada uma só nos seus dias da semana: Seg–Qui = baixa,
    Sex–Dom = alta; sem dias marcados = todos os dias). Feriado sempre vence."""
    from apps.nucleo.feriados import eh_feriado
    from apps.nucleo.models.cadastros import ConfiguracaoReservas

    # Feriado automático só consulta a config nas datas que são realmente feriado,
    # para não bater no banco em todo dia comum.
    if eh_feriado(dia) and ConfiguracaoReservas.carregar().feriados_automaticos:
        return Temporada.Classificacao.FERIADO

    vigentes = {
        t.classificacao
        for t in Temporada.objects.filter(inicio__lte=dia, fim__gte=dia)
        if t.vale_no_dia(dia)
    }
    for classificacao in PRECEDENCIA_TEMPORADA:
        if classificacao in vigentes:
            return classificacao
    return None


def tarifa_do_dia(tipo_uh: TipoUH, dia: date) -> Decimal:
    """Diária do tipo na data: tarifa da temporada vigente, senão tarifa base."""
    classificacao = classificacao_do_dia(dia)
    if classificacao:
        tarifa = Tarifa.objects.filter(
            tipo_uh=tipo_uh, classificacao=classificacao
        ).first()
        if tarifa:
            return tarifa.valor
    return tipo_uh.tarifa_base


def diaria_media(tipo_uh: TipoUH, checkin: date, checkout: date) -> Decimal:
    """Média das diárias do período (valor sugerido para a reserva)."""
    noites = (checkout - checkin).days
    if noites <= 0:
        raise ValidationError("Período inválido: a saída deve ser após a entrada.")
    total = sum(
        tarifa_do_dia(tipo_uh, checkin + timedelta(days=n)) for n in range(noites)
    )
    return (Decimal(total) / noites).quantize(Decimal("0.01"))


# ---------- Tarifa por unidade (Passo 3) ----------
#
# A matriz Tarifa (TipoUH × classificação) segue a base. O que a unidade acrescenta:
# quarto de dois cômodos custa mais que o de um, e a unidade pode ter tarifa própria.
# Ordem de resolução: tarifa_override → tarifa do tipo × fator se duplo → tarifa do tipo.


def _arredonda_dezena(valor: Decimal) -> Decimal:
    """Arredonda à dezena mais próxima (250 × 1.6 = 400)."""
    return (valor / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10


def _tarifa_unidade_sobre(uh: UH, tarifa_tipo: Decimal) -> Decimal:
    """Aplica as regras da unidade sobre uma diária-base do tipo."""
    from apps.nucleo.estrutura import eh_duplo

    if uh.tarifa_override is not None:
        return uh.tarifa_override
    if eh_duplo(uh):
        fator = Decimal(str(getattr(settings, "ACRESCIMO_TARIFA_DUPLO", 1.6)))
        return _arredonda_dezena(tarifa_tipo * fator)
    return tarifa_tipo


def tarifa_da_unidade(uh: UH, dia: date) -> Decimal:
    """Diária efetiva da unidade num dia. Precedência:
    preço do QUARTO na temporada (TarifaUnidade) → tarifa própria fixa
    (tarifa_override) → tipo × fator se duplo → tipo."""
    from .models import TarifaUnidade

    classif = classificacao_do_dia(dia)
    if classif:
        t = TarifaUnidade.objects.filter(uh=uh, classificacao=classif).first()
        if t:
            return t.valor
    return _tarifa_unidade_sobre(uh, tarifa_do_dia(uh.tipo, dia))


def diaria_media_unidade(uh: UH, checkin: date, checkout: date) -> Decimal:
    """Média das diárias efetivas da unidade no período."""
    noites = (checkout - checkin).days
    if noites <= 0:
        raise ValidationError("Período inválido: a saída deve ser após a entrada.")
    total = sum(
        tarifa_da_unidade(uh, checkin + timedelta(days=n)) for n in range(noites)
    )
    return (Decimal(total) / noites).quantize(Decimal("0.01"))


def tarifa_base_unidade(uh: UH) -> Decimal:
    """Diária de referência da unidade fora de temporada — o "a partir de" do card
    por quarto na vitrine (sem datas)."""
    return _tarifa_unidade_sobre(uh, uh.tipo.tarifa_base)


def preco_unidade_noite(uh: UH, dia: date):
    """`(base 2 pax, pessoa_adicional, meia 6-15)` da unidade na data — a fonte do
    preço por ocupação (Passo 3). Precedência:

    1. **Feriado específico do quarto** (`TarifaTemporada`, ex.: Natal/Ano Novo).
    2. **Classificação** (feriado automático / alta / baixa) com preço do quarto
       (`TarifaUnidade`).
    3. **Fallback**: base atual do quarto + `pessoa_adicional` do tipo.

    `pessoa_adicional` e `meia` seguem a mesma fonte do valor; se a fonte não os
    definir, caem no do tipo / metade do adicional — nada muda até preencher."""
    from .models import TarifaTemporada, TarifaUnidade

    pa_tipo = uh.tipo.pessoa_adicional or Decimal("0.00")

    def _resolve(t):
        adic = t.pessoa_adicional if t.pessoa_adicional is not None else pa_tipo
        meia = t.meia if t.meia is not None else (adic / 2)
        return t.valor, adic, meia

    especiais = [
        t for t in TarifaTemporada.objects.filter(
            uh=uh, temporada__inicio__lte=dia, temporada__fim__gte=dia,
        ).select_related("temporada")
        if t.temporada.vale_no_dia(dia)
    ]
    if especiais:  # período mais curto = mais específico
        return _resolve(min(especiais, key=lambda x: (x.temporada.fim - x.temporada.inicio).days))

    classif = classificacao_do_dia(dia)
    if classif:
        t = TarifaUnidade.objects.filter(uh=uh, classificacao=classif).first()
        if t:
            return _resolve(t)

    return tarifa_da_unidade(uh, dia), pa_tipo, (pa_tipo / 2)


def tarifa_day_use(dia: date):
    """`(valor_adulto, valor_meia)` do day use na data pela classificação da
    temporada, ou None se não houver preço cadastrado (cai no tipo)."""
    from .models import TarifaDayUse

    classif = classificacao_do_dia(dia)
    if classif:
        t = TarifaDayUse.objects.filter(classificacao=classif).first()
        if t:
            meia = t.valor_meia if t.valor_meia is not None else (t.valor_adulto / 2)
            return t.valor_adulto, meia
    return None


def tarifa_minima_do_tipo(tipo_uh: TipoUH) -> Decimal | None:
    """Menor diária efetiva entre as unidades do tipo — o "a partir de" honesto.

    Usa a tarifa base do tipo como referência (fora de temporada). Corrige a
    promessa falsa de anunciar por menos do que qualquer unidade custa.
    """
    valores = [
        _tarifa_unidade_sobre(uh, tipo_uh.tarifa_base)
        for uh in tipo_uh.uhs.all()
    ]
    return min(valores) if valores else None


# ---------- Colchão extra e cotação itemizada (Passo 4) ----------


def colchoes_extras(reserva) -> int:
    """Quantos colchões extras a reserva exige (para a governança preparar o quarto).

    Interface pública: a governança lê daqui, sem importar models de reservas.
    """
    from apps.nucleo.estrutura import extras_para

    return extras_para(reserva.uh, reserva.adultos + reserva.criancas)


def reservas_ativas_qs():
    """Reservas que seguram a UH agora — pré-reservas com retenção vencida NÃO contam
    (o quarto já está livre, mesmo antes do job de expiração rodar)."""
    return Reserva.objects.filter(status__in=Reserva.STATUS_ATIVOS).exclude(
        status=Reserva.Status.PRE_RESERVA, expira_em__lt=timezone.now()
    )


def reservas_no_periodo(uh: UH, checkin: date, checkout: date):
    """Reservas ativas da UH que colidem com o período [checkin, checkout)."""
    return reservas_ativas_qs().filter(
        uh=uh, checkin__lt=checkout, checkout__gt=checkin,
    )


def expirar_vencidas() -> int:
    """Cancela as pré-reservas cujo prazo de retenção venceu, liberando o quarto.
    Chamada pelo cron (management command) e antes de alocar uma nova reserva."""
    n = Reserva.objects.filter(
        status=Reserva.Status.PRE_RESERVA, expira_em__lt=timezone.now()
    ).update(
        status=Reserva.Status.CANCELADA,
        motivo_cancelamento="Pré-reserva expirada (retenção sem confirmação).",
    )
    return n


def _uhs_bloqueio_manutencao(checkin: date, checkout: date) -> set:
    """IDs de UHs bloqueadas por Manutenção (por datas) que colidem com as noites
    [checkin, checkout). Vazio se o módulo estiver inativo — degradação graciosa."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    if not modulo_ativo(Modulo.MANUTENCAO):
        return set()
    from apps.manutencao.services import uhs_bloqueadas
    return set(uhs_bloqueadas(checkin, checkout))


def reserva_conflita(uh: UH, inicio: date, fim: date | None = None) -> bool:
    """Há reserva ativa nas noites [inicio, fim] (fim inclusive; None = em aberto)?
    Interface pública para a Manutenção validar a janela de bloqueio."""
    qs = reservas_ativas_qs().filter(uh=uh, checkout__gt=inicio)
    if fim is not None:
        qs = qs.filter(checkin__lte=fim)
    return qs.exists()


def uh_disponivel(uh: UH, checkin: date, checkout: date, *,
                  adultos=None, criancas=None) -> bool:
    """O quarto está livre no período? Informe `adultos`/`criancas` para que a
    disponibilidade também respeite o **pool de colchões extra** por noite (Fase 4):
    um quarto só é oferecido para aquela lotação se houver colchão extra em todas as
    noites. Sem a lotação, devolve a disponibilidade-base (comportamento histórico)."""
    livre = (
        uh.status == UH.Status.ATIVA
        and not reservas_no_periodo(uh, checkin, checkout).exists()
        and uh.pk not in _uhs_bloqueio_manutencao(checkin, checkout)
    )
    if not livre or adultos is None:
        return livre
    return colchoes_extra_suficiente(uh, checkin, checkout, adultos, criancas or 0)


def uhs_disponiveis(checkin: date, checkout: date, *, adultos=None, criancas=None):
    """UHs ativas livres no período — consulta central de disponibilidade
    (reservas ativas + bloqueios de manutenção por datas). Com `adultos`/`criancas`,
    descarta também os quartos cujo arranjo sugerido não caberia no pool de colchões
    extra por noite (Fase 4). Retorna sempre um queryset (encadeável)."""
    ocupadas = set(reservas_ativas_qs().filter(
        checkin__lt=checkout, checkout__gt=checkin,
    ).values_list("uh_id", flat=True))
    ocupadas |= _uhs_bloqueio_manutencao(checkin, checkout)
    qs = UH.objects.filter(status=UH.Status.ATIVA).exclude(pk__in=ocupadas)
    if adultos is None or (checkout - checkin).days <= 0:
        return qs

    from apps.reservas import colchoes

    livres = colchoes_extra_livres(checkin, checkout)
    min_livre = min(livres.values()) if livres else ColchoesExtra.atual().quantidade
    insuficientes = set()
    for uh in qs.select_related("config").prefetch_related("posicoes_cama"):
        if not colchoes.configurado(uh):
            continue
        arr = colchoes.sugerir_arranjo(uh, adultos, criancas or 0)
        precisa = colchoes.consumo_extra(uh, arr.casais, arr.solteiros)
        # Quarto que não puxa do pool (base garantida) está sempre disponível, mesmo
        # com o pool esgotado/negativo numa noite.
        if precisa > 0 and precisa > min_livre:
            insuficientes.add(uh.pk)
    return qs.exclude(pk__in=insuficientes)


def colchoes_extra_suficiente(uh: UH, checkin: date, checkout: date,
                              adultos: int, criancas: int, excluir_id=None) -> bool:
    """Há colchão extra no pool para acomodar essa lotação neste quarto em TODAS as
    noites? A base de casal é garantida → True quando o arranjo sugerido não precisa de
    extra, ou quando o quarto está fora do modelo de colchões (day use / sem camas)."""
    from apps.reservas import colchoes

    if not colchoes.configurado(uh):
        return True
    arr = colchoes.sugerir_arranjo(uh, adultos, criancas)
    precisa = colchoes.consumo_extra(uh, arr.casais, arr.solteiros)
    if precisa <= 0 or (checkout - checkin).days <= 0:
        return True
    livres = colchoes_extra_livres(checkin, checkout, excluir_id=excluir_id)
    return all(livre >= precisa for livre in livres.values())


# ───────── Estoque de colchões extra — trava global por noite ─────────
#
# A base de casal de cada quarto (2×casais_max) é garantida e NÃO disputa o pool.
# Só o consumo EXTRA (Reserva.colchoes_extra) de cada reserva ativa briga pelo pool
# global (ColchoesExtra). A trava é por NOITE [checkin, checkout). Sofá-cama não
# consome colchão. Ver docs/Reservas/PLANO_ESTOQUE_COLCHOES.md.


def _noites(checkin: date, checkout: date) -> list:
    return [checkin + timedelta(days=n) for n in range((checkout - checkin).days)]


def colchoes_extra_por_noite(checkin: date, checkout: date, excluir_id=None) -> dict:
    """{noite: colchões extra JÁ usados pelas reservas ativas naquela noite}.

    Ativas = pré-reserva (retenção válida) + confirmada + hospedada (`reservas_ativas_qs`;
    exclui orçamento/cancelada/no-show). `excluir_id` tira a própria reserva da soma, para
    a edição não contar o próprio consumo em dobro."""
    noites = _noites(checkin, checkout)
    usados = {n: 0 for n in noites}
    qs = (reservas_ativas_qs()
          .filter(checkin__lt=checkout, checkout__gt=checkin)
          .select_related("uh")
          .prefetch_related("uh__posicoes_cama"))
    if excluir_id:
        qs = qs.exclude(pk=excluir_id)
    for r in qs:
        extra = r.colchoes_extra
        if not extra:
            continue
        for n in noites:
            if r.checkin <= n < r.checkout:
                usados[n] += extra
    return usados


def colchoes_extra_livres(checkin: date, checkout: date, excluir_id=None) -> dict:
    """{noite: colchões extra LIVRES} = pool global − usados pelas reservas ativas."""
    pool = ColchoesExtra.atual().quantidade
    usados = colchoes_extra_por_noite(checkin, checkout, excluir_id=excluir_id)
    return {n: pool - u for n, u in usados.items()}


def conferir_arranjo(uh, *, casais, solteiros, usa_sofa_cama, adultos, criancas,
                     checkin, checkout, excluir_id=None) -> dict:
    """Confere um arranjo de camas: ESTRUTURA do quarto (`colchoes.cabe_no_quarto`) +
    TRAVA GLOBAL do pool de extras por noite. Pura (não grava), reutilizável por
    recepção, site, admin e API. Retorna {"erros", "avisos", "extra"}.

    - `erros` bloqueiam (estrutura inválida OU falta colchão extra em alguma noite —
      a mensagem aponta a(s) noite(s) e quantos faltam).
    - `avisos` não bloqueiam ("resta só N colchão extra na noite dd/mm").
    - a **base de casal nunca é bloqueada** por colchão: só o excedente (`extra`) disputa.
    """
    from apps.reservas import colchoes as _colchoes

    erros = list(_colchoes.cabe_no_quarto(
        uh, casais, solteiros, usa_sofa_cama, adultos, criancas))
    avisos: list = []
    precisa = _colchoes.consumo_extra(uh, casais, solteiros)

    if precisa and (checkout - checkin).days > 0:
        cfg = ColchoesExtra.atual()
        livres = colchoes_extra_livres(checkin, checkout, excluir_id=excluir_id)
        faltam = [(n, precisa - livre) for n, livre in sorted(livres.items())
                  if livre < precisa]
        if faltam:
            txt = ", ".join(f"{n:%d/%m} (faltam {q})" for n, q in faltam)
            erros.append(
                f"Sem colchão extra para este arranjo na(s) noite(s): {txt}. "
                "Use menos pessoas, o sofá-cama, outro quarto ou outra data."
            )
        else:
            apertadas = [(n, livre - precisa) for n, livre in sorted(livres.items())
                         if (livre - precisa) <= cfg.alerta_minimo]
            if apertadas:
                n, resta = apertadas[0]
                avisos.append(
                    f"Atenção: depois desta reserva resta {resta} colchão extra "
                    f"na noite {n:%d/%m}."
                )
    return {"erros": erros, "avisos": avisos, "extra": precisa}


# ───────── Berço — recurso global (grátis), trava por noite ─────────


def bercos_usados_por_noite(checkin: date, checkout: date, excluir_id=None) -> dict:
    """{noite: berços já usados pelas reservas ativas naquela noite}. `excluir_id` tira
    a própria reserva da soma (edição não conta em dobro)."""
    noites = _noites(checkin, checkout)
    usados = {n: 0 for n in noites}
    qs = reservas_ativas_qs().filter(
        usa_berco=True, checkin__lt=checkout, checkout__gt=checkin)
    if excluir_id:
        qs = qs.exclude(pk=excluir_id)
    for r in qs.values("checkin", "checkout"):
        for n in noites:
            if r["checkin"] <= n < r["checkout"]:
                usados[n] += 1
    return usados


def berco_disponivel(checkin: date, checkout: date, excluir_id=None) -> bool:
    """Há berço livre em TODAS as noites do período? (estoque global − usados)."""
    from .models import BercoEstoque

    if (checkout - checkin).days <= 0:
        return False
    estoque = BercoEstoque.atual().quantidade
    usados = bercos_usados_por_noite(checkin, checkout, excluir_id=excluir_id)
    return all(u < estoque for u in usados.values())


def _resolver_arranjo(uh, *, casais, solteiros, usa_sofa_cama, adultos, criancas):
    """Resolve o arranjo a persistir: usa o informado ou, se vier vazio, a sugestão
    de `colchoes.sugerir_arranjo` (casal base → sofá → solteiro extra)."""
    from apps.reservas.colchoes import sugerir_arranjo

    if casais is None and solteiros is None:
        arr = sugerir_arranjo(uh, adultos, criancas)
        sofa = arr.usa_sofa_cama if usa_sofa_cama is None else bool(usa_sofa_cama)
        return arr.casais, arr.solteiros, sofa
    return int(casais or 0), int(solteiros or 0), bool(usa_sofa_cama)


def _travar_e_resolver_arranjo(uh, *, casais, solteiros, usa_sofa_cama,
                               adultos, criancas, checkin, checkout) -> dict:
    """Resolve o arranjo de camas e **trava o pool de colchões por noite** (lock), para
    quartos configurados. Levanta ValidationError se a trava recusa. Devolve o dict de
    campos a persistir na Reserva. Chamar dentro de uma transação (o lock serializa a
    corrida). Usado por `criar_prereserva` e `adicionar_quarto`."""
    from apps.reservas import colchoes

    if not colchoes.configurado(uh):
        return {chave: valor for chave, valor in (
            ("casais", casais), ("solteiros", solteiros), ("usa_sofa_cama", usa_sofa_cama))
            if valor is not None}
    ColchoesExtra.atual()  # garante a linha única do pool
    ColchoesExtra.objects.select_for_update().first()  # trava o pool nesta transação
    casais, solteiros, usa_sofa_cama = _resolver_arranjo(
        uh, casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa_cama,
        adultos=adultos, criancas=criancas)
    conf = conferir_arranjo(
        uh, casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa_cama,
        adultos=adultos, criancas=criancas, checkin=checkin, checkout=checkout)
    if conf["erros"]:
        raise ValidationError(conf["erros"])
    return {"casais": casais, "solteiros": solteiros, "usa_sofa_cama": usa_sofa_cama}


def painel_colchoes(inicio: date, fim: date) -> dict:
    """Ocupação do pool de colchões extra por noite no período [inicio, fim] (fim
    inclusive). Para o painel de colchões (gerência). Status: ok / aviso / esgotado."""
    cfg = ColchoesExtra.atual()
    usados = colchoes_extra_por_noite(inicio, fim + timedelta(days=1))
    linhas = []
    for noite in sorted(usados):
        u = usados[noite]
        livre = cfg.quantidade - u
        if livre <= 0:
            status = "esgotado"
        elif livre <= cfg.alerta_minimo:
            status = "aviso"
        else:
            status = "ok"
        linhas.append({"noite": noite, "usados": u, "livres": livre, "status": status})
    return {"pool": cfg.quantidade, "alerta_minimo": cfg.alerta_minimo, "linhas": linhas}


def colchoes_alertas_proximos(dias: int = 14) -> dict | None:
    """Noites nos próximos `dias` com colchão extra esgotado ou no limite — para o
    bloco 'Precisa de atenção' do dashboard. None se estiver tudo folgado."""
    hoje = timezone.localdate()
    painel = painel_colchoes(hoje, hoje + timedelta(days=dias - 1))
    esgotadas = [ln for ln in painel["linhas"] if ln["status"] == "esgotado"]
    apertadas = [ln for ln in painel["linhas"] if ln["status"] == "aviso"]
    if not esgotadas and not apertadas:
        return None
    return {"esgotadas": esgotadas, "apertadas": apertadas}


def montagem_do_dia(dia: date) -> list:
    """Lista de montagem de camas das chegadas do dia `dia` — para a Governança:
    quarto · casais · solteiros · sofá · colchões extra. Só quartos configurados.
    Interface pública (a Governança não importa models de Reservas)."""
    from apps.reservas import colchoes

    qs = (reservas_ativas_qs()
          .filter(checkin=dia)
          .select_related("uh", "hospede")
          .prefetch_related("uh__posicoes_cama")
          .order_by("uh__numero"))
    linhas = []
    for r in qs:
        if not colchoes.configurado(r.uh):
            continue
        linhas.append({
            "uh": r.uh.numero,
            "hospede": r.hospede.nome,
            "casais": r.casais,
            "solteiros": r.solteiros,
            "sofa": r.usa_sofa_cama,
            "extra": r.colchoes_extra,
        })
    return linhas


# ───────── Interface pública para o canal Site (venda por tipo) ─────────

def uh_livre_do_tipo(tipo_uh, checkin, checkout, *, adultos=None, criancas=None):
    """Uma UH livre daquele tipo no período (ordem por número), ou None. Com
    `adultos`/`criancas`, só devolve um quarto cujo arranjo caiba no pool de colchões."""
    if (checkout - checkin).days <= 0:
        return None
    return (uhs_disponiveis(checkin, checkout, adultos=adultos, criancas=criancas)
            .filter(tipo=tipo_uh).order_by("numero").first())


def tipo_disponivel(tipo_uh, checkin, checkout, *, adultos=None, criancas=None) -> bool:
    """Há ao menos um quarto desse tipo livre no período (e, com a lotação, com colchão
    extra no pool)?"""
    return uh_livre_do_tipo(
        tipo_uh, checkin, checkout, adultos=adultos, criancas=criancas) is not None


def obter_ou_criar_hospede(*, nome, email="", telefone="", documento=""):
    """Localiza (por e-mail/CPF) ou cria a Pessoa + especialização Hóspede.
    Interface pública para o canal Site cadastrar o hóspede no CRM."""
    from apps.nucleo.models import Hospede, Pessoa

    pessoa = None
    if email:
        pessoa = Pessoa.objects.filter(email__iexact=email).first()
    if not pessoa and documento:
        pessoa = Pessoa.objects.filter(documento=documento).first()
    if pessoa:
        campos = []
        if nome and pessoa.nome != nome:
            pessoa.nome = nome
            campos.append("nome")
        if telefone and not pessoa.telefone:
            pessoa.telefone = telefone
            campos.append("telefone")
        if documento and not pessoa.documento:
            pessoa.documento = documento
            campos.append("documento")
        if campos:
            pessoa.save(update_fields=campos)
    else:
        pessoa = Pessoa.objects.create(
            nome=nome, email=email, telefone=telefone, documento=documento
        )
    Hospede.objects.get_or_create(pessoa=pessoa)
    return pessoa


@transaction.atomic
def criar_prereserva(*, tipo_uh=None, uh=None, checkin, checkout, hospede, usuario,
                     canal=Reserva.Canal.BALCAO, faturamento=None, titular=None,
                     adultos=2, criancas=0, valor_diaria=None, observacoes="",
                     reter=False, casais=None, solteiros=None, usa_sofa_cama=None,
                     criancas_0_5=None, criancas_6_15=None,
                     cobra_iss=True, cobra_taxa_turismo=True, usa_berco=False,
                     nao_reembolsavel=False):
    """Cria uma PRÉ-RESERVA num quarto físico. Passe `uh` para reservar uma unidade
    ESPECÍFICA (venda por quarto) ou `tipo_uh` para alocar qualquer livre do tipo. O
    antioverbooking (constraint) protege da corrida. Interface pública usada pelo Site
    (com retenção) e por outros canais/módulos, como a conversão do Comercial.

    Preço: quando `valor_diaria` é None, calcula pela motor de tarifa (Manual §2 — pessoa
    adicional, single 70%, criança 6-15 meia). Arranjo de camas: se `casais`/`solteiros`
    vierem vazios, o sistema sugere; a **trava global de colchões extra por noite** é
    validada aqui (lock serializa a corrida)."""
    from apps.reservas import precos

    expirar_vencidas()  # solta retenções vencidas para não bloquear a constraint
    por_unidade = uh is not None
    if por_unidade:
        if not uh_disponivel(uh, checkin, checkout):
            raise ValidationError("Este quarto não está disponível no período.")
        tipo_uh = uh.tipo
    else:
        # Aloca um quarto do tipo que também caiba no pool de colchões p/ a lotação
        # (evita escolher um quarto que a trava recusaria logo em seguida).
        uh = uh_livre_do_tipo(tipo_uh, checkin, checkout,
                              adultos=adultos, criancas=criancas)
        if not uh:
            raise ValidationError("Não há quarto desse tipo disponível no período.")

    # Faixas de criança p/ o preço: sem o detalhe (chamador legado), trata `criancas`
    # como 6-15 (meia) — conservador. Mantém `criancas` = total coerente.
    if criancas_0_5 is None and criancas_6_15 is None:
        criancas_0_5, criancas_6_15 = 0, criancas
    else:
        criancas_0_5, criancas_6_15 = (criancas_0_5 or 0), (criancas_6_15 or 0)
    criancas = criancas_0_5 + criancas_6_15

    if valor_diaria is None:
        cot = precos.cotacao(
            uh=uh if por_unidade else None, tipo=None if por_unidade else tipo_uh,
            checkin=checkin, checkout=checkout, adultos=adultos,
            criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
            nao_reembolsavel=nao_reembolsavel)
        valor_diaria = cot["media_noite"]

    # Arranjo + trava global de colchões extra por noite (lock serializa a corrida).
    arranjo = _travar_e_resolver_arranjo(
        uh, casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa_cama,
        adultos=adultos, criancas=criancas, checkin=checkin, checkout=checkout)

    # Berço (grátis, recurso global): só concede se houver livre em todas as noites.
    if usa_berco and not berco_disponivel(checkin, checkout):
        raise ValidationError("Não há berço disponível em alguma noite do período.")

    expira = (timezone.now() + timedelta(minutes=settings.RESERVA_RETENCAO_MINUTOS)
              if reter else None)
    extra = {}
    if faturamento:
        extra["faturamento"] = faturamento
    if titular:
        extra["titular"] = titular
    try:
        return Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=checkin, checkout=checkout,
            adultos=adultos, criancas=criancas,
            criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
            cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
            usa_berco=usa_berco, nao_reembolsavel=nao_reembolsavel,
            status=Reserva.Status.PRE_RESERVA, canal=canal,
            valor_diaria=valor_diaria, criado_por=usuario, observacoes=observacoes,
            expira_em=expira, **arranjo, **extra,
        )
    except IntegrityError:
        raise ValidationError("Este quarto acabou de ser reservado. Tente novamente.")


def criar_reserva_site(*, tipo_uh, checkin, checkout, hospede, usuario,
                       adultos=2, criancas=0, valor_diaria=None, observacoes="",
                       criancas_0_5=None, criancas_6_15=None,
                       cobra_iss=True, cobra_taxa_turismo=True):
    """Pré-reserva do canal Site, com prazo de retenção (fina camada sobre criar_prereserva)."""
    return criar_prereserva(
        tipo_uh=tipo_uh, checkin=checkin, checkout=checkout, hospede=hospede,
        usuario=usuario, canal=Reserva.Canal.SITE, adultos=adultos, criancas=criancas,
        valor_diaria=valor_diaria, observacoes=observacoes, reter=True,
        criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
        cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
    )


def criar_reserva_site_unidade(*, uh, checkin, checkout, hospede, usuario,
                               adultos=2, criancas=0, valor_diaria=None, observacoes="",
                               criancas_0_5=None, criancas_6_15=None,
                               cobra_iss=True, cobra_taxa_turismo=True,
                               casais=None, solteiros=None, usa_sofa_cama=None):
    """Pré-reserva do canal Site num quarto ESPECÍFICO (venda por unidade), com retenção.
    `casais`/`solteiros`/`usa_sofa_cama` deixam o hóspede escolher a montagem das camas;
    vazio = o sistema sugere."""
    return criar_prereserva(
        uh=uh, checkin=checkin, checkout=checkout, hospede=hospede,
        usuario=usuario, canal=Reserva.Canal.SITE, adultos=adultos, criancas=criancas,
        valor_diaria=valor_diaria, observacoes=observacoes, reter=True,
        criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
        cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
        casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa_cama,
    )


def arranjos_disponiveis(uh) -> list:
    """Opções de montagem de cama que o hóspede pode escolher no site (venda por
    unidade). Interface pública — devolve [{rotulo, casais, solteiros, tem_sofa}]."""
    from apps.reservas import colchoes

    if not colchoes.configurado(uh):
        return []
    opcoes = colchoes.presets(uh)
    tem_sofa = colchoes.tem_sofa(uh)
    return [{"rotulo": o["rotulo"], "casais": o["casais"], "solteiros": o["solteiros"],
             "tem_sofa": tem_sofa} for o in opcoes]


@transaction.atomic
def transferir_datas(reserva, novo_checkin, novo_checkout, usuario):
    """Reagenda a reserva para outras datas (1ª opção de cancelamento — não é
    cancelamento). Revalida disponibilidade da UH + pool de colchões nas novas datas e
    recalcula a diária pela motor. Mantém a janela de arrependimento (confirmada_em).
    Só para reserva NÃO iniciada."""
    from apps.reservas import colchoes, precos

    if reserva.status not in (Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA,
                              Reserva.Status.CONFIRMADA):
        raise ValidationError("Só dá para transferir a data de uma reserva não iniciada.")
    if (novo_checkout - novo_checkin).days <= 0:
        raise ValidationError("Período inválido: a saída deve ser após a entrada.")

    expirar_vencidas()
    conflito = (reservas_ativas_qs()
                .filter(uh=reserva.uh, checkin__lt=novo_checkout, checkout__gt=novo_checkin)
                .exclude(pk=reserva.pk).exists())
    if conflito or reserva.uh.pk in _uhs_bloqueio_manutencao(novo_checkin, novo_checkout):
        raise ValidationError("O quarto não está livre nas novas datas.")

    if colchoes.configurado(reserva.uh):
        ColchoesExtra.objects.select_for_update().first()
        conf = conferir_arranjo(
            reserva.uh, casais=reserva.casais, solteiros=reserva.solteiros,
            usa_sofa_cama=reserva.usa_sofa_cama, adultos=reserva.adultos,
            criancas=reserva.criancas, checkin=novo_checkin, checkout=novo_checkout,
            excluir_id=reserva.pk)
        if conf["erros"]:
            raise ValidationError(conf["erros"])

    nova_diaria = precos.cotacao(
        uh=reserva.uh, checkin=novo_checkin, checkout=novo_checkout,
        adultos=reserva.adultos, criancas_0_5=reserva.criancas_0_5,
        criancas_6_15=reserva.criancas_6_15)["media_noite"]
    antigo = (reserva.checkin, reserva.checkout, reserva.valor_diaria)
    reserva.checkin, reserva.checkout, reserva.valor_diaria = (
        novo_checkin, novo_checkout, nova_diaria)
    try:
        reserva.save(update_fields=["checkin", "checkout", "valor_diaria"])
    except IntegrityError:
        raise ValidationError("O quarto acabou de ser reservado nessas datas.")
    registrar_auditoria(usuario, "transferencia_datas", reserva, {
        "de": f"{antigo[0]:%d/%m/%Y}–{antigo[1]:%d/%m/%Y}",
        "para": f"{novo_checkin:%d/%m/%Y}–{novo_checkout:%d/%m/%Y}",
        "diaria_antiga": str(antigo[2]), "diaria_nova": str(nova_diaria)})
    return reserva


def uh_ocupada(uh: UH) -> bool:
    """Há hóspede em casa nesta UH agora? Interface pública para outros módulos
    (ex.: Manutenção não bloqueia um quarto ocupado)."""
    return Reserva.objects.filter(uh=uh, status=Reserva.Status.HOSPEDADA).exists()


def pendentes_de_sinal():
    """Reservas que ainda podem receber sinal (orçamento/pré-reserva) — para o
    módulo Pagamentos vincular a cobrança. Retorna [{id, rotulo}]."""
    qs = (
        Reserva.objects.filter(
            status__in=[Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA]
        )
        .select_related("uh", "hospede")
        .order_by("checkin")
    )
    return [
        {"id": r.pk, "rotulo": f"#{r.pk} · {r.uh.numero} · {r.hospede.nome} · {r.checkin:%d/%m}"}
        for r in qs
    ]


def estadia_ativa(reserva_id):
    """Reserva hospedada (em casa) por id, ou None. Base do Portal do Hóspede."""
    return (
        Reserva.objects.filter(pk=reserva_id, status=Reserva.Status.HOSPEDADA)
        .select_related("uh", "hospede")
        .first()
    )


def dados_estadia(reserva_id) -> dict | None:
    """Resumo da estadia + extrato da conta para o portal do hóspede.
    Interface pública — não expõe models internos."""
    reserva = estadia_ativa(reserva_id)
    if not reserva:
        return None
    conta = getattr(reserva, "conta", None)
    lancamentos = []
    if conta:
        for lanc in conta.lancamentos.order_by("criado_em"):
            lancamentos.append({
                "descricao": lanc.descricao, "natureza": lanc.get_natureza_display(),
                "tipo": lanc.get_tipo_display(), "valor": lanc.valor,
                "quando": lanc.criado_em,
                "debito": lanc.tipo in LancamentoConta.TIPOS_DEBITO,
            })
    return {
        "reserva_id": reserva.pk,
        "uh_id": reserva.uh_id,
        "uh": reserva.uh.numero,
        "hospede": reserva.hospede.nome,
        "checkin": reserva.checkin,
        "checkout": reserva.checkout,
        "conta_id": conta.pk if conta else None,
        "lancamentos": lancamentos,
        "total": conta.total_lancamentos() if conta else Decimal("0.00"),
        "saldo": conta.saldo() if conta else Decimal("0.00"),
        "por_natureza": conta.total_por_natureza() if conta else {},
    }


def relatorio_producao(inicio: date, fim: date) -> dict:
    """Receita lançada nas contas no período, por natureza (serviço×consumo)."""
    from django.db.models import Sum
    lanc = LancamentoConta.objects.filter(criado_em__date__range=(inicio, fim))
    def _soma(**f):
        return lanc.filter(**f).aggregate(t=Sum("valor"))["t"] or Decimal("0.00")
    servico = (_soma(tipo__in=LancamentoConta.TIPOS_DEBITO, natureza="servico")
               - _soma(tipo=LancamentoConta.Tipo.DESCONTO, natureza="servico"))
    consumo = (_soma(tipo__in=LancamentoConta.TIPOS_DEBITO, natureza="consumo")
               - _soma(tipo=LancamentoConta.Tipo.DESCONTO, natureza="consumo"))
    return {"servico": servico, "consumo": consumo, "total": servico + consumo}


def relatorio_ocupacao(inicio: date, fim: date, statuses=None) -> dict:
    """Taxa de ocupação, ADR e RevPAR do período + diárias-quarto por tipo.

    `statuses` (opcional) escolhe quais reservas contam. O padrão — realizado
    (hospedada/saída) — preserva o comportamento histórico do relatório; para a
    ocupação PREVISTA (janela futura) passe também as confirmadas (ver
    `ocupacao_prevista`).
    """
    from django.db.models import Sum
    statuses = statuses or [Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT]
    dias = (fim - inicio).days + 1
    uhs = list(UH.objects.filter(status=UH.Status.ATIVA).select_related("tipo"))
    disp = len(uhs) * dias
    reservas = Reserva.objects.filter(
        status__in=statuses,
        checkin__lte=fim, checkout__gt=inicio,
    ).select_related("uh__tipo")
    ocupadas = 0
    por_tipo: dict = {}
    for r in reservas:
        ini = max(r.checkin, inicio)
        f = min(r.checkout, fim + timedelta(days=1))
        noites = max(0, (f - ini).days)
        ocupadas += noites
        por_tipo[r.uh.tipo.nome] = por_tipo.get(r.uh.tipo.nome, 0) + noites
    receita = LancamentoConta.objects.filter(
        criado_em__date__range=(inicio, fim), tipo=LancamentoConta.Tipo.DIARIA
    ).aggregate(t=Sum("valor"))["t"] or Decimal("0.00")
    taxa = (Decimal(ocupadas) / disp * 100) if disp else Decimal("0")
    adr = (receita / ocupadas) if ocupadas else Decimal("0")
    revpar = (receita / disp) if disp else Decimal("0")
    return {
        "dias": dias, "disponiveis": disp, "ocupadas": ocupadas,
        "taxa": taxa.quantize(Decimal("0.1")), "adr": adr.quantize(Decimal("0.01")),
        "revpar": revpar.quantize(Decimal("0.01")), "receita": receita,
        "por_tipo": por_tipo,
    }


def ocupacao_prevista(inicio: date, fim: date) -> dict:
    """Ocupação PREVISTA de uma janela: conta confirmadas + hospedadas + saídas.

    A janela de marketing olha para a frente (próximos 90 dias), onde as reservas
    ainda são *confirmadas* (check-in futuro) — contá-las evita o falso 0% de quem
    só olha o realizado. Mesma matemática de `relatorio_ocupacao`, outro recorte.
    """
    return relatorio_ocupacao(inicio, fim, statuses=[
        Reserva.Status.CONFIRMADA, Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT])


def relatorio_reservas(inicio: date, fim: date) -> dict:
    """Reservas criadas no período por canal e por status."""
    from django.db.models import Count
    qs = Reserva.objects.filter(criado_em__date__range=(inicio, fim))
    por_canal = dict(qs.values_list("canal").annotate(n=Count("id")))
    por_status = dict(qs.values_list("status").annotate(n=Count("id")))
    return {"total": qs.count(), "por_canal": por_canal, "por_status": por_status}


def pendencias_auditoria():
    """Inconsistências operacionais de Reservas para a Auditoria (read-only)."""
    from django.urls import reverse
    achados = []
    hoje = timezone.localdate()

    for r in (Reserva.objects.filter(status=Reserva.Status.HOSPEDADA, checkout__lt=hoje)
              .select_related("uh", "hospede")):
        achados.append({
            "area": "Reservas", "tipo": "checkout_vencido", "gravidade": "alta",
            "descricao": f"{r.uh.numero} — {r.hospede.nome}: check-out era {r.checkout:%d/%m} e não foi feito.",
            "url": reverse("reservas:detalhe", args=[r.pk]),
        })

    for c in contas_abertas():
        s = c.saldo()
        if s > 0:
            achados.append({
                "area": "Reservas", "tipo": "conta_com_saldo", "gravidade": "media",
                "descricao": f"Conta {c.reserva.uh.numero} — {c.reserva.hospede.nome}: saldo em aberto R$ {s}.",
                "url": reverse("reservas:detalhe", args=[c.reserva_id]),
            })

    vencidas = Reserva.objects.filter(
        status=Reserva.Status.PRE_RESERVA, expira_em__lt=timezone.now()
    ).count()
    if vencidas:
        achados.append({
            "area": "Reservas", "tipo": "prereserva_vencida", "gravidade": "baixa",
            "descricao": f"{vencidas} pré-reserva(s) vencida(s) ainda ativa(s) — rode 'expirar_reservas'.",
            "url": None,
        })

    prox = hoje + timedelta(days=3)
    for r in (Reserva.objects.filter(status=Reserva.Status.CONFIRMADA, checkin__lte=prox)
              .select_related("uh", "hospede")):
        if not r.adiantamentos.exists():
            achados.append({
                "area": "Reservas", "tipo": "sem_sinal", "gravidade": "baixa",
                "descricao": f"{r.uh.numero} — {r.hospede.nome}: confirmada p/ {r.checkin:%d/%m} sem sinal.",
                "url": reverse("reservas:detalhe", args=[r.pk]),
            })
    return achados


def resumo_fiscal_conta(conta_id):
    """Totais por natureza (serviço×consumo) + tomador de uma conta de hospedagem —
    interface pública para o módulo Fiscal montar a NFS-e/NFC-e. Retorna None se
    a conta não existir."""
    from apps.nucleo.models import NaturezaFiscal
    conta = (
        ContaHospedagem.objects
        .select_related("reserva__uh", "reserva__hospede")
        .filter(pk=conta_id).first()
    )
    if not conta:
        return None
    por_nat = conta.total_por_natureza()  # {"Serviço": x, "Consumo": y}
    return {
        "conta_id": conta.pk,
        "reserva_id": conta.reserva_id,
        "uh": conta.reserva.uh.numero,
        "hospede": conta.reserva.hospede,  # Pessoa (tomador)
        "servico": por_nat.get(NaturezaFiscal.SERVICO.label, Decimal("0.00")),
        "consumo": por_nat.get(NaturezaFiscal.CONSUMO.label, Decimal("0.00")),
    }


def historico_hospede(pessoa) -> dict:
    """Resumo do histórico do hóspede p/ o Comercial (cliente recorrente).
    Interface pública — não expõe models de Reservas para fora."""
    if pessoa is None:
        return {"estadias": 0, "ultima": None, "futuras": 0}
    from django.db.models import Q
    qs = Reserva.objects.filter(hospede=pessoa)
    encerradas = qs.filter(status=Reserva.Status.CHECKOUT)
    ultima = encerradas.order_by("-checkout").values_list("checkout", flat=True).first()
    # "Futuras" = reservas que ainda seguram vaga; pré-reserva vencida (retenção
    # expirada, ex.: carrinho abandonado do site) não conta como cliente recorrente.
    agora = timezone.now()
    futuras = qs.filter(
        status__in=[Reserva.Status.CONFIRMADA, Reserva.Status.PRE_RESERVA,
                    Reserva.Status.HOSPEDADA]
    ).filter(Q(expira_em__isnull=True) | Q(expira_em__gt=agora)).count()
    return {
        "estadias": encerradas.count(),
        "ultima": ultima,
        "futuras": futuras,
    }


def confirmar_reserva(reserva_id, usuario) -> bool:
    """Confirma a reserva (pré-reserva/orçamento → confirmada). Interface pública
    para o módulo Pagamentos: sinal pago online → reserva confirmada."""
    reserva = Reserva.objects.filter(pk=reserva_id).first()
    if not reserva or reserva.status not in (
        Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA
    ):
        return False
    reserva.confirmar(usuario)
    return True


def lancar_na_conta(
    conta: ContaHospedagem,
    tipo: str,
    natureza: str,
    descricao: str,
    valor: Decimal,
    usuario,
) -> LancamentoConta:
    """Lança item na conta do quarto. É por aqui que os PDVs vão lançar consumo."""
    return LancamentoConta.objects.create(
        conta=conta,
        tipo=tipo,
        natureza=natureza,
        descricao=descricao,
        valor=valor,
        criado_por=usuario,
    )


def _receber_no_caixa(
    usuario, forma: FormaPagamento, valor: Decimal, descricao: str, parcelas: int = 1,
    autorizacao: str = "",
) -> MovimentoCaixa:
    """Recebimento pelo caixa de RESERVAS do operador — gaveta própria da recepção,
    separada de Loja/Restaurante. Delega ao helper público do núcleo."""
    from apps.nucleo.models import receber_no_caixa
    from apps.nucleo.modulos import Modulo

    return receber_no_caixa(
        usuario, forma, valor, descricao, parcelas, modulo=Modulo.RESERVAS,
        autorizacao=autorizacao,
    )


@transaction.atomic
def receber_pagamento(
    conta: ContaHospedagem,
    usuario,
    forma: FormaPagamento,
    valor: Decimal,
    parcelas: int = 1,
    observacao: str = "",
    autorizacao: str = "",
) -> PagamentoConta:
    """Recebe um pagamento (parcial ou total) da conta pelo caixa do operador.
    Vários pagamentos na mesma conta = rateio (formas/pagadores diferentes). A conta
    só fecha quando o saldo zera. `observacao` registra quem pagou cada parte.
    `autorizacao` guarda o NSU/código do comprovante do cartão (conciliação)."""
    # Trava a conta p/ serializar pagamentos concorrentes (duplo POST não superpaga).
    from apps.nucleo.sistema import travar
    conta = travar(conta)
    if not conta.aberta:
        raise ValidationError("A conta desta hospedagem já foi fechada.")
    valor = Decimal(str(valor or 0))
    if valor <= 0:
        raise ValidationError("O valor do pagamento deve ser positivo.")
    if valor > conta.saldo():
        raise ValidationError(
            f"Valor acima do saldo da conta (R$ {conta.saldo()}).")
    sufixo = f" ({observacao})" if observacao else ""
    movimento = _receber_no_caixa(
        usuario, forma, valor,
        f"Conta reserva #{conta.reserva_id} — {conta.reserva.hospede.nome}{sufixo}",
        parcelas, autorizacao=autorizacao,
    )
    return PagamentoConta.objects.create(
        conta=conta, movimento_caixa=movimento, valor=valor, observacao=observacao
    )


# ---------- Reserva de grupo (reserva-mãe + filhas por quarto) ----------
#
# Folio híbrido: as diárias (e o colchão) de todos os quartos caem no folio-mãe,
# pago pelo titular; o consumo fica na conta de cada quarto. Antioverbooking,
# check-in e check-out seguem por quarto — a mãe agrupa e soma.


@transaction.atomic
def criar_grupo(*, rotulo, titular, checkin, checkout, usuario,
                faturamento=Reserva.Faturamento.PARTICULAR,
                canal=Reserva.Canal.BALCAO, observacoes="", reter=False):
    """Abre a reserva-mãe e o folio-mãe (conta das diárias). Sem quartos ainda —
    a recepção adiciona os quartos com `adicionar_quarto`."""
    if checkout <= checkin:
        raise ValidationError("A saída deve ser depois da entrada.")
    expira = (timezone.now() + timedelta(minutes=settings.RESERVA_RETENCAO_MINUTOS)
              if reter else None)
    grupo = GrupoReserva.objects.create(
        rotulo=rotulo, titular=titular, checkin=checkin, checkout=checkout,
        faturamento=faturamento, canal=canal, observacoes=observacoes,
        expira_em=expira, criado_por=usuario,
    )
    ContaHospedagem.objects.create(grupo=grupo)  # folio-mãe
    registrar_auditoria(usuario, "criar_grupo", grupo, {"rotulo": rotulo})
    return grupo


@transaction.atomic
def adicionar_quarto(grupo, *, uh, hospede, usuario, adultos=2, criancas=0,
                     valor_diaria=None, casais=None, solteiros=None, usa_sofa_cama=None,
                     criancas_0_5=None, criancas_6_15=None,
                     cobra_iss=True, cobra_taxa_turismo=True):
    """Adiciona um quarto (reserva-filha) ao grupo, num UH específico escolhido pela
    recepção. Antioverbooking valida a UH; herda período e faturamento do grupo. Preço
    pela motor (Manual §2) e **trava de colchões por noite** — igual às reservas avulsas."""
    from apps.reservas import precos

    if grupo.encerrado_em:
        raise ValidationError("Este grupo já foi encerrado.")
    if not uh_disponivel(uh, grupo.checkin, grupo.checkout):
        raise ValidationError(
            f"O quarto {uh.numero} não está livre no período do grupo."
        )

    if criancas_0_5 is None and criancas_6_15 is None:
        criancas_0_5, criancas_6_15 = 0, criancas
    else:
        criancas_0_5, criancas_6_15 = (criancas_0_5 or 0), (criancas_6_15 or 0)
    criancas = criancas_0_5 + criancas_6_15

    arranjo = _travar_e_resolver_arranjo(
        uh, casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa_cama,
        adultos=adultos, criancas=criancas,
        checkin=grupo.checkin, checkout=grupo.checkout)

    if valor_diaria is None:
        valor_diaria = precos.cotacao(
            uh=uh, checkin=grupo.checkin, checkout=grupo.checkout, adultos=adultos,
            criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15)["media_noite"]
    try:
        return Reserva.objects.create(
            uh=uh, hospede=hospede, grupo=grupo,
            checkin=grupo.checkin, checkout=grupo.checkout,
            adultos=adultos, criancas=criancas,
            criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
            cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
            status=Reserva.Status.PRE_RESERVA, canal=grupo.canal,
            faturamento=grupo.faturamento, titular=grupo.titular,
            valor_diaria=valor_diaria, criado_por=usuario, **arranjo,
        )
    except IntegrityError:
        raise ValidationError("Este quarto acabou de ser reservado. Tente outro.")


@transaction.atomic
def confirmar_grupo(grupo_id, usuario) -> bool:
    """Confirma todas as filhas em pré-reserva/orçamento. Idempotente — usada pelo
    sinal único do grupo (Pagamentos). Limpa a retenção do grupo."""
    grupo = GrupoReserva.objects.filter(pk=grupo_id).first()
    if not grupo:
        return False
    confirmadas = 0
    for filha in grupo.filhas.filter(
        status__in=[Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA]
    ):
        filha.confirmar(usuario)
        confirmadas += 1
    if grupo.expira_em:
        grupo.expira_em = None
        grupo.save(update_fields=["expira_em", "atualizado_em"])
    return confirmadas > 0


@transaction.atomic
def checkin_grupo(grupo, usuario) -> dict:
    """Check-in de conveniência do bloco: entra em cada quarto pronto, pula os que
    não dá (bloqueado, sujo) e devolve o que entrou e o que ficou."""
    entrou, pendentes = [], []
    for filha in grupo.filhas.filter(status=Reserva.Status.CONFIRMADA):
        try:
            filha.fazer_checkin(usuario)
            entrou.append(filha.uh.numero)
        except ValidationError as erro:
            pendentes.append(f"{filha.uh.numero}: {' '.join(erro.messages)}")
    return {"entrou": entrou, "pendentes": pendentes}


@transaction.atomic
def cancelar_grupo(grupo, usuario, motivo: str):
    """Cancela o bloco inteiro (cascata). Recusa se algum quarto já está hospedado —
    faça o check-out antes."""
    if not motivo:
        raise ValidationError("Informe o motivo do cancelamento.")
    if grupo.filhas.filter(status=Reserva.Status.HOSPEDADA).exists():
        raise ValidationError(
            "Há quarto hospedado no grupo — faça o check-out antes de cancelar."
        )
    for filha in grupo.filhas.filter(
        status__in=[Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA,
                    Reserva.Status.ORCAMENTO]
    ):
        filha.cancelar(usuario, motivo)
    grupo.motivo_cancelamento = motivo
    grupo.save(update_fields=["motivo_cancelamento", "atualizado_em"])
    registrar_auditoria(usuario, "cancelar_grupo", grupo, {"motivo": motivo})


@transaction.atomic
def remover_do_grupo(reserva, usuario, motivo: str):
    """Remove um quarto do bloco cancelando aquela filha (encolhe, sem derrubar o
    resto). Só antes do check-in."""
    if reserva.grupo_id is None:
        raise ValidationError("Esta reserva não pertence a um grupo.")
    if reserva.status not in (Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA,
                              Reserva.Status.ORCAMENTO):
        raise ValidationError("Só dá para remover um quarto antes do check-in.")
    reserva.cancelar(usuario, motivo or "Quarto removido do grupo.")


def total_grupo(grupo) -> dict:
    """Visão consolidada do grupo: folio-mãe (diárias) + consumo por quarto.
    Só lê e soma — nunca recalcula (cada conta é a fonte única do seu escopo)."""
    folio = grupo.folio
    quartos = []
    consumo_total = Decimal("0.00")
    saldo_consumo_total = Decimal("0.00")
    for filha in grupo.filhas.select_related("uh", "hospede").all():
        conta = getattr(filha, "conta", None)
        consumo = conta.total_lancamentos() if conta else Decimal("0.00")
        saldo = conta.saldo() if conta else Decimal("0.00")
        consumo_total += consumo
        saldo_consumo_total += saldo
        quartos.append({
            "reserva": filha, "uh": filha.uh, "consumo": consumo, "saldo": saldo,
        })
    return {
        "grupo": grupo,
        "folio": folio,
        "diarias": folio.total_lancamentos(),
        "folio_pago": folio.total_pago(),
        "folio_saldo": folio.saldo(),
        "quartos": quartos,
        "consumo_total": consumo_total,
        "saldo_consumo_total": saldo_consumo_total,
        "total_geral": folio.total_lancamentos() + consumo_total,
    }


@transaction.atomic
@transaction.atomic
def receber_folio_grupo(grupo, usuario, forma: FormaPagamento, valor: Decimal,
                        parcelas: int = 1, observacao: str = "",
                        autorizacao: str = "") -> PagamentoConta:
    """Recebe (parcial ou total) o folio-mãe pelo caixa do operador. O folio só fecha
    no `encerrar_grupo`, quando o saldo zera."""
    from apps.nucleo.sistema import travar
    folio = travar(grupo.folio)
    if not folio.aberta:
        raise ValidationError("O folio deste grupo já foi fechado.")
    valor = Decimal(str(valor or 0))
    if valor <= 0:
        raise ValidationError("O valor do pagamento deve ser positivo.")
    if valor > folio.saldo():
        raise ValidationError(f"Valor acima do saldo do folio (R$ {folio.saldo()}).")
    sufixo = f" ({observacao})" if observacao else ""
    movimento = _receber_no_caixa(
        usuario, forma, valor, f"Folio grupo #{grupo.pk} — {grupo.rotulo}{sufixo}",
        parcelas, autorizacao=autorizacao,
    )
    return PagamentoConta.objects.create(
        conta=folio, movimento_caixa=movimento, valor=valor, observacao=observacao
    )


@transaction.atomic
def encerrar_grupo(grupo, usuario):
    """Encerra o grupo: exige todos os quartos fora de estado ativo (check-out ou
    cancelados) e o folio-mãe com saldo zero. Fecha o folio e marca o grupo."""
    if grupo.encerrado_em:
        raise ValidationError("Este grupo já foi encerrado.")
    if grupo.filhas_ativas.exists():
        raise ValidationError(
            "Ainda há quartos ativos no grupo — faça o check-out de todos antes."
        )
    folio = grupo.folio
    if folio.saldo() != Decimal("0.00"):
        raise ValidationError(
            f"O folio do grupo tem saldo de R$ {folio.saldo()} — receba ou fature antes."
        )
    folio.status = ContaHospedagem.Status.FECHADA
    folio.fechada_em = timezone.now()
    folio.save(update_fields=["status", "fechada_em"])
    grupo.encerrado_em = timezone.now()
    grupo.save(update_fields=["encerrado_em", "atualizado_em"])
    registrar_auditoria(usuario, "encerrar_grupo", grupo, {})


def expirar_grupos_vencidos() -> int:
    """Cancela em bloco os grupos cuja retenção venceu (todas as filhas juntas).
    Roda no cron, junto de expirar_vencidas."""
    from django.db import transaction as _tx

    agora = timezone.now()
    vencidos = GrupoReserva.objects.filter(
        expira_em__lt=agora, encerrado_em__isnull=True
    ).exclude(filhas__status=Reserva.Status.HOSPEDADA)
    n = 0
    for grupo in vencidos:
        tem_ativas = grupo.filhas.filter(status__in=Reserva.STATUS_ATIVOS).exists()
        if not tem_ativas:
            continue
        with _tx.atomic():
            for filha in grupo.filhas.filter(status__in=Reserva.STATUS_ATIVOS):
                filha.status = Reserva.Status.CANCELADA
                filha.motivo_cancelamento = "Pré-reserva de grupo expirada."
                filha.save(update_fields=["status", "motivo_cancelamento"])
            grupo.motivo_cancelamento = "Pré-reserva de grupo expirada (retenção sem confirmação)."
            grupo.save(update_fields=["motivo_cancelamento", "atualizado_em"])
        n += 1
    return n


def saidas_vencidas() -> dict:
    """
    Reservas HOSPEDADA cuja data de saída já passou e que ninguém finalizou
    (esquecimento, virada de turno, hóspede que já foi). Separadas por dinheiro,
    porque o atendente trata cada caso de um jeito:

    - `com_saldo`: tem valor a receber → cobrar no caixa e então fechar (alerta).
    - `quitadas`: conta zerada, só falta formalizar a saída num clique (aviso).

    Fechar é sempre do atendente — este helper só ALIMENTA os avisos do painel,
    não altera nada.
    """
    hoje = timezone.localdate()
    vencidas = (
        Reserva.objects.select_related("uh", "hospede", "conta")
        .filter(status=Reserva.Status.HOSPEDADA, checkout__lt=hoje)
        .exclude(uh__tipo__modalidade=TipoUH.Modalidade.DAY_USE)
        .order_by("checkout", "uh__numero")
    )
    com_saldo, quitadas = [], []
    total_aberto = Decimal("0.00")
    for reserva in vencidas:
        conta = getattr(reserva, "conta", None)
        saldo = conta.saldo() if conta else Decimal("0.00")
        if saldo > Decimal("0.00"):
            total_aberto += saldo
            com_saldo.append(reserva)
        else:
            quitadas.append(reserva)
    return {
        "com_saldo": com_saldo,
        "quitadas": quitadas,
        "total_aberto": total_aberto,
    }


@transaction.atomic
def trocar_quarto(reserva, novo_uh, usuario, motivo=""):
    """
    Move a reserva para outro quarto. A conta (folio) pertence à reserva, então
    diárias, consumo e pagamentos vão junto automaticamente. O antioverbooking
    (ExclusionConstraint) valida se o destino está livre no período.
    """
    if reserva.status not in Reserva.STATUS_ATIVOS:
        raise ValidationError("Só reservas ativas podem trocar de quarto.")
    if novo_uh.pk == reserva.uh_id:
        raise ValidationError("Escolha um quarto diferente do atual.")
    if novo_uh.status != UH.Status.ATIVA:
        raise ValidationError(
            f"O quarto {novo_uh.numero} está {novo_uh.get_status_display().lower()}."
        )
    if novo_uh.pk in _uhs_bloqueio_manutencao(reserva.checkin, reserva.checkout):
        raise ValidationError(
            f"O quarto {novo_uh.numero} está em manutenção no período desta reserva."
        )
    antigo = reserva.uh
    reserva.uh = novo_uh
    try:
        with transaction.atomic():
            reserva.save()
    except IntegrityError:
        raise ValidationError(
            f"O quarto {novo_uh.numero} já tem reserva ativa no período."
        )
    registrar_auditoria(
        usuario, "troca_quarto", reserva,
        {"de": antigo.numero, "para": novo_uh.numero, "motivo": motivo},
    )
    # Quarto antigo foi liberado — Governança gera a faxina.
    from .signals import quarto_liberado

    quarto_liberado.send(
        sender=Reserva, uh=antigo, reserva=reserva, usuario=usuario, origem="troca"
    )
    return reserva


def contas_abertas():
    """Contas de hospedagem abertas de QUARTO (para PDVs lançarem consumo na conta).
    Exclui os folios-mãe de grupo (que não têm reserva/quarto — só diárias)."""
    return (
        ContaHospedagem.objects.filter(
            status=ContaHospedagem.Status.ABERTA, reserva__isnull=False
        )
        .select_related("reserva", "reserva__uh", "reserva__hospede")
        .order_by("reserva__uh__numero")
    )


def conta_aberta(conta_id):
    """Uma conta aberta pelo id, ou None."""
    return (
        ContaHospedagem.objects.filter(
            pk=conta_id, status=ContaHospedagem.Status.ABERTA
        )
        .select_related("reserva", "reserva__uh", "reserva__hospede")
        .first()
    )


@transaction.atomic
def receber_adiantamento(
    reserva: Reserva, usuario, forma: FormaPagamento, valor: Decimal, parcelas: int = 1,
    autorizacao: str = "",
) -> Adiantamento:
    """Adiantamento/sinal antes do check-in — vira crédito na conta."""
    if reserva.status not in (
        Reserva.Status.ORCAMENTO,
        Reserva.Status.PRE_RESERVA,
        Reserva.Status.CONFIRMADA,
    ):
        raise ValidationError("Adiantamento só antes da entrada (check-in).")
    movimento = _receber_no_caixa(
        usuario, forma, valor,
        f"Adiantamento reserva #{reserva.pk} — {reserva.hospede.nome}",
        parcelas, autorizacao=autorizacao,
    )
    return Adiantamento.objects.create(
        reserva=reserva, movimento_caixa=movimento, valor=valor
    )


def resumo_do_dia() -> dict:
    """Indicadores de hoje para o dashboard do núcleo."""
    from django.utils import timezone

    hoje = timezone.localdate()
    uhs_ativas = UH.objects.filter(
        status=UH.Status.ATIVA,
    ).exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE).count()
    # Ocupação = QUARTOS distintos ocupados / quartos ativos. Contar reservas
    # (e não quartos) estoura 100% quando há grupo/duplicidade no mesmo quarto;
    # day-use não entra no mapa dos 24, então fica de fora dos dois lados.
    hospedadas = (
        Reserva.objects.filter(status=Reserva.Status.HOSPEDADA)
        .exclude(uh__tipo__modalidade=TipoUH.Modalidade.DAY_USE)
        .values("uh")
        .distinct()
        .count()
    )
    chegadas = (
        Reserva.objects.select_related("hospede", "uh")
        .filter(
            checkin=hoje,
            status__in=[Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA],
        )
        .order_by("uh__numero")
    )
    saidas = (
        Reserva.objects.select_related("hospede", "uh")
        .filter(checkout=hoje, status=Reserva.Status.HOSPEDADA)
        .order_by("uh__numero")
    )
    return {
        "chegadas_hoje": chegadas.count(),
        "saidas_hoje": saidas.count(),
        "hospedadas": hospedadas,
        "uhs_ativas": uhs_ativas,
        "ocupacao": round(hospedadas * 100 / uhs_ativas) if uhs_ativas else 0,
        "chegadas": list(chegadas[:8]),
        "saidas": list(saidas[:8]),
    }


SITUACOES_QUARTO = {
    "livre": "Livre",
    "ocupada": "Ocupada",
    "chegada": "Chegada hoje",
    "a_limpar": "A limpar",
    "em_limpeza": "Em limpeza",
    "bloqueada": "Bloqueada",
    "inativa": "Inativa",
}


_LIMPEZA_LABEL = {
    "limpa": "Limpo",
    "suja": "Sujo",
    "em_limpeza": "Em limpeza",
    "inspecionada": "Inspecionado",
}


def mapa_quartos_hoje(*, ler_limpeza: bool = True) -> dict:
    """Situação ao vivo de cada UH — mapa de portas / herói do dashboard.

    `ler_limpeza=True` consulta Governança via service (se o módulo estiver ativo).
    Cada item traz: in/out, saldo (hospedada), limpeza, PCD.
    """
    from apps.nucleo.estrutura import capacidade as capacidade_estrutura
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    hoje = timezone.localdate()
    hospedadas = {
        r.uh_id: r
        for r in Reserva.objects.filter(status=Reserva.Status.HOSPEDADA)
        .select_related("hospede", "conta", "grupo")
    }
    chegadas = {
        r.uh_id: r
        for r in Reserva.objects.filter(
            checkin=hoje,
            status__in=[Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA],
        ).select_related("hospede")
    }
    a_limpar = {
        r.uh_id: r
        for r in Reserva.objects.filter(
            checkout=hoje, status=Reserva.Status.CHECKOUT
        ).select_related("hospede")
    }

    limpeza = {}
    if ler_limpeza and modulo_ativo(Modulo.GOVERNANCA):
        from apps.governanca.services import status_por_uh

        limpeza = status_por_uh()

    # Manutenção bloqueia por datas; aqui interessa quem está bloqueado HOJE.
    manutencao_hoje = {}
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao.services import motivos_bloqueio

        manutencao_hoje = motivos_bloqueio()

    quartos, contagem = [], {k: 0 for k in SITUACOES_QUARTO}
    # Mapa operacional = só hospedagem (24 quartos). Day use tem fluxo próprio.
    for uh in (
        UH.objects.select_related("tipo")
        .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
        .order_by("numero")
    ):
        reserva, badge, badge_alerta = None, "", False
        motivo_bloqueio = ""
        if uh.status == UH.Status.INATIVA:
            situacao = "inativa"
        elif uh.status == UH.Status.BLOQUEADA or uh.pk in manutencao_hoje:
            situacao = "bloqueada"
            motivo_bloqueio = manutencao_hoje.get(uh.pk, "")
        elif uh.pk in hospedadas:
            situacao, reserva = "ocupada", hospedadas[uh.pk]
            if reserva.checkout == hoje:
                badge = "saída hoje"
            elif reserva.checkout < hoje:
                # Check-out vencido e ninguém deu baixa — vira alerta operacional.
                badge, badge_alerta = "saída atrasada", True
        elif uh.pk in chegadas:
            situacao, reserva = "chegada", chegadas[uh.pk]
        elif uh.pk in a_limpar:
            situacao, reserva = "a_limpar", a_limpar[uh.pk]
        else:
            situacao = "livre"

        limpeza_cod = limpeza.get(uh.pk) if limpeza else None
        if limpeza and situacao in ("livre", "a_limpar"):
            if limpeza_cod == "suja":
                situacao = "a_limpar"
            elif limpeza_cod == "em_limpeza":
                situacao = "em_limpeza"
            elif limpeza_cod in ("limpa", "inspecionada", None):
                situacao = "livre"

        saldo = None
        periodo = ""
        if reserva:
            periodo = f"{reserva.checkin:%d/%m}→{reserva.checkout:%d/%m}"
            if situacao == "ocupada" and hasattr(reserva, "conta"):
                try:
                    saldo = reserva.conta.saldo()
                except ContaHospedagem.DoesNotExist:
                    saldo = None

        contagem[situacao] += 1
        quartos.append({
            "uh": uh,
            "situacao": situacao,
            "label": SITUACOES_QUARTO[situacao],
            "reserva": reserva,
            "badge": badge,
            "badge_alerta": badge_alerta,
            "motivo_bloqueio": motivo_bloqueio,
            "pcd": uh.pcd,
            "periodo": periodo,
            "saldo": saldo,
            # Saldo compacto para o card do mapa (reais inteiros, ponto de milhar);
            # o valor exato com centavos fica no fólio e na dica.
            "saldo_fmt": (
                "R$ " + f"{saldo:,.0f}".replace(",", ".") if saldo is not None else ""
            ),
            "limpeza_cod": limpeza_cod,
            "limpeza_label": _LIMPEZA_LABEL.get(limpeza_cod or "", ""),
            "tipo_nome": uh.tipo.nome,
            "lotacao": capacidade_estrutura(uh)["maxima_criancas"],
            "grupo": (reserva.grupo.rotulo if reserva and reserva.grupo_id else ""),
        })

    situacoes_filtro = [
        {"cod": cod, "label": label, "n": contagem[cod]}
        for cod, label in SITUACOES_QUARTO.items()
        if contagem[cod] or cod in ("livre", "ocupada")
    ]
    tipos = TipoUH.objects.filter(uhs__isnull=False).distinct().order_by("nome")
    return {
        "quartos": quartos,
        "tipos": tipos,
        "situacoes_filtro": situacoes_filtro,
        "contagem": contagem,
        "hoje": hoje,
        "amanha": hoje + timedelta(days=1),
    }


def dados_graficos() -> dict:
    """Séries para os gráficos do dashboard (ocupação, receita, canais, funil)."""
    from collections import defaultdict

    from django.db.models import Count
    from django.utils import timezone

    from apps.nucleo.models import UH, TipoUH

    from .models import LancamentoConta

    hoje = timezone.localdate()
    dias14 = [hoje + timedelta(days=n) for n in range(14)]
    uhs_ativas = UH.objects.filter(
        status=UH.Status.ATIVA,
    ).exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE).count()

    ativas = list(
        Reserva.objects.filter(
            status__in=Reserva.STATUS_ATIVOS,
            checkin__lt=hoje + timedelta(days=14),
            checkout__gt=hoje,
        ).select_related("uh")
    )

    # 1) Ocupação — próximos 14 dias
    ocup_valores, ocup_labels, ocup_fds = [], [], []
    for d in dias14:
        occ = sum(1 for r in ativas if r.checkin <= d < r.checkout)
        ocup_valores.append(round(occ * 100 / uhs_ativas) if uhs_ativas else 0)
        ocup_labels.append(d.strftime("%d/%m"))
        ocup_fds.append(d.weekday() >= 5)

    # 2) Ocupação média por tipo — próximos 14 dias
    tipos = list(TipoUH.objects.all())
    qtd_tipo = {
        t.pk: UH.objects.filter(tipo=t, status=UH.Status.ATIVA).count() for t in tipos
    }
    tipo_labels, tipo_valores = [], []
    for t in tipos:
        base = qtd_tipo[t.pk] * 14
        occ = sum(
            1
            for r in ativas
            if r.uh.tipo_id == t.pk
            for d in dias14
            if r.checkin <= d < r.checkout
        )
        tipo_labels.append(t.nome)
        tipo_valores.append(round(occ * 100 / base) if base else 0)

    # 3) Receita dos últimos 7 dias — serviço × consumo (folio)
    dias7 = [hoje - timedelta(days=6 - n) for n in range(7)]
    por_dia = defaultdict(lambda: {"servico": 0.0, "consumo": 0.0})
    lanc = LancamentoConta.objects.filter(
        criado_em__date__gte=dias7[0], tipo__in=LancamentoConta.TIPOS_DEBITO
    )
    for lc in lanc:
        por_dia[lc.criado_em.date()][lc.natureza] += float(lc.valor)
    receita_labels = [d.strftime("%d/%m") for d in dias7]
    receita_servico = [round(por_dia[d]["servico"], 2) for d in dias7]
    receita_consumo = [round(por_dia[d]["consumo"], 2) for d in dias7]

    # 4) Origem das reservas (canal) — exclui canceladas/no-show
    rotulos_canal = dict(Reserva.Canal.choices)
    canais = (
        Reserva.objects.exclude(
            status__in=[Reserva.Status.CANCELADA, Reserva.Status.NO_SHOW]
        )
        .values("canal")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    canal_labels = [rotulos_canal.get(c["canal"], c["canal"]) for c in canais]
    canal_valores = [c["n"] for c in canais]

    # 5) Funil de reservas por status
    rotulos_status = dict(Reserva.Status.choices)
    ordem_funil = [
        Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA,
        Reserva.Status.CONFIRMADA, Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT,
    ]
    contagem = {
        row["status"]: row["n"]
        for row in Reserva.objects.values("status").annotate(n=Count("id"))
    }
    funil_labels = [rotulos_status[s] for s in ordem_funil]
    funil_valores = [contagem.get(s, 0) for s in ordem_funil]

    return {
        "ocupacao": {"labels": ocup_labels, "valores": ocup_valores, "fds": ocup_fds},
        "tipos": {"labels": tipo_labels, "valores": tipo_valores},
        "receita": {
            "labels": receita_labels,
            "servico": receita_servico,
            "consumo": receita_consumo,
        },
        "canais": {"labels": canal_labels, "valores": canal_valores},
        "funil": {"labels": funil_labels, "valores": funil_valores},
    }


# ───────────────────────── FNRH (Ficha Nacional de Registro de Hóspedes) ─────────

def _prefill_titular(reserva) -> dict:
    """Dados iniciais da ficha do titular, a partir do cadastro do hóspede."""
    p = reserva.hospede
    hospede = getattr(p, "hospede", None)
    dados = {
        "titular": True,
        "pessoa": p,
        "nome": p.nome,
        "documento_numero": p.documento or "",
        "cpf": p.documento if p.tipo == p.Tipo.FISICA else "",
        "endereco": p.endereco or "",
        "cidade": p.cidade or "",
        "uf": p.uf or "",
        "cep": p.cep or "",
        "telefone": p.telefone or "",
        "email": p.email or "",
    }
    if hospede is not None:
        dados["nascimento"] = hospede.nascimento
        dados["nacionalidade"] = hospede.nacionalidade or "Brasileira"
    return dados


def garantir_fichas_fnrh(reserva):
    """Garante uma ficha por hóspede (titular + acompanhantes = adultos+crianças).
    Cria a do titular pré-preenchida e os slots vazios que faltarem. Idempotente.
    Retorna o queryset das fichas da reserva."""
    from .models import FichaFNRH

    if not reserva.fichas_fnrh.filter(titular=True).exists():
        FichaFNRH.objects.create(reserva=reserva, **_prefill_titular(reserva))
    faltam = reserva.total_hospedes - reserva.fichas_fnrh.count()
    for _ in range(max(0, faltam)):
        FichaFNRH.objects.create(reserva=reserva, titular=False, nome="")
    return reserva.fichas_fnrh.all()


def marcar_fichas_preenchidas(fichas, *, origem, usuario=None):
    """Carimba as fichas salvas com quem/quando/por onde foram preenchidas."""
    from .models import FichaFNRH

    agora = timezone.now()
    for ficha in fichas:
        if not ficha.completa:
            continue
        ficha.origem = origem
        ficha.preenchida_em = agora
        ficha.preenchida_por = usuario if origem == FichaFNRH.Origem.RECEPCAO else None
        ficha.save(update_fields=["origem", "preenchida_em", "preenchida_por"])


def preparar_fnrh(reserva_id):
    """Portal/recepção: garante as fichas da reserva e devolve (reserva, queryset).
    (None, None) se a reserva não existe."""
    reserva = Reserva.objects.filter(pk=reserva_id).first()
    if reserva is None:
        return None, None
    garantir_fichas_fnrh(reserva)
    return reserva, reserva.fichas_fnrh.all()


def fnrh_formset(*, data=None, queryset):
    """Formset das fichas — para o portal editar sem importar forms internos."""
    from .forms import FichaFNRHFormSet

    return FichaFNRHFormSet(data, queryset=queryset)


# ───────────────────────── BOH (Boletim de Ocupação Hoteleira) ───────────────────

def boh_mensal(ano: int, mes: int) -> dict:
    """Agrega os dados da FNRH + ocupação de um mês, no formato do Boletim de
    Ocupação Hoteleira (Embratur). Base: hóspedes que ENTRARAM no mês (check-in no
    período e que de fato se hospedaram). Só lê e soma."""
    import calendar
    from collections import Counter

    from .models import FichaFNRH

    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    dia_seguinte = ultimo + timedelta(days=1)
    entrou = [Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT]

    fichas = FichaFNRH.objects.filter(
        reserva__checkin__gte=primeiro,
        reserva__checkin__lte=ultimo,
        reserva__status__in=entrou,
    ).select_related("reserva")

    nacional, internacional = Counter(), Counter()
    motivo, transporte, sexo = Counter(), Counter(), Counter()
    total_hospedes = 0
    for f in fichas:
        total_hospedes += 1
        pais = (f.pais or "").strip()
        eh_estrangeiro = bool(pais) and pais.lower() not in ("brasil", "brazil")
        if eh_estrangeiro:
            internacional[pais] += 1
        else:
            nacional[(f.uf or "").upper() or "Não informado"] += 1
        motivo[f.get_motivo_viagem_display() or "Não informado"] += 1
        transporte[f.get_meio_transporte_display() or "Não informado"] += 1
        sexo[f.get_sexo_display() or "Não informado"] += 1

    # Ocupação (UH-noites) no mês.
    uhs_hospedagem = UH.objects.filter(
        tipo__modalidade=TipoUH.Modalidade.HOSPEDAGEM
    ).exclude(status=UH.Status.INATIVA).count()
    dias_mes = (dia_seguinte - primeiro).days
    uh_noites_disponiveis = uhs_hospedagem * dias_mes

    reservas_mes = Reserva.objects.filter(
        status__in=entrou, checkin__lt=dia_seguinte, checkout__gt=primeiro,
    )
    uh_noites_ocupadas = 0
    for r in reservas_mes:
        ini = max(r.checkin, primeiro)
        fim = min(r.checkout, dia_seguinte)
        uh_noites_ocupadas += max(0, (fim - ini).days)

    # Chegadas do mês (para permanência média).
    chegadas = list(Reserva.objects.filter(
        status__in=entrou, checkin__gte=primeiro, checkin__lte=ultimo,
    ))
    noites_total = sum(r.noites for r in chegadas)
    permanencia_media = (noites_total / len(chegadas)) if chegadas else 0.0
    taxa = (uh_noites_ocupadas / uh_noites_disponiveis) if uh_noites_disponiveis else 0.0

    def ordena(counter):
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "ano": ano, "mes": mes,
        "periodo": (primeiro, ultimo),
        "total_hospedes": total_hospedes,
        "total_chegadas": len(chegadas),
        "uh_noites_disponiveis": uh_noites_disponiveis,
        "uh_noites_ocupadas": uh_noites_ocupadas,
        "taxa_ocupacao": round(taxa * 100, 1),
        "permanencia_media": round(permanencia_media, 1),
        "nacional": ordena(nacional),
        "internacional": ordena(internacional),
        "motivo": ordena(motivo),
        "transporte": ordena(transporte),
        "sexo": ordena(sexo),
    }


# ───────────────────────── Envio à FNRH Digital (push — estratégia B) ────────────

def enviar_fnrh(reserva) -> bool:
    """Empurra a reserva + fichas para a FNRH Digital via gateway. Idempotente
    (reaproveita ids já obtidos) e best-effort: em falha, marca erro e NÃO levanta —
    a recepção não trava. Retorna True se ficou 'enviada'."""
    import logging

    from . import fnrh_gateway

    log = logging.getLogger(__name__)
    if reserva.fnrh_status == Reserva.SincFNRH.ENVIADA:
        return True
    try:
        gw = fnrh_gateway.get_gateway()
        if not reserva.fnrh_reserva_id:
            reserva.fnrh_reserva_id = gw.criar_reserva(reserva)
        for ficha in reserva.fichas_fnrh.all():
            if not ficha.completa:
                continue
            mudou = []
            if not ficha.fnrh_pessoa_id:
                ficha.fnrh_pessoa_id = gw.criar_pessoa(ficha)
                mudou.append("fnrh_pessoa_id")
            if not ficha.fnrh_hospede_id:
                ficha.fnrh_hospede_id = gw.adicionar_hospede(
                    reserva.fnrh_reserva_id, ficha, ficha.fnrh_pessoa_id
                )
                mudou.append("fnrh_hospede_id")
            if mudou:
                ficha.save(update_fields=mudou)
        gw.checkin(reserva.fnrh_reserva_id)
    except Exception as erro:  # best-effort: registra e segue
        reserva.fnrh_status = Reserva.SincFNRH.ERRO
        reserva.fnrh_erro = str(erro)[:500]
        reserva.save(update_fields=["fnrh_reserva_id", "fnrh_status", "fnrh_erro"])
        log.warning("Envio FNRH falhou (reserva %s): %s", reserva.pk, erro)
        return False
    reserva.fnrh_status = Reserva.SincFNRH.ENVIADA
    reserva.fnrh_sincronizada_em = timezone.now()
    reserva.fnrh_erro = ""
    reserva.save(update_fields=[
        "fnrh_reserva_id", "fnrh_status", "fnrh_sincronizada_em", "fnrh_erro",
    ])
    return True


def fnrh_pendentes_qs():
    """Reservas hospedadas/checkout que ainda não foram aceitas pela FNRH."""
    return Reserva.objects.filter(
        status__in=[Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT],
        fnrh_status__in=[Reserva.SincFNRH.PENDENTE, Reserva.SincFNRH.ERRO],
    )


def diarias_periodo(inicio, fim) -> Decimal:
    """Total de diárias lançadas no folio no período (sempre recebidas pela recepção).
    Interface pública p/ Relatórios não importar LancamentoConta diretamente."""
    from django.db.models import Sum
    return (LancamentoConta.objects.filter(
        criado_em__date__range=(inicio, fim), tipo=LancamentoConta.Tipo.DIARIA
    ).aggregate(t=Sum("valor"))["t"] or Decimal("0"))

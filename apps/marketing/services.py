"""Serviços do módulo Marketing.

Passo 2: o Quadro (7 fases) e as faixas de peças (próximos dias / atrasadas). Sem portões
ainda — a validação de Aprovação/Encerramento entra no Passo 4.
"""
from datetime import timedelta

from django.utils import timezone

from .models import Campanha, PecaCampanha


def quadro_por_fase() -> list[dict]:
    """As 7 colunas do quadro, cada uma com suas campanhas (na ordem das fases)."""
    por_fase: dict[str, list] = {f: [] for f, _ in Campanha.Fase.choices}
    for c in Campanha.objects.select_related("responsavel").all():
        por_fase.setdefault(c.fase, []).append(c)
    return [
        {"fase": f, "label": label, "campanhas": por_fase.get(f, [])}
        for f, label in Campanha.Fase.choices
    ]


def pecas_proximos_dias(dias: int = 7):
    """Peças datadas a sair nos próximos `dias` (ainda não prontas)."""
    hoje = timezone.localdate()
    return (PecaCampanha.objects
            .filter(data__gte=hoje, data__lte=hoje + timedelta(days=dias))
            .exclude(status=PecaCampanha.Status.PRONTA)
            .select_related("campanha").order_by("data")[:20])


def pecas_atrasadas():
    """Peças com data no passado e ainda não prontas — o que já devia ter saído."""
    hoje = timezone.localdate()
    return (PecaCampanha.objects
            .filter(data__lt=hoje)
            .exclude(status=PecaCampanha.Status.PRONTA)
            .select_related("campanha").order_by("data")[:20])


# ── Verba mensal (Passo 3): teto por mês; travada e gasta = soma das campanhas ──
from decimal import Decimal, InvalidOperation  # noqa: E402

from django.db.models import Sum  # noqa: E402

from .models import VerbaMarketing  # noqa: E402


def mes_atual() -> str:
    return timezone.localdate().strftime("%Y-%m")


def _mes_de_campanha(c) -> str:
    """Mês a que a verba TRAVADA da campanha pertence: o do início (quando roda),
    com fallback na aprovação e, por fim, na criação."""
    d = c.inicio or (c.aprovada_em.date() if c.aprovada_em else None) or c.criado_em.date()
    return d.strftime("%Y-%m")


def posicao_verba(mes: str | None = None) -> dict:
    """Foto da verba do mês. Fonte única: teto é cadastrado; travada e gasta são soma.

    - teto     = `VerbaMarketing.tetos[mes]`
    - travada  = Σ `verba_travada` das campanhas do mês, ainda não encerradas
    - gasta    = Σ gastos (comercial) de campanhas COM fluxo de marketing, no mês do gasto
    - **sobra não acumula**: cada mês olha só o seu teto.
    """
    mes = mes or mes_atual()
    verba = VerbaMarketing.atual()
    teto = verba.teto_do_mes(mes)

    # travada conta TODAS as campanhas do mês (uma fonte só). Encerrar não "some" da
    # conta: reduz a própria verba_travada ao que foi gasto (devolve o não gasto).
    travada = Decimal("0.00")
    for c in Campanha.objects.exclude(verba_travada=Decimal("0")):
        if _mes_de_campanha(c) == mes:
            travada += c.verba_travada

    ano, m = int(mes[:4]), int(mes[5:7])
    from apps.comercial.models import GastoDiario
    gasta = (GastoDiario.objects
             .filter(campanha__fluxo__isnull=False, data__year=ano, data__month=m)
             .aggregate(s=Sum("valor"))["s"] or Decimal("0.00"))

    disponivel = teto - travada
    pct = int(round(travada / teto * 100)) if teto else 0
    return {
        "mes": mes, "teto": teto, "travada": travada, "gasta": gasta,
        "disponivel": disponivel, "pct": pct,
        "alerta": bool(teto) and pct >= verba.alerta_pct, "alerta_pct": verba.alerta_pct,
    }


def parse_moeda(valor) -> Decimal:
    """'R$ 18.000,00' / '18000' / '1.600,50' → Decimal. Fonte única de parse de dinheiro
    dos formulários (o campo .js-moeda manda formatado no blur e cru no submit em foco)."""
    s = str(valor or "0").strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s or "0")
    except (InvalidOperation, ValueError):
        raise ValueError("Valor monetário inválido.")


def definir_teto(mes: str, valor) -> VerbaMarketing:
    """Gestor cadastra/edita o teto do mês (a única fonte do número)."""
    try:
        dec = parse_moeda(valor)
    except ValueError:
        raise ValueError("Valor de teto inválido.")
    verba = VerbaMarketing.atual()
    tetos = dict(verba.tetos or {})
    tetos[mes] = str(dec)  # string preserva a precisão do dinheiro no JSON
    verba.tetos = tetos
    verba.save(update_fields=["tetos"])
    return verba


# ── Passo 4: portão POR FASE + avanço no funil (regras invariantes) ───────────
from django.core.exceptions import ValidationError  # noqa: E402
from django.db import transaction  # noqa: E402

from .models import Campanha as _Camp, Comentario, EtapaCampanha, ItemChecklist  # noqa: E402

# Canais oferecidos como pílulas na ficha (o protótipo mostra estes cinco).
CANAIS_PADRAO = ["Instagram", "Meta Ads", "Google", "WhatsApp", "E-mail"]

# Ordem do funil — cada fase "avança" para a próxima (encerrada é terminal).
ORDEM_FASES = [
    Campanha.Fase.IDEIA, Campanha.Fase.PROPOSTA, Campanha.Fase.APROVACAO,
    Campanha.Fase.ESTRUTURACAO, Campanha.Fase.PRODUCAO, Campanha.Fase.NOAR,
    Campanha.Fase.ENCERRADA,
]


def proxima_fase(fase):
    i = ORDEM_FASES.index(fase)
    return ORDEM_FASES[i + 1] if i + 1 < len(ORDEM_FASES) else None


def _tem_pecas(c) -> bool:
    return bool(list(c.pecas.all()))  # usa prefetch quando houver (quadro)


def _todas_pecas_prontas(c) -> bool:
    pecas = list(c.pecas.all())
    return bool(pecas) and all(p.status == PecaCampanha.Status.PRONTA for p in pecas)


def _retro_completa(c) -> bool:
    return all((getattr(c, f) or "").strip()
               for f in ("retro_funcionou", "retro_nao", "retro_diferente"))


# Portão de cada fase = o que ela precisa satisfazer para AVANÇAR.
# (chave, rótulo, obrigatório, auto|None, meta|None)
#   auto(c)->bool  → resolve sozinho a partir dos campos da ficha (não clicável)
#   auto=None      → item manual (marca-se à mão)
#   meta(c)->str   → subtítulo do item (ex.: quem/como concluiu), opcional
PORTOES = {
    Campanha.Fase.IDEIA: [
        ("objetivo", "Ideia descrita em uma frase", True,
         lambda c: bool((c.objetivo or "").strip()), lambda c: "Concluído pela ficha"),
        ("justifica", "Oportunidade ou data que justifica", False, None, None),
    ],
    Campanha.Fase.PROPOSTA: [
        ("publico", "Público-alvo definido", True, lambda c: bool((c.publico or "").strip()), None),
        ("canais", "Canais escolhidos", True, lambda c: bool(c.canais), None),
        ("periodo", "Período (início e fim) definido", True, lambda c: bool(c.inicio and c.fim), None),
        ("verba", "Verba prevista definida", True, lambda c: c.verba_prevista > 0, None),
        ("responsavel", "Responsável atribuído", True, lambda c: bool(c.responsavel_id), None),
    ],
    Campanha.Fase.APROVACAO: [],  # decisão da gerência — o próprio avançar é a aprovação
    Campanha.Fase.ESTRUTURACAO: [
        ("pecas", "Peças/entregáveis planejados", True, _tem_pecas, None),
        ("criativo", "Responsável pela criação", False, lambda c: bool(c.criativo_id), None),
    ],
    Campanha.Fase.PRODUCAO: [
        ("pecas_prontas", "Todas as peças prontas", True, _todas_pecas_prontas, None),
    ],
    Campanha.Fase.NOAR: [
        ("retro", "Retrospectiva preenchida", True, _retro_completa, None),
    ],
    Campanha.Fase.ENCERRADA: [],
}


def _rows_por_chave(campanha) -> dict:
    return {it.chave: it for it in campanha.checks.all()}


def garantir_itens(campanha) -> None:
    """Cria as linhas de ItemChecklist do portão da FASE ATUAL (para marcação/dispensa)."""
    for chave, *_ in PORTOES.get(campanha.fase, []):
        ItemChecklist.objects.get_or_create(campanha=campanha, chave=chave)


def _resolvido(criterio, campanha, row) -> bool:
    _chave, _rot, _obrig, auto, _meta = criterio
    if row and row.dispensado:
        return True
    if auto is None:
        return bool(row and row.feito)
    return bool(auto(campanha))


def portao_da(campanha) -> dict:
    """Estado do portão da fase atual: itens, progresso e se pode avançar."""
    garantir_itens(campanha)
    rows = _rows_por_chave(campanha)
    crit = PORTOES.get(campanha.fase, [])
    itens, feitos, obrig_pendentes = [], 0, []
    for c in crit:
        chave, rotulo, obrig, auto, meta = c
        row = rows.get(chave)
        ok = _resolvido(c, campanha, row)
        if ok:
            feitos += 1
        elif obrig:
            obrig_pendentes.append(rotulo)
        itens.append({
            "chave": chave, "rotulo": rotulo, "obrigatorio": obrig,
            "resolvido": ok, "dispensado": bool(row and row.dispensado),
            "manual": auto is None,
            "meta": (meta(campanha) if meta and ok else ""),
        })
    prox = proxima_fase(campanha.fase)
    if prox is None:
        label = ""
    elif prox == Campanha.Fase.ENCERRADA:
        label = "Finalizar campanha"
    else:
        label = f"Avançar para {Campanha.Fase(prox).label}"
    return {
        "fase": campanha.fase, "fase_nome": Campanha.Fase(campanha.fase).label,
        "itens": itens, "feitos": feitos, "total": len(crit),
        "obrig_pendentes": obrig_pendentes,
        "pode_avancar": not obrig_pendentes and prox is not None,
        "eh_aprovacao": campanha.fase == Campanha.Fase.APROVACAO,
        "proxima": prox, "proxima_nome": (Campanha.Fase(prox).label if prox else ""),
        "avancar_label": label,
    }


def progresso_portao(campanha) -> tuple:
    """(feitos, total, completo) do portão atual — leitura, sem criar linhas (usa prefetch)."""
    rows = _rows_por_chave(campanha)
    crit = PORTOES.get(campanha.fase, [])
    feitos = sum(1 for c in crit if _resolvido(c, campanha, rows.get(c[0])))
    total = len(crit)
    return feitos, total, (feitos >= total)


def marcar_item(item, usuario, feito=True):
    item.feito = feito
    item.por = usuario
    item.em = timezone.now() if feito else None
    item.save()
    return item


def dispensar_item(item, usuario, motivo):
    """Gestor dispensa um item obrigatório (com motivo registrado). Todos dispensáveis (decisão E)."""
    item.dispensado = True
    item.motivo_dispensa = motivo or ""
    item.por = usuario
    item.em = timezone.now()
    item.save()
    return item


def _garantir_anuncio(campanha, usuario):
    """Cria/garante a comercial.Campanha (origem que os leads usam). Embrulhar (decisão A)."""
    from django.utils.text import slugify

    from apps.comercial.models import Campanha as CampAnuncio
    base = slugify(campanha.nome)[:60] or f"mkt-{campanha.pk}"
    codigo, i = base, 1
    while CampAnuncio.objects.filter(codigo=codigo).exists():
        i += 1
        codigo = f"{base}-{i}"[:80]
    return CampAnuncio.objects.create(
        nome=campanha.nome, codigo=codigo, provedor=CampAnuncio.Provedor.OUTRO,
        ativa=True, criado_por=usuario)


def _aplicar_aprovacao(campanha, usuario):
    """Trava a verba no teto do mês + garante o anúncio (origem dos leads). Valida antes."""
    mes = _mes_de_campanha(campanha)
    disponivel = posicao_verba(mes)["disponivel"]
    if campanha.verba_prevista > disponivel:
        raise ValidationError(
            f"Verba insuficiente no teto de {mes}: disponível R$ {disponivel}, "
            f"a campanha pede R$ {campanha.verba_prevista}.")
    if not campanha.anuncio_id:
        campanha.anuncio = _garantir_anuncio(campanha, usuario)
    campanha.verba_travada = campanha.verba_prevista
    campanha.aprovada_por = usuario
    campanha.aprovada_em = timezone.now()


def avancar(campanha, usuario):
    """Move a campanha UMA fase adiante, cobrando o portão e aplicando o efeito da transição.

    Aprovação→Estruturação é a aprovação (só gerência): trava a verba no teto do mês.
    No ar→Encerrada é a finalização: devolve o não gasto. Ambas validam antes de gravar,
    em transação — o mês nunca fica comprometido por uma transição que não passou.
    """
    from apps.nucleo.permissoes import eh_gerente
    prox = proxima_fase(campanha.fase)
    if prox is None:
        raise ValidationError("Campanha já encerrada.")
    port = portao_da(campanha)
    if port["obrig_pendentes"]:
        raise ValidationError("Falta para avançar: " + ", ".join(port["obrig_pendentes"]) + ".")
    with transaction.atomic():
        if campanha.fase == Campanha.Fase.APROVACAO:
            if not eh_gerente(usuario):
                raise ValidationError("Apenas a gerência aprova campanhas.")
            _aplicar_aprovacao(campanha, usuario)
        elif prox == Campanha.Fase.ENCERRADA:
            campanha.verba_travada = campanha.gasta  # devolve o não gasto ao mês
        campanha.fase = prox
        campanha.save()
    return campanha


def retroceder(campanha, fase_destino, usuario=None):
    """Volta a campanha a uma fase anterior (ex.: 'Reprovar' → Proposta).

    Descer abaixo de Aprovação destrava a verba (aprovada_por/verba_travada zerados)."""
    if fase_destino not in Campanha.Fase.values:
        return campanha
    if ORDEM_FASES.index(fase_destino) >= ORDEM_FASES.index(campanha.fase):
        return campanha
    with transaction.atomic():
        if ORDEM_FASES.index(fase_destino) < ORDEM_FASES.index(Campanha.Fase.APROVACAO):
            campanha.verba_travada = Decimal("0.00")
            campanha.aprovada_por = None
            campanha.aprovada_em = None
        campanha.fase = fase_destino
        campanha.save()
    return campanha


# Papéis, canais, etapas e conversa da ficha ─────────────────────────────────
# fornecedor é texto (CharField); os outros três são FK a usuário.
PAPEIS = [
    ("solicitante", "SOLICITANTE", "quem pediu a campanha"),
    ("responsavel", "RESPONSÁVEL", "quem responde por ela"),
    ("criativo", "CRIATIVO", "quem produz as peças"),
    ("fornecedor", "FORNECEDOR", "quem executa ou veicula"),
]


def usuarios_equipe():
    from django.contrib.auth import get_user_model
    U = get_user_model()
    return U.objects.filter(is_active=True).order_by("first_name", "username")


def atribuir_papel(campanha, papel, valor):
    """Define solicitante/responsavel/criativo (id de usuário) ou fornecedor (texto)."""
    if papel == "fornecedor":
        campanha.fornecedor = (valor or "").strip()
        campanha.save(update_fields=["fornecedor"])
        return campanha
    if papel not in ("solicitante", "responsavel", "criativo"):
        return campanha
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=valor).first() if valor else None
    setattr(campanha, papel, user)
    campanha.save(update_fields=[papel])
    return campanha


def alternar_canal(campanha, canal):
    canal = (canal or "").strip()
    if not canal:
        return campanha
    atuais = list(campanha.canais or [])
    atuais.remove(canal) if canal in atuais else atuais.append(canal)
    campanha.canais = atuais
    campanha.save(update_fields=["canais"])
    return campanha


def adicionar_etapa(campanha, texto, dono_id=None, prazo=None):
    texto = (texto or "").strip()
    if not texto:
        return None
    dono = None
    if dono_id:
        from django.contrib.auth import get_user_model
        dono = get_user_model().objects.filter(pk=dono_id).first()
    return EtapaCampanha.objects.create(
        campanha=campanha, texto=texto, dono=dono, prazo=prazo or None)


def alternar_etapa(etapa):
    etapa.feito = not etapa.feito
    etapa.save(update_fields=["feito"])
    return etapa


def remover_etapa(etapa):
    etapa.delete()


def adicionar_comentario(campanha, autor, texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    return Comentario.objects.create(campanha=campanha, autor=autor, texto=texto)


# ── Passo 5: peças datadas → calendário (mês e ano) ──────────────────────────
import calendar as _calendar  # noqa: E402

from apps.nucleo.periodos import MESES_PT  # noqa: E402


def pecas_no_mes(ano: int, mes: int):
    return (PecaCampanha.objects.filter(data__year=ano, data__month=mes)
            .select_related("campanha").order_by("data"))


def calendario_mes(ano: int, mes: int) -> list:
    """Grade de semanas (domingo→sábado); cada dia traz suas peças (pontos no calendário)."""
    semanas = _calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes)
    por_dia: dict[int, list] = {}
    for p in pecas_no_mes(ano, mes):
        por_dia.setdefault(p.data.day, []).append(p)
    grade = []
    for semana in semanas:
        grade.append([
            {"dia": dia, "pecas": por_dia.get(dia, []) if dia else []}
            for dia in semana
        ])
    return grade


def calendario_ano(ano: int) -> list:
    """12 colunas: contagem de peças por mês do ano."""
    por_mes = {m: 0 for m in range(1, 13)}
    for p in PecaCampanha.objects.filter(data__year=ano):
        por_mes[p.data.month] += 1
    return [{"mes": m, "nome": MESES_PT[m], "n": por_mes[m]} for m in range(1, 13)]


# ── Calendário como LINHA DO TEMPO (Gantt) — campanha é intervalo, não dia ─────
# Cor por fase usando SÓ tokens do app.css (o app.css vence o pastel do protótipo).
FASE_COR = {
    Campanha.Fase.IDEIA: ("var(--superficie-2)", "var(--tinta-suave)"),
    Campanha.Fase.PROPOSTA: ("var(--alerta-bg)", "var(--alerta)"),
    Campanha.Fase.APROVACAO: ("var(--perigo-bg)", "var(--perigo)"),
    Campanha.Fase.ESTRUTURACAO: ("var(--info-bg)", "var(--info)"),
    Campanha.Fase.PRODUCAO: ("var(--superficie-2)", "var(--madeira)"),
    Campanha.Fase.NOAR: ("var(--sucesso-bg)", "var(--sucesso)"),
    Campanha.Fase.ENCERRADA: ("var(--superficie-2)", "var(--tinta-suave)"),
}


def _2a_domingo(ano, mes):
    """2º domingo do mês (Dia das Mães = maio, Dia dos Pais = agosto)."""
    from datetime import date as _d
    d = _d(ano, mes, 1)
    primeiro_dom = 1 + (6 - d.weekday()) % 7  # weekday(): seg=0..dom=6
    return _d(ano, mes, primeiro_dom + 7)


def marcos_do_periodo(de, ate):
    """Datas que puxam reserva (feriados/sazonais) dentro da janela — para os ticks tracejados."""
    from datetime import date as _d
    anos = range(de.year, ate.year + 1)
    fixos = [(1, 1, "Ano-Novo"), (4, 21, "Tiradentes"), (6, 12, "Namorados"),
             (9, 7, "Independência"), (10, 12, "N. Sra./Criança"), (11, 2, "Finados"),
             (11, 15, "República"), (12, 25, "Natal"), (12, 31, "Réveillon")]
    out = []
    for a in anos:
        for mes, dia, nome in fixos:
            out.append((_d(a, mes, dia), nome))
        out.append((_2a_domingo(a, 5), "Dia das Mães"))
        out.append((_2a_domingo(a, 8), "Dia dos Pais"))
    return sorted((d, n) for d, n in out if de <= d <= ate)


def calendario_timeline(ano: int, mes: int, escala: str = "mes") -> dict:
    """Linha do tempo: uma linha por campanha, barra cobrindo a vigência.

    Espelha o protótipo (buildCalendario): janela = mês (N dias) ou ano (12 meses);
    posição em % da trilha; barra hachurada = futuro (planejado), cheia = passado
    (realizado); a linha vermelha de HOJE corta a barra; peças são pontos; marcos são
    ticks tracejados. Tudo em tokens do app.css.
    """
    from datetime import date as _d
    hoje = timezone.localdate()
    por_ano = escala == "ano"

    if por_ano:
        de, ate = _d(ano, 1, 1), _d(ano, 12, 31)
        cols = [{"label": MESES_PT[i][:3].lower(), "hoje": (i == hoje.month and ano == hoje.year)}
                for i in range(1, 13)]
        titulo = str(ano)
    else:
        n = _calendar.monthrange(ano, mes)[1]
        de, ate = _d(ano, mes, 1), _d(ano, mes, n)
        cols = [{"label": str(i),
                 "hoje": (i == hoje.day and mes == hoje.month and ano == hoje.year)}
                for i in range(1, n + 1)]
        titulo = f"{MESES_PT[mes]} {ano}"
    total = len(cols)

    def pos(d):
        if por_ano:
            nd = _calendar.monthrange(d.year, d.month)[1]
            return ((d.month - 1) + (d.day - 1) / nd) / 12 * 100
        return (d.day - 1) / total * 100

    def clamp(x):
        return max(0.0, min(100.0, x))

    passo = 0.3 if por_ano else 100 / total

    linhas = []
    camps = (Campanha.objects.select_related("responsavel")
             .prefetch_related("pecas")
             .filter(inicio__isnull=False, fim__isnull=False,
                     inicio__lte=ate, fim__gte=de).order_by("inicio"))
    for c in camps:
        ini = max(c.inicio, de)
        fim = min(c.fim, ate)
        e = clamp(pos(ini))
        f = clamp(pos(fim) + passo)
        largura = max(1.2, f - e)
        futuro = c.inicio > hoje
        corte = clamp(pos(hoje)) if (c.inicio <= hoje <= c.fim) else None
        bg, fg = FASE_COR.get(c.fase, FASE_COR[Campanha.Fase.IDEIA])
        resp = ((c.responsavel.get_full_name() or c.responsavel.username)
                if c.responsavel else "sem responsável")
        pecas = []
        for p in c.pecas.all():
            if p.data and de <= p.data <= ate:
                cor = ("var(--sucesso)" if p.status == PecaCampanha.Status.PRONTA
                       else "var(--perigo)" if p.data < hoje else "var(--lampiao)")
                pecas.append({"left": round(clamp(pos(p.data)), 2), "cor": cor,
                              "dica": f"{p.nome} · {p.canal or 'sem canal'} · {p.data:%d/%m}"})
        linhas.append({
            "id": c.pk, "nome": c.nome or "(sem nome)",
            "sub": f"{resp} · {c.inicio:%d/%m} a {c.fim:%d/%m}",
            "left": round(e, 2), "width": round(largura, 2),
            "bg": bg, "fg": fg, "hachurado": futuro,
            "rotulo": c.nome if largura >= (len(c.nome or "") * 6 + 22) / 7 else "",
            "corte": round(corte, 2) if corte is not None else None,
            "pecas": pecas,
            "dica": (f"{c.nome} · {c.get_fase_display()}\n{c.inicio:%d/%m} a {c.fim:%d/%m}"
                     f"\n{resp}" + ("\nainda não começou" if futuro else "")),
        })

    marcos = []
    linha_col = [-999.0, -999.0]
    for i, (d, nome) in enumerate(marcos_do_periodo(de, ate)):
        x = clamp(pos(d))
        linha = i % 2
        larg = (len(nome) * 6 + 8) / 7
        cabe = (x - linha_col[linha]) > larg
        if cabe:
            linha_col[linha] = x
        meia = larg / 2
        if x < meia:
            ancora = "left:0;transform:none"
        elif x > 100 - meia:
            ancora = "left:100%;transform:translateX(-100%)"
        else:
            ancora = f"left:{x:.2f}%;transform:translateX(-50%)"
        marcos.append({
            "left": round(x, 2), "nome": nome if cabe else "",
            "top": linha * 15 + 2, "ancora": ancora,
            "dica": f"{nome}\n{d:%d/%m} · data que puxa reserva",
        })

    return {"escala": escala, "titulo": titulo, "cols": cols, "linhas": linhas,
            "marcos": marcos, "vazio": not linhas}


# ── Passo 6: gastos datados + relatório (mês/ano) ────────────────────────────
def lancar_gasto(campanha, data, valor, usuario):
    """Lança um gasto DATADO — fonte única `comercial.GastoDiario`. Garante o anúncio antes."""
    from apps.comercial.services import registrar_gasto
    if not campanha.anuncio_id:
        campanha.anuncio = _garantir_anuncio(campanha, usuario)
        campanha.save(update_fields=["anuncio"])
    return registrar_gasto(campanha=campanha.anuncio, data=data, valor=valor, usuario=usuario)


def _meses_entre(inicio, fim) -> list[str]:
    y, m, out = inicio.year, inicio.month, []
    while (y, m) <= (fim.year, fim.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _retorno_rastreado(anuncio_id):
    """Receita RASTREADA: leads ganhos atribuídos à campanha (via anúncio). E o nº de fechamentos."""
    from apps.comercial.models import Oportunidade
    qs = Oportunidade.objects.filter(campanha_id=anuncio_id, status=Oportunidade.Status.GANHA)
    receita = qs.aggregate(s=Sum("valor_estimado"))["s"] or Decimal("0.00")
    return receita, qs.count()


def _retorno_janela(campanha):
    """Receita ESTIMADA por janela: ganhos com check-in na vigência (coincidência de calendário)."""
    if not (campanha.inicio and campanha.fim):
        return Decimal("0.00")
    from apps.comercial.models import Oportunidade
    return (Oportunidade.objects.filter(
        status=Oportunidade.Status.GANHA,
        checkin_previsto__gte=campanha.inicio, checkin_previsto__lte=campanha.fim)
        .aggregate(s=Sum("valor_estimado"))["s"] or Decimal("0.00"))


def relatorio(inicio, fim) -> dict:
    """Relatório do período. Gasto entra no mês em que o dinheiro saiu (data do GastoDiario).

    Retorno **rastreado** (leads atribuídos) e **estimado por janela** aparecem SEPARADOS e
    nunca somados; as campanhas são ordenadas pela **rastreada**. CAC = gasto por FECHAMENTO.
    """
    from apps.comercial.models import GastoDiario
    verba = VerbaMarketing.atual()
    teto = sum((verba.teto_do_mes(m) for m in _meses_entre(inicio, fim)), Decimal("0.00"))
    gasto = (GastoDiario.objects.filter(campanha__fluxo__isnull=False,
             data__gte=inicio, data__lte=fim).aggregate(s=Sum("valor"))["s"] or Decimal("0.00"))
    sobra = teto - gasto
    hoje = timezone.localdate()
    dias = max((min(fim, hoje) - inicio).days + 1, 1)
    ritmo = (gasto / dias).quantize(Decimal("0.01")) if gasto else Decimal("0.00")

    linhas = []
    for mc in Campanha.objects.filter(anuncio__isnull=False).select_related("anuncio"):
        g = (GastoDiario.objects.filter(campanha_id=mc.anuncio_id,
             data__gte=inicio, data__lte=fim).aggregate(s=Sum("valor"))["s"] or Decimal("0.00"))
        rastreada, fechos = _retorno_rastreado(mc.anuncio_id)
        janela = _retorno_janela(mc)
        if not (g or rastreada or janela):
            continue
        linhas.append({
            "nome": mc.nome, "gasto": g, "rastreada": rastreada, "janela": janela,
            "fechamentos": fechos,
            "cac": (g / fechos).quantize(Decimal("0.01")) if fechos else None,
        })
    linhas.sort(key=lambda x: x["rastreada"], reverse=True)  # ordena pela RASTREADA
    return {"teto": teto, "gasto": gasto, "sobra": sobra, "ritmo": ritmo, "linhas": linhas}


# ── Passo 7: atribuição de lead (campanha vigente) ───────────────────────────
# Só é "vigente" quem está de fato rodando: estruturação / produção / no ar
# (ideia/proposta/aprovação ainda não captam; encerrada não capta mais).
FASES_VIGENTES = (Campanha.Fase.ESTRUTURACAO, Campanha.Fase.PRODUCAO, Campanha.Fase.NOAR)


def campanha_vigente(canal=None, quando=None):
    """A campanha de marketing vigente para o canal na data (com anúncio para prender o lead).

    Sobreposição resolve pela mais recente. Sem vigente → None (o lead fica 'Orgânico').
    """
    dia = quando or timezone.localdate()
    if hasattr(dia, "date"):
        dia = dia.date()
    candidatas = []
    for c in (Campanha.objects.filter(fase__in=FASES_VIGENTES, anuncio__isnull=False,
              inicio__lte=dia, fim__gte=dia)):
        canais = c.canais or []
        if canal and canais and canal not in canais:
            continue
        candidatas.append(c)
    if not candidatas:
        return None
    candidatas.sort(key=lambda c: c.inicio, reverse=True)  # mais recente vence
    return candidatas[0]


# ── Passo 8: funil de aquisição (reflete a conversão/perda do comercial) ──────
def aquisicao(campanha) -> dict:
    """Resumo dos leads atribuídos à campanha: quantos entraram, fecharam, perderam.

    Reflete o funil comercial (não o reimplementa): conversão vem de `converter_em_reserva`
    (status GANHA + reserva_id — a origem viaja junto) e a perda traz o motivo. CAC = gasto
    por FECHAMENTO. Receita = valor dos ganhos (rastreada).
    """
    from django.db.models import Count

    from apps.comercial.models import Oportunidade
    vazio = {"total": 0, "abertos": 0, "ganhos": 0, "perdidos": 0,
             "receita": Decimal("0.00"), "conversao": 0, "cac": None, "motivos": []}
    if not campanha.anuncio_id:
        return vazio
    qs = Oportunidade.objects.filter(campanha_id=campanha.anuncio_id)
    total = qs.count()
    ganhos_qs = qs.filter(status=Oportunidade.Status.GANHA)
    ganhos = ganhos_qs.count()
    perdidos = qs.filter(status=Oportunidade.Status.PERDIDA).count()
    abertos = qs.filter(status=Oportunidade.Status.ABERTA).count()
    receita = ganhos_qs.aggregate(s=Sum("valor_estimado"))["s"] or Decimal("0.00")
    gasto = campanha.gasta
    motivos = [
        {"motivo": m["motivo_perda__nome"] or "—", "n": m["n"]}
        for m in (qs.filter(status=Oportunidade.Status.PERDIDA)
                  .values("motivo_perda__nome").annotate(n=Count("id")).order_by("-n"))
    ]
    return {
        "total": total, "abertos": abertos, "ganhos": ganhos, "perdidos": perdidos,
        "receita": receita,
        "conversao": int(round(ganhos / total * 100)) if total else 0,
        "cac": (gasto / ganhos).quantize(Decimal("0.01")) if ganhos else None,
        "motivos": motivos,
    }


# ── Passo 9: ocupação × campanha (próximos 90 dias) ──────────────────────────
def ocupacao_x_campanha(dias: int = 91) -> list[dict]:
    """Cruza a ocupação semanal dos próximos `dias` com a vigência das campanhas.

    Distingue os dois casos que pareciam um:
      - **oportunidade**: semana vazia SEM campanha → onde anunciar rende mais;
      - **problema**: semana vazia COM campanha ativa → o problema é a campanha, não a falta dela.
    A barra é em **escala absoluta** (0–100%); o branco (o vazio) é a informação.
    """
    from apps.reservas.services import ocupacao_prevista
    hoje = timezone.localdate()
    fim_janela = hoje + timedelta(days=dias)
    camps = list(Campanha.objects.filter(
        fase__in=FASES_VIGENTES, anuncio__isnull=False,
        inicio__lte=fim_janela, fim__gte=hoje))

    def campanhas_da(ini, fim):
        return [c for c in camps if c.inicio <= fim and c.fim >= ini]

    blocos = []
    for i in range(dias // 7):
        ini = hoje + timedelta(days=i * 7)
        fim = ini + timedelta(days=6)
        oc = ocupacao_prevista(ini, fim)   # janela futura conta confirmadas
        taxa = float(oc["taxa"])
        livres = int(oc["disponiveis"]) - int(oc["ocupadas"])
        nas = campanhas_da(ini, fim)
        if taxa < 50:
            situacao = "problema" if nas else "oportunidade"
        else:
            situacao = "ok"
        blocos.append({
            "inicio": ini, "fim": fim, "taxa": taxa, "livres": livres,
            "tem_campanha": bool(nas), "situacao": situacao,
            "campanhas": ", ".join(c.nome for c in nas),
            "rotulo": f"{ini:%d/%m}",
        })
    return blocos


def marcos_ocupacao(dias: int = 91) -> list[dict]:
    """Datas que puxam reserva na janela + se já há campanha cobrindo cada uma."""
    hoje = timezone.localdate()
    fim_janela = hoje + timedelta(days=dias)
    camps = list(Campanha.objects.filter(
        fase__in=FASES_VIGENTES, anuncio__isnull=False,
        inicio__lte=fim_janela, fim__gte=hoje))
    out = []
    for d, nome in marcos_do_periodo(hoje, fim_janela):
        cobre = any(c.inicio <= d <= c.fim for c in camps)
        faltam = (d - hoje).days
        out.append({
            "nome": nome, "quando": f"{d:%d/%m} · em {faltam} dia{'s' if faltam != 1 else ''}",
            "coberta": cobre,
            "estado": "campanha no ar" if cobre else "sem campanha ainda",
        })
    return out


# ── Passo 10: duplicar campanha ──────────────────────────────────────────────
def duplicar(campanha, usuario):
    """Clona uma campanha para reaproveitar o planejamento — resetando o que não se herda.

    Herda: nome (+ cópia), objetivo, público, canais, verba prevista, responsável/criação,
    fornecedor, peças (sem data, a fazer) e tarefas (reabertas).
    Reseta: fase → ideia, sem verba travada, sem anúncio/leads/gastos, sem datas, sem
    aprovação e sem retrospectiva (uma campanha nova não herda o histórico da anterior).
    """
    from .models import EtapaCampanha
    nova = Campanha.objects.create(
        nome=f"{campanha.nome} (cópia)",
        objetivo=campanha.objetivo, publico=campanha.publico,
        canais=list(campanha.canais or []),
        verba_prevista=campanha.verba_prevista,
        responsavel=campanha.responsavel, criativo=campanha.criativo,
        fornecedor=campanha.fornecedor, solicitante=usuario,
        fase=Campanha.Fase.IDEIA,
        # reset explícito (defaults já cuidam, mas deixo claro):
        verba_travada=Decimal("0.00"), anuncio=None, aprovada_por=None, aprovada_em=None,
        retro_funcionou="", retro_nao="", retro_diferente="", inicio=None, fim=None,
    )
    for p in campanha.pecas.all():
        PecaCampanha.objects.create(
            campanha=nova, nome=p.nome, canal=p.canal, data=None,
            status=PecaCampanha.Status.A_FAZER)
    for e in campanha.etapas.all():
        EtapaCampanha.objects.create(
            campanha=nova, texto=e.texto, dono=None, prazo=None, feito=False)
    return nova


# ── Quadro rico (visual do protótipo) ────────────────────────────────────────
SUBTITULO_FASE = {
    Campanha.Fase.IDEIA: "pauta bruta, sem compromisso",
    Campanha.Fase.PROPOSTA: "objetivo, público, estimativa",
    Campanha.Fase.APROVACAO: "na mesa do gestor",
    Campanha.Fase.ESTRUTURACAO: "montando as peças",
    Campanha.Fase.PRODUCAO: "criativos em produção",
    Campanha.Fase.NOAR: "campanha rodando",
    Campanha.Fase.ENCERRADA: "com retrospectiva",
}


def motivos_meus(user) -> dict:
    """Por que cada campanha é 'minha' — 4 vínculos (id → lista de motivos, por prioridade).

    (1) gestor e ela espera aprovação; (2) você é o responsável; (3) você pediu
    (solicitante); (4) você tem tarefa aberta nela. Uma fonte só: contador e filtro
    do 'Só os meus' consomem esta mesma função (senão divergem)."""
    from collections import Counter

    from apps.nucleo.permissoes import eh_gerente

    from .models import EtapaCampanha
    motivos: dict = {}

    def add(cid, texto):
        motivos.setdefault(cid, [])
        if texto not in motivos[cid]:
            motivos[cid].append(texto)

    if eh_gerente(user):
        for cid in Campanha.objects.filter(fase=Campanha.Fase.APROVACAO).values_list("id", flat=True):
            add(cid, "espera sua aprovação")
    for cid in Campanha.objects.filter(responsavel=user).values_list("id", flat=True):
        add(cid, "você responde por ela")
    for cid in Campanha.objects.filter(solicitante=user).values_list("id", flat=True):
        add(cid, "você pediu")
    cont = Counter(EtapaCampanha.objects.filter(dono=user, feito=False)
                   .values_list("campanha_id", flat=True))
    for cid, n in cont.items():
        add(cid, f"{n} tarefa{'s' if n != 1 else ''} sua{'s' if n != 1 else ''}")
    return motivos


def meus_resumo(user) -> tuple:
    """(total, rótulo) do botão 'Só os meus' — ex.: (4, '4 campanhas · 1 a aprovar')."""
    from .models import EtapaCampanha
    mot = motivos_meus(user)
    total = len(mot)
    if not total:
        return 0, "nada atribuído a você"
    aprovar = sum(1 for ms in mot.values() if "espera sua aprovação" in ms)
    tarefas = EtapaCampanha.objects.filter(dono=user, feito=False).count()
    rot = f"{total} campanha{'s' if total != 1 else ''}"
    if aprovar:
        rot += f" · {aprovar} a aprovar"
    if tarefas:
        rot += f" · {tarefas} tarefa{'s' if tarefas != 1 else ''}"
    return total, rot


def quadro_colunas(minhas=None) -> list[dict]:
    """As 7 colunas com cards ricos. `minhas` (dict id→motivos) liga o filtro 'Só os meus':
    mostra só as minhas, anexa o motivo (âmbar) e conta as escondidas por coluna."""
    so_meus = minhas is not None
    cols = []
    for fase, label in Campanha.Fase.choices:
        qs = (Campanha.objects.filter(fase=fase).select_related("responsavel")
              .prefetch_related("checks", "etapas", "pecas"))
        todas = list(qs)
        visiveis = [c for c in todas if c.id in minhas] if so_meus else todas
        escondidas = len(todas) - len(visiveis)
        cards, total = [], Decimal("0.00")
        for c in visiveis:
            total += c.verba_prevista
            feitos, tot_ck, check_completo = progresso_portao(c)
            etapas = list(c.etapas.all())
            abertas = sum(1 for e in etapas if not e.feito)
            pecas = list(c.pecas.all())
            prontas = sum(1 for p in pecas if p.status == PecaCampanha.Status.PRONTA)
            cards.append({
                "obj": c, "codigo": c.codigo, "iniciais": c.iniciais,
                "responsavel": (c.responsavel.get_full_name() or c.responsavel.username)
                if c.responsavel else "sem responsável",
                "canais": c.canais or [],
                "verba": c.verba_prevista,
                "pct_check": int(feitos / tot_ck * 100) if tot_ck else 100,
                "check_texto": f"{feitos}/{tot_ck}", "check_completo": check_completo,
                "etapas_abertas": abertas,
                "tem_pecas": bool(pecas),
                "pct_pecas": int(prontas / len(pecas) * 100) if pecas else 0,
                "pecas_texto": f"{prontas}/{len(pecas)}",
                "motivo_meu": " · ".join(minhas.get(c.id, [])) if so_meus else "",
            })
        if so_meus and escondidas:
            vazio = f"Nada seu aqui · {escondidas} campanha{'s' if escondidas != 1 else ''} de outra{'s' if escondidas != 1 else ''} pessoa{'s' if escondidas != 1 else ''}"
        else:
            vazio = "Nada nesta fase."
        cols.append({
            "fase": fase, "label": label, "sub": SUBTITULO_FASE.get(fase, ""),
            "total": total, "conta": len(cards),
            "portao": fase in (Campanha.Fase.APROVACAO, Campanha.Fase.ENCERRADA),
            "cards": cards, "vazio_texto": vazio,
        })
    return cols


def _resp_de(campanha) -> str:
    u = campanha.responsavel
    return (u.get_full_name() or u.username) if u else "sem responsável"


def banda_proximos(dias: int = 7) -> list[dict]:
    """Peças de hoje até domingo (7 dias), não prontas — a agenda da semana."""
    hoje = timezone.localdate()
    out = []
    for p in pecas_proximos_dias(dias):
        hoje_flag = p.data == hoje
        out.append({
            "id": p.campanha_id, "nome": p.nome, "campanha": p.campanha.nome,
            "canal": p.canal or "—", "responsavel": _resp_de(p.campanha),
            "quando": "sai hoje" if hoje_flag else p.data.strftime("%d/%m"),
            "hoje": hoje_flag,
        })
    return out


def resumo_proximos(dias: int = 7) -> str:
    """'N hoje · M até domingo' (ou 'nada hoje')."""
    hoje = timezone.localdate()
    itens = list(pecas_proximos_dias(dias))
    h = sum(1 for p in itens if p.data == hoje)
    a2 = len(itens) - h
    txt = f"{h} hoje" if h else "nada hoje"
    if a2:
        txt += f" · {a2} até domingo"
    return txt


def banda_atrasados() -> list[dict]:
    """Peças vencidas e não prontas — o painel de atrasos (selo PEÇA)."""
    hoje = timezone.localdate()
    out = []
    for p in pecas_atrasadas():
        d = (hoje - p.data).days
        out.append({
            "id": p.campanha_id, "texto": p.nome, "canal": p.canal or "—",
            "campanha": p.campanha.nome, "dono": _resp_de(p.campanha), "tipo": "PEÇA",
            "desde": f"há {d} dia{'s' if d != 1 else ''}" if d else "agora",
        })
    return out

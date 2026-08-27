"""
Regras da Escala. Interface pública para as views (e futura integração:
Governança/Manutenção poderão atribuir tarefas a quem está de turno).
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from .models import Atribuicao, Ausencia, TrocaTurno


def inicio_da_semana(data=None):
    data = data or timezone.localdate()
    return data - timedelta(days=data.weekday())  # segunda-feira


def ausencia_no_dia(funcionario, data):
    return funcionario.ausencias.filter(inicio__lte=data, fim__gte=data).first()


def resumo_funcionario(funcionario, inicio, fim):
    """Dias/horas trabalhados, ausências e trocas do funcionário no período.
    Interface pública — o Histórico do funcionário (núcleo) consome daqui."""
    from datetime import datetime

    from django.db.models import Q

    atribs = (
        Atribuicao.objects
        .filter(funcionario=funcionario, data__range=(inicio, fim))
        .select_related("turno")
    )
    horas = 0.0
    for a in atribs:
        seg = (
            datetime.combine(inicio, a.turno.fim)
            - datetime.combine(inicio, a.turno.inicio)
        ).total_seconds()
        if seg <= 0:  # turno que vira a meia-noite
            seg += 86400
        horas += seg / 3600

    ausencias = []
    for au in Ausencia.objects.filter(
        funcionario=funcionario, inicio__lte=fim, fim__gte=inicio
    ).order_by("inicio"):
        di, df = max(au.inicio, inicio), min(au.fim, fim)
        ausencias.append({
            "tipo": au.get_tipo_display(), "dias": (df - di).days + 1,
            "inicio": au.inicio, "fim": au.fim,
        })

    trocas = TrocaTurno.objects.filter(
        Q(solicitante=funcionario) | Q(substituto=funcionario),
        criado_em__date__range=(inicio, fim),
    ).count()

    return {
        "dias_trabalhados": atribs.count(),
        "horas_trabalhadas": round(horas, 1),
        "ausencias": ausencias,
        "dias_ausente": sum(a["dias"] for a in ausencias),
        "trocas": trocas,
    }


def atribuir(turno, funcionario, data, operador):
    if ausencia_no_dia(funcionario, data):
        raise ValidationError(
            f"{funcionario.pessoa.nome} está ausente em {data:%d/%m} — remova a ausência antes."
        )
    try:
        return Atribuicao.objects.create(
            turno=turno, funcionario=funcionario, data=data, criado_por=operador
        )
    except IntegrityError:
        raise ValidationError("Esse funcionário já está nesse turno neste dia.")


def desatribuir(atribuicao):
    atribuicao.delete()


def mover(atribuicao, novo_turno, nova_data, operador=None):
    """Move uma atribuição para outro turno/dia (arrasto na grade). Bloqueia
    ausência e duplicata (o mesmo funcionário no mesmo turno×dia)."""
    if ausencia_no_dia(atribuicao.funcionario, nova_data):
        raise ValidationError(
            f"{atribuicao.funcionario.pessoa.nome} está ausente em {nova_data:%d/%m}."
        )
    duplicata = (
        Atribuicao.objects
        .filter(turno=novo_turno, funcionario=atribuicao.funcionario, data=nova_data)
        .exclude(pk=atribuicao.pk).exists()
    )
    if duplicata:
        raise ValidationError("Esse funcionário já está nesse turno neste dia.")
    atribuicao.turno = novo_turno
    atribuicao.data = nova_data
    atribuicao.save(update_fields=["turno", "data"])
    return atribuicao


def adicionar_hora_extra(funcionario, data, inicio, fim, tipo, operador=None):
    """Lança uma hora extra planejada (banco/extra) num dia do colaborador."""
    from .models import HoraExtra
    he = HoraExtra(funcionario=funcionario, data=data, inicio=inicio, fim=fim,
                   tipo=tipo or HoraExtra.Tipo.BANCO, criado_por=operador)
    if he.total_minutos <= 0:
        raise ValidationError("Fim deve ser depois do início.")
    he.save()
    return he


def remover_hora_extra(hora_extra):
    hora_extra.delete()


def definir_compensacao_feriado(atribuicao, valor):
    """Marca, no dia de feriado trabalhado, se compensa com folga ou dobro."""
    from .models import Atribuicao
    if valor not in dict(Atribuicao.Compensacao.choices):
        raise ValidationError("Compensação inválida.")
    atribuicao.compensacao_feriado = valor
    atribuicao.save(update_fields=["compensacao_feriado"])
    return atribuicao


def feriados_no_periodo(inicio, fim):
    """Set de datas que são feriado no período (para marcar na grade/relatório)."""
    from .models import Feriado
    return set(Feriado.objects.filter(data__range=(inicio, fim)).values_list("data", flat=True))


def _fmt_min(m):
    return f"{m // 60}h{m % 60:02d}"


def _min_turno(turno):
    from datetime import date, datetime
    d = datetime.combine(date.today(), turno.fim) - datetime.combine(date.today(), turno.inicio)
    m = int(d.total_seconds() // 60)
    return m + 1440 if m < 0 else m


def relatorio_colaborador(funcionario, inicio, fim):
    """Relatório mensal do colaborador: horas normais, extras (banco/extra),
    feriados trabalhados e ausências no período. Base = escala planejada
    (quando houver ponto, passa a usar o realizado)."""
    from .models import Atribuicao, Ausencia, HoraExtra

    atribs = list(
        Atribuicao.objects.filter(funcionario=funcionario, data__range=(inicio, fim))
        .select_related("turno")
    )
    feriados = feriados_no_periodo(inicio, fim)
    horas_normais = sum(_min_turno(a.turno) for a in atribs)

    fer_trab = []
    for a in atribs:
        if a.data in feriados:
            comp = a.compensacao_feriado or funcionario.compensacao_feriado or "folga"
            fer_trab.append({"data": a.data, "turno": a.turno.nome,
                             "compensacao": "Folga compensatória" if comp == "folga" else "Pagamento em dobro"})

    hx = list(HoraExtra.objects.filter(funcionario=funcionario, data__range=(inicio, fim)).order_by("data", "inicio"))
    banco = sum(h.total_minutos for h in hx if h.tipo == "banco")
    extra = sum(h.total_minutos for h in hx if h.tipo == "extra")

    ausencias = []
    for au in Ausencia.objects.filter(funcionario=funcionario, inicio__lte=fim, fim__gte=inicio).order_by("inicio"):
        di, df = max(au.inicio, inicio), min(au.fim, fim)
        ausencias.append({"tipo": au.get_tipo_display(), "dias": (df - di).days + 1,
                          "inicio": au.inicio, "fim": au.fim})

    return {
        "dias_trabalhados": len({a.data for a in atribs}),
        "horas_normais_txt": _fmt_min(horas_normais),
        "banco_txt": _fmt_min(banco),
        "extra_txt": _fmt_min(extra),
        "hx_total_txt": _fmt_min(banco + extra),
        "horas_extras": hx,
        "feriados_trabalhados": fer_trab,
        "ausencias": ausencias,
        "dias_ausente": sum(a["dias"] for a in ausencias),
    }


def ausencias_da_semana(inicio):
    """[(funcionario_id, 'YYYY-MM-DD')] das ausências que tocam a semana — o
    editor usa para acender de vermelho a célula inválida ao arrastar."""
    fim = inicio + timedelta(days=6)
    bloqueios = []
    for au in Ausencia.objects.filter(inicio__lte=fim, fim__gte=inicio):
        d = max(au.inicio, inicio)
        ate = min(au.fim, fim)
        while d <= ate:
            bloqueios.append({"func": au.funcionario_id, "data": d.strftime("%Y-%m-%d")})
            d += timedelta(days=1)
    return bloqueios


def grade_semana(inicio, setor=None):
    """Estrutura para a grade: por turno (linha) × 7 dias, com os funcionários."""
    from .models import Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)

    atribs = (
        Atribuicao.objects.filter(data__range=(dias[0], dias[-1]))
        .select_related("funcionario__pessoa", "turno")
    )
    mapa = {}
    for a in atribs:
        mapa.setdefault((a.turno_id, a.data), []).append(a)

    linhas = []
    for t in turnos:
        celulas = [{"data": d, "atribs": mapa.get((t.pk, d), [])} for d in dias]
        linhas.append({"turno": t, "celulas": celulas})
    return {"dias": dias, "linhas": linhas}


# ---------- Gerador automático de escala (regras encodadas) ----------

# Turno.setor é código; Funcionario.setor é texto livre — casamos por palavra-chave.
SETOR_KEYWORDS = {
    "recepcao": ["recep"],
    "governanca": ["govern", "camar", "limpeza", "arruma", "rouparia"],
    "cozinha": ["cozinh", "restaur", "garcom", "garçom", "bar"],
    "manutencao": ["manuten", "zelador"],
    "geral": [],
}

INTERJORNADA_MIN_H = 11   # CLT: 11h entre o fim de um turno e o início do próximo
MAX_DIAS_SEMANA = 6       # DSR: ao menos 1 folga a cada 6 dias


def funcionarios_do_setor(setor_code):
    from django.db.models import Q

    from apps.nucleo.models import Funcionario

    kws = SETOR_KEYWORDS.get(setor_code, [])
    qs = Funcionario.objects.select_related("pessoa").order_by("pk")
    if not kws:
        return list(qs)
    q = Q()
    for kw in kws:
        q |= Q(setor__icontains=kw)
    return list(qs.filter(q))


def semana_idx(inicio):
    """Índice 0..3 no ciclo de 4 semanas (gira quem folga no domingo)."""
    return inicio.isocalendar().week % 4


def folga_domingo(funcionario, idx):
    """Regra de domingo por sexo, escalonada por funcionário (para não folgarem
    todos no mesmo domingo): ♀ folga 2 de 4, ♂ folga 1 de 4."""
    off = funcionario.pk or 0
    if funcionario.sexo == "M":
        return (idx + off) % 4 == 0            # 1 de 4 domingos de folga
    if funcionario.sexo == "F":
        return (idx + off) % 2 == 0            # 2 de 4 domingos de folga
    return False                               # sem sexo: sem regra especial


def _viola_interjornada(ultimo, dia, turno):
    """ultimo = (data, fim) do último turno alocado; bloqueia gap < 11h (ex.:
    tarde termina 22h e manhã começa 7h no dia seguinte = 9h)."""
    if not ultimo:
        return False
    from datetime import datetime
    ult_data, ult_fim = ultimo
    if (dia - ult_data).days != 1:
        return False
    gap = (datetime.combine(dia, turno.inicio) - datetime.combine(ult_data, ult_fim))
    return gap.total_seconds() / 3600 < INTERJORNADA_MIN_H


def gerar_semana(inicio, operador, setor=None, limpar=True):
    """Monta a semana automaticamente respeitando: cobertura mínima por turno,
    domingo por sexo, interjornada 11h, DSR (máx 6 dias) e ausências/férias.
    Devolve nº de atribuições criadas. O gestor ajusta depois; validar_semana
    aponta o que ficou descoberto."""
    from .models import Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    idx = semana_idx(inicio)
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)
    turnos = list(turnos.order_by("inicio"))
    setores = sorted({t.setor for t in turnos})

    if limpar:
        Atribuicao.objects.filter(
            data__range=(dias[0], dias[-1]), turno__setor__in=setores
        ).delete()

    criadas = 0
    for st in setores:
        funcs = funcionarios_do_setor(st)
        turnos_setor = [t for t in turnos if t.setor == st]
        dias_trab = {f.pk: 0 for f in funcs}
        ultimo = {f.pk: None for f in funcs}     # (data, fim) do último turno
        ocupado_no_dia = set()                   # (func_pk, data) — 1 turno/dia
        for dia in dias:
            eh_domingo = dia.weekday() == 6
            for t in turnos_setor:
                cands = [
                    f for f in funcs
                    if (f.pk, dia) not in ocupado_no_dia
                    and dias_trab[f.pk] < MAX_DIAS_SEMANA
                    and not ausencia_no_dia(f, dia)
                    and not _viola_interjornada(ultimo[f.pk], dia, t)
                ]
                # Cobertura vem primeiro: quem "deveria folgar" no domingo (regra
                # por sexo) vai para o fim da fila e só entra se faltar gente.
                cands.sort(key=lambda f: (
                    1 if (eh_domingo and folga_domingo(f, idx)) else 0,
                    dias_trab[f.pk],
                ))
                for f in cands[: t.min_pessoas]:
                    Atribuicao.objects.create(
                        turno=t, funcionario=f, data=dia, criado_por=operador
                    )
                    dias_trab[f.pk] += 1
                    ultimo[f.pk] = (dia, t.fim)
                    ocupado_no_dia.add((f.pk, dia))
                    criadas += 1
    return criadas


def conflito_interjornada(funcionario, turno, data, ignora_pk=None):
    """A escala de `funcionario` no `turno`/`data` deixa <11h de descanso em
    relação ao dia anterior ou seguinte? (usado no drop, para pedir confirmação)."""
    from datetime import datetime
    viz = Atribuicao.objects.filter(
        funcionario=funcionario, data__in=[data - timedelta(days=1), data + timedelta(days=1)]
    ).select_related("turno")
    if ignora_pk:
        viz = viz.exclude(pk=ignora_pk)
    for a in viz:
        if a.data < data:
            gap = datetime.combine(data, turno.inicio) - datetime.combine(a.data, a.turno.fim)
        else:
            gap = datetime.combine(a.data, a.turno.inicio) - datetime.combine(data, turno.fim)
        if gap.total_seconds() / 3600 < INTERJORNADA_MIN_H:
            return True
    return False


def analisar_semana(inicio, setor=None):
    """Análise completa da semana. Devolve:
      alertas    — lista para o painel ({nivel, texto})
      violacoes  — {atribuicao_id: [{nivel, texto}]} para o selo em cada chip
      bloqueios  — violações de nível legal (barram a publicação)."""
    from datetime import datetime

    from .models import Feriado, Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    domingo = dias[6]
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)
    turnos = list(turnos)
    setores = sorted({t.setor for t in turnos})

    # Semana + 1 dia de borda (interjornada na virada domingo↔segunda).
    borda = list(
        Atribuicao.objects.filter(
            data__range=(dias[0] - timedelta(days=1), dias[-1] + timedelta(days=1)),
            turno__in=turnos,
        ).select_related("funcionario__pessoa", "turno")
    )
    atribs = [a for a in borda if dias[0] <= a.data <= dias[-1]]

    violacoes, alertas, bloqueios = {}, [], []

    def marca(pk, nivel, texto):
        violacoes.setdefault(pk, []).append({"nivel": nivel, "texto": texto})

    # 1) Cobertura mínima por turno × dia
    por_slot = {}
    for a in atribs:
        por_slot.setdefault((a.turno_id, a.data), []).append(a)
    faltas = []
    for t in turnos:
        for d in dias:
            tem = len(por_slot.get((t.pk, d), []))
            if tem < t.min_pessoas:
                faltas.append(f"{t.get_setor_display()} {t.nome} {d:%d/%m} ({tem}/{t.min_pessoas})")
    if faltas:
        alertas.append({"nivel": "perigo", "texto": "Cobertura abaixo do mínimo: " + "; ".join(faltas) + "."})
        bloqueios.append("cobertura abaixo do mínimo")
    else:
        alertas.append({"nivel": "ok", "texto": "Cobertura completa nos 7 dias (mínimo por turno atendido)."})

    # 2) Interjornada 11h + 3) DSR — por funcionário, considerando turno E hora extra.
    from .models import HoraExtra
    he_borda = list(HoraExtra.objects.filter(
        data__range=(dias[0] - timedelta(days=1), dias[-1] + timedelta(days=1))
    ).select_related("funcionario__pessoa"))

    spans, atribs_por_dia, nomes_func = {}, {}, {}
    for a in borda:
        spans.setdefault((a.funcionario_id, a.data), []).append((a.turno.inicio, a.turno.fim))
        atribs_por_dia.setdefault((a.funcionario_id, a.data), []).append(a)
        nomes_func[a.funcionario_id] = a.funcionario.pessoa.nome
    for he in he_borda:
        spans.setdefault((he.funcionario_id, he.data), []).append((he.inicio, he.fim))
        nomes_func[he.funcionario_id] = he.funcionario.pessoa.nome

    inter_nomes, dsr_nomes = [], []
    for fid in {f for (f, _d) in spans}:
        nome = nomes_func.get(fid, "")
        for d in dias:
            hoje = spans.get((fid, d), [])
            ontem = spans.get((fid, d - timedelta(days=1)), [])
            if hoje and ontem:
                gap = (datetime.combine(d, min(s[0] for s in hoje))
                       - datetime.combine(d - timedelta(days=1), max(s[1] for s in ontem)))
                if gap.total_seconds() / 3600 < INTERJORNADA_MIN_H:
                    if nome not in inter_nomes:
                        inter_nomes.append(nome)
                    for a in atribs_por_dia.get((fid, d), []):
                        marca(a.pk, "perigo", "Interjornada <11h")
        dias_trab = {d for d in dias if spans.get((fid, d))}
        if len(dias_trab) >= 7:
            dsr_nomes.append(nome)
            for d in dias:
                for a in atribs_por_dia.get((fid, d), []):
                    marca(a.pk, "perigo", "Sem folga na semana (DSR)")
    if inter_nomes:
        alertas.append({"nivel": "perigo", "texto": "Interjornada <11h: " + ", ".join(inter_nomes) + "."})
        bloqueios.append("interjornada <11h")
    if dsr_nomes:
        alertas.append({"nivel": "perigo", "texto": "Sem folga na semana (DSR): " + ", ".join(dsr_nomes) + "."})
        bloqueios.append("DSR (sem folga)")
    if not inter_nomes and not dsr_nomes:
        alertas.append({"nivel": "ok", "texto": "Interjornada de 11h respeitada e DSR ok (todos com folga)."})

    # Total de horas extras da semana (prévia do relatório mensal)
    he_sem = [he for he in he_borda if dias[0] <= he.data <= dias[-1]]
    if he_sem:
        def _fmt(m):
            return f"{m // 60}h{m % 60:02d}"
        tot = sum(he.total_minutos for he in he_sem)
        banco = sum(he.total_minutos for he in he_sem if he.tipo == "banco")
        extra = sum(he.total_minutos for he in he_sem if he.tipo == "extra")
        alertas.append({"nivel": "info",
                        "texto": f"Horas extras planejadas na semana: {_fmt(tot)} "
                                 f"(banco {_fmt(banco)} · extra {_fmt(extra)})."})

    # 4) Domingo — folga real + memória dos últimos 4 domingos (rodízio)
    idx = semana_idx(inicio)
    domingos = [domingo - timedelta(days=7 * k) for k in range(4)]
    dom_hist = Atribuicao.objects.filter(data__in=domingos, turno__in=turnos)
    trab_por_dom = {}
    for a in dom_hist:
        trab_por_dom.setdefault(a.funcionario_id, set()).add(a.data)
    trab_este = {a.funcionario_id: a for a in atribs if a.data == domingo}
    folgam, forcados, rodizio = [], [], []
    for st in setores:
        for f in funcionarios_do_setor(st):
            if not f.sexo:
                continue
            deveria = folga_domingo(f, idx)
            if f.pk not in trab_este:
                folgam.append(f"{f.pessoa.nome} ({'♀ 2/4' if f.sexo == 'F' else '♂ 1/4'})")
            elif deveria:
                forcados.append(f.pessoa.nome)
            qtd = len(trab_por_dom.get(f.pk, set()))
            limite = 4 if f.sexo == "M" else 3      # ♂: nunca folgou no mês; ♀: só 1 folga em 4
            if qtd >= limite and f.pk in trab_este:
                rodizio.append(f.pessoa.nome)
                marca(trab_este[f.pk].pk, "aviso", f"{qtd}º domingo — rodízio")
    if folgam:
        alertas.append({"nivel": "info", "texto": f"Domingo {domingo:%d/%m} — folga pela regra: " + "; ".join(folgam) + "."})
    if forcados:
        alertas.append({"nivel": "aviso",
                        "texto": f"Domingo {domingo:%d/%m} — folga dominical não coube por falta de gente: "
                                 f"{', '.join(forcados)}. Considere um coringa."})
    if rodizio:
        alertas.append({"nivel": "aviso",
                        "texto": "Rodízio de domingo quebrado (poucas folgas no mês): "
                                 + ", ".join(sorted(set(rodizio))) + "."})

    # 5) Feriado na semana
    for fe in Feriado.objects.filter(data__range=(dias[0], dias[-1])):
        alertas.append({"nivel": "info",
                        "texto": f"Feriado {fe.data:%d/%m} ({fe.nome}) — tratar como domingo; "
                                 "compensação (folga/dobro) por funcionário."})

    return {"alertas": alertas, "violacoes": violacoes, "bloqueios": bloqueios}


def validar_semana(inicio, setor=None):
    """Compat: só os alertas do painel (usa analisar_semana)."""
    return analisar_semana(inicio, setor)["alertas"]


def publicar_semana(inicio, setor, operador, justificativa=""):
    """Publica a semana. Barra se houver violação legal em aberto, salvo se a
    gerência justificar (força). Registra na auditoria."""
    from apps.nucleo.models.financeiro import registrar_auditoria

    from .models import SemanaPublicada

    bloqueios = analisar_semana(inicio, setor)["bloqueios"]
    if bloqueios and not (justificativa or "").strip():
        raise ValidationError(
            "Há violação legal em aberto (" + ", ".join(bloqueios) + "). "
            "Corrija ou justifique para publicar mesmo assim."
        )
    pub, _ = SemanaPublicada.objects.update_or_create(
        inicio=inicio, setor=setor or "",
        defaults={"publicado_por": operador, "forcado": bool(bloqueios),
                  "justificativa": justificativa.strip()[:240]},
    )
    registrar_auditoria(operador, "publicar_escala", pub,
                        {"forcado": bool(bloqueios), "bloqueios": bloqueios,
                         "justificativa": pub.justificativa})
    return pub


def registrar_ausencia(funcionario, tipo, inicio, fim, operador, observacao=""):
    if fim < inicio:
        raise ValidationError("A data final não pode ser antes da inicial.")
    return Ausencia.objects.create(
        funcionario=funcionario, tipo=tipo, inicio=inicio, fim=fim,
        observacao=observacao, criado_por=operador,
    )


def minha_escala(usuario, inicio, fim):
    func = getattr(usuario, "funcionario", None)
    if not func:
        return []
    return (
        Atribuicao.objects.filter(funcionario=func, data__range=(inicio, fim))
        .select_related("turno").order_by("data", "turno__inicio")
    )


def solicitar_troca(atribuicao, substituto, motivo=""):
    if substituto == atribuicao.funcionario:
        raise ValidationError("Escolha um substituto diferente.")
    if ausencia_no_dia(substituto, atribuicao.data):
        raise ValidationError("O substituto está ausente nesse dia.")
    return TrocaTurno.objects.create(
        atribuicao=atribuicao, solicitante=atribuicao.funcionario,
        substituto=substituto, motivo=motivo,
    )


def decidir_troca(troca, operador, aprovar):
    if troca.status != TrocaTurno.Status.PENDENTE:
        raise ValidationError("Esta troca já foi decidida.")
    troca.decidido_por = operador
    troca.decidido_em = timezone.now()
    if aprovar:
        troca.status = TrocaTurno.Status.APROVADA
        atrib = troca.atribuicao
        atrib.funcionario = troca.substituto
        atrib.save(update_fields=["funcionario"])
    else:
        troca.status = TrocaTurno.Status.RECUSADA
    troca.save(update_fields=["status", "decidido_por", "decidido_em"])
    return troca

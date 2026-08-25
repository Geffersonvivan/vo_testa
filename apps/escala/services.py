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


def validar_semana(inicio, setor=None):
    """Alertas da semana: cobertura, interjornada, DSR, domingo e feriados.
    Cada item = {nivel: ok|aviso|perigo|info, texto}."""
    from .models import Feriado, Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)
    turnos = list(turnos)

    atribs = list(
        Atribuicao.objects.filter(data__range=(dias[0], dias[-1]),
                                  turno__in=turnos)
        .select_related("funcionario__pessoa", "turno")
    )
    por_slot = {}
    por_func = {}
    for a in atribs:
        por_slot.setdefault((a.turno_id, a.data), []).append(a)
        por_func.setdefault(a.funcionario_id, []).append(a)

    alertas = []

    # 1) Cobertura mínima por turno × dia
    faltas = []
    for t in turnos:
        for d in dias:
            tem = len(por_slot.get((t.pk, d), []))
            if tem < t.min_pessoas:
                faltas.append(f"{t.get_setor_display()} {t.nome} {d:%d/%m} ({tem}/{t.min_pessoas})")
    if faltas:
        alertas.append({"nivel": "perigo",
                        "texto": "Cobertura abaixo do mínimo: " + "; ".join(faltas) + "."})
    else:
        alertas.append({"nivel": "ok",
                        "texto": "Cobertura completa nos 7 dias (mínimo por turno atendido)."})

    # 2) Interjornada 11h e 3) DSR — por funcionário
    problemas_inter, sem_folga = [], []
    for fid, lista in por_func.items():
        nome = lista[0].funcionario.pessoa.nome
        por_data = {}
        for a in lista:
            por_data.setdefault(a.data, []).append(a)
        # interjornada: fim de ontem × início de hoje
        from datetime import datetime
        for d in dias:
            hoje = por_data.get(d, [])
            ontem = por_data.get(d - timedelta(days=1), [])
            if hoje and ontem:
                fim_ontem = max(a.turno.fim for a in ontem)
                ini_hoje = min(a.turno.inicio for a in hoje)
                gap = (datetime.combine(d, ini_hoje)
                       - datetime.combine(d - timedelta(days=1), fim_ontem))
                if gap.total_seconds() / 3600 < INTERJORNADA_MIN_H:
                    problemas_inter.append(f"{nome} ({d:%d/%m})")
        if len(por_data) >= 7:
            sem_folga.append(nome)
    if problemas_inter:
        alertas.append({"nivel": "perigo",
                        "texto": "Interjornada <11h (descanso curto entre turnos): "
                                 + "; ".join(problemas_inter) + "."})
    if sem_folga:
        alertas.append({"nivel": "perigo",
                        "texto": "Sem folga na semana (DSR): " + ", ".join(sem_folga) + "."})
    if not problemas_inter and not sem_folga:
        alertas.append({"nivel": "ok",
                        "texto": "Interjornada de 11h respeitada e DSR ok (todos com folga)."})

    # 4) Domingo — folga real (regra por sexo, respeitando a cobertura) e aviso
    #    quando a cobertura obrigou alguém que "deveria" folgar a trabalhar.
    idx = semana_idx(inicio)
    domingo = dias[6]
    trabalham_dom = {a.funcionario_id for a in atribs if a.data == domingo}
    folgam, forcados = [], []
    for st in sorted({t.setor for t in turnos}):
        for f in funcionarios_do_setor(st):
            if not f.sexo:
                continue
            marca = "♀ 2/4" if f.sexo == "F" else "♂ 1/4"
            deveria = folga_domingo(f, idx)
            if f.pk not in trabalham_dom:
                folgam.append(f"{f.pessoa.nome} ({marca})")
            elif deveria:
                forcados.append(f.pessoa.nome)
    if folgam:
        alertas.append({"nivel": "info",
                        "texto": f"Domingo {domingo:%d/%m} — folga pela regra: " + "; ".join(folgam) + "."})
    if forcados:
        alertas.append({"nivel": "aviso",
                        "texto": f"Domingo {domingo:%d/%m} — folga dominical não pôde ser respeitada "
                                 f"por falta de gente: {', '.join(forcados)}. Considere um coringa."})

    # 5) Feriado na semana
    for fe in Feriado.objects.filter(data__range=(dias[0], dias[-1])):
        alertas.append({"nivel": "info",
                        "texto": f"Feriado {fe.data:%d/%m} ({fe.nome}) — tratar como domingo; "
                                 "compensação (folga/dobro) por funcionário."})

    return alertas


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

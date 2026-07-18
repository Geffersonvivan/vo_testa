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

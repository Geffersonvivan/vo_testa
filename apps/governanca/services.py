"""Serviços da Governança — interface pública (o Mapa de quartos consome daqui)."""

from django.utils import timezone

from apps.nucleo.models import registrar_auditoria

from .models import StatusLimpeza, TarefaGovernanca


def situacao_uh(uh) -> StatusLimpeza:
    return StatusLimpeza.objects.get_or_create(uh=uh)[0]


def uh_pronta_para_checkin(uh) -> bool:
    """Limpa ou inspecionada. Interface pública para Reservas (guard de entrada)."""
    return situacao_uh(uh).pronta


def status_por_uh() -> dict:
    """{uh_id: situacao} — usado pelo Mapa de quartos."""
    return {s.uh_id: s.situacao for s in StatusLimpeza.objects.all()}


def definir_status(uh, situacao, usuario=None):
    status = situacao_uh(uh)
    status.situacao = situacao
    status.atualizado_por = usuario
    status.save()
    return status


def abrir_faxina(uh, tipo=TarefaGovernanca.Tipo.FAXINA, usuario=None, origem="manual"):
    """Marca o quarto como sujo e cria a tarefa de faxina (evita duplicar pendente)."""
    definir_status(uh, StatusLimpeza.Situacao.SUJA, usuario)
    tarefa = (
        TarefaGovernanca.objects.filter(
            uh=uh, tipo=tipo, status__in=["pendente", "em_andamento"]
        ).first()
    )
    if tarefa:
        return tarefa
    return TarefaGovernanca.objects.create(uh=uh, tipo=tipo, origem=origem)


def iniciar_tarefa(tarefa, usuario=None):
    tarefa.status = TarefaGovernanca.Status.EM_ANDAMENTO
    tarefa.iniciada_em = timezone.now()
    tarefa.save()
    definir_status(tarefa.uh, StatusLimpeza.Situacao.EM_LIMPEZA, usuario)
    return tarefa


def concluir_tarefa(tarefa, usuario=None):
    tarefa.status = TarefaGovernanca.Status.CONCLUIDA
    tarefa.concluida_em = timezone.now()
    tarefa.save()
    definir_status(tarefa.uh, StatusLimpeza.Situacao.LIMPA, usuario)
    registrar_auditoria(usuario, "faxina_concluida", tarefa, {"quarto": tarefa.uh.numero})
    # A Lavanderia (se ativa) recolhe o enxoval sujo do quarto — via sinal.
    from .signals import faxina_concluida

    faxina_concluida.send(sender=TarefaGovernanca, uh=tarefa.uh,
                          tarefa=tarefa, usuario=usuario)
    return tarefa


def inspecionar(uh, usuario=None):
    return definir_status(uh, StatusLimpeza.Situacao.INSPECIONADA, usuario)


def tarefas_ativas():
    return (
        TarefaGovernanca.objects.exclude(status=TarefaGovernanca.Status.CONCLUIDA)
        .select_related("uh", "uh__tipo", "camareira")
    )


# Urgência: o que precisa de ação sobe. (a limpar → em limpeza → limpa → inspecionada)
_ORDEM_LIMPEZA = {
    StatusLimpeza.Situacao.SUJA: 0,
    StatusLimpeza.Situacao.EM_LIMPEZA: 1,
    StatusLimpeza.Situacao.LIMPA: 2,
    StatusLimpeza.Situacao.INSPECIONADA: 3,
}


def painel_limpeza():
    """Tela única de Governança: uma linha por quarto FÍSICO (day-use fora), com o
    status de limpeza + a tarefa ativa (se houver), ordenada por urgência. Substitui
    as duas tabelas (fila de faxina + situação dos quartos) por uma só."""
    from apps.nucleo.models import UH, TipoUH

    tarefas = {}
    for t in tarefas_ativas():
        tarefas.setdefault(t.uh_id, t)  # a mais recente por quarto (ordering do model)

    contagem = {c: 0 for c, _ in StatusLimpeza.Situacao.choices}
    linhas = []
    quartos = (
        UH.objects.select_related("tipo")
        .exclude(status=UH.Status.INATIVA)
        .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
    )
    for uh in quartos:
        status = situacao_uh(uh)
        contagem[status.situacao] += 1
        linhas.append({
            "uh": uh,
            "situacao": status.situacao,
            "situacao_label": status.get_situacao_display(),
            "tarefa": tarefas.get(uh.pk),
            "atualizado_em": status.atualizado_em,
        })
    linhas.sort(key=lambda ln: (_ORDEM_LIMPEZA.get(ln["situacao"], 9), ln["uh"].numero))
    return {"linhas": linhas, "contagem": contagem}

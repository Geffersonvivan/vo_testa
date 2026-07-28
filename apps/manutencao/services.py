"""
Regras do módulo Manutenção. Interface pública para as views e outros módulos.
O bloqueio do quarto usa `UH.status` (a disponibilidade é sempre dona do
Reservas); a ocupação atual é consultada por `reservas.services` — nunca por
import de model interno. Operações que mexem no quarto são auditadas.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import UH, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .models import OrdemServico
from .signals import reparo_concluido


def _registrar_bloqueio(uh, usuario, ordem):
    """Valida e audita o bloqueio POR DATAS. A indisponibilidade em si vem da
    janela [bloqueio_inicio, bloqueio_fim] da OS (a disponibilidade é dona do
    Reservas) — aqui não se mexe em UH.status."""
    if uh.status == UH.Status.INATIVA:
        raise ValidationError(f"O quarto {uh.numero} está inativo.")
    # A janela do bloqueio não pode colidir com reserva ativa (consulta a fonte).
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import reserva_conflita

        if reserva_conflita(uh, ordem.bloqueio_inicio, ordem.bloqueio_fim):
            raise ValidationError(
                f"O quarto {uh.numero} tem reserva no período do bloqueio — "
                "ajuste as datas ou realoje o hóspede antes."
            )
    registrar_auditoria(usuario, "bloqueio_uh", ordem, {
        "uh": uh.numero, "motivo": ordem.titulo,
        "de": str(ordem.bloqueio_inicio),
        "ate": str(ordem.bloqueio_fim) if ordem.bloqueio_fim else "até concluir",
    })


def _liberar_uh(uh, usuario, ordem):
    # O bloqueio por datas cessa ao encerrar a OS (deixa de contar em `bloqueios`).
    # Mantido por segurança: solta um UH.status legado que tenha ficado BLOQUEADA.
    if uh.status == UH.Status.BLOQUEADA:
        uh.status = UH.Status.ATIVA
        uh.save(update_fields=["status"])
        registrar_auditoria(usuario, "liberacao_uh", ordem, {"uh": uh.numero})


@transaction.atomic
def abrir_os(operador, *, uh=None, area="", titulo, descricao="",
             tipo=OrdemServico.Tipo.CORRETIVA,
             prioridade=OrdemServico.Prioridade.MEDIA,
             responsavel=None, prestador=None, previsto_para=None,
             bloquear=False, recorrencia_meses=None, agendada_para=None,
             bloqueio_inicio=None, bloqueio_fim=None):
    titulo = (titulo or "").strip()
    area = (area or "").strip()
    if not titulo:
        raise ValidationError("Descreva o problema no título.")
    if not uh and not area:
        raise ValidationError("Escolha um quarto ou informe a área comum.")
    if uh and area:
        raise ValidationError("Informe apenas um alvo: quarto OU área comum.")
    if bloquear and not uh:
        raise ValidationError("Só é possível bloquear um quarto (não uma área).")

    # Janela do bloqueio (por datas): início = agendada/hoje; fim = previsto ou aberto.
    b_ini = b_fim = None
    if bloquear and uh:
        b_ini = bloqueio_inicio or agendada_para or timezone.localdate()
        b_fim = bloqueio_fim or previsto_para or None
        if b_fim and b_fim < b_ini:
            raise ValidationError("O fim do bloqueio não pode ser antes do início.")

    ordem = OrdemServico.objects.create(
        uh=uh, area=area, titulo=titulo, descricao=descricao or "",
        tipo=tipo, prioridade=prioridade, responsavel=responsavel,
        prestador=prestador, previsto_para=previsto_para,
        bloqueia_uh=bool(bloquear and uh),
        bloqueio_inicio=b_ini, bloqueio_fim=b_fim,
        recorrencia_meses=recorrencia_meses or None,
        agendada_para=agendada_para,
        criado_por=operador,
    )
    if ordem.bloqueia_uh:
        _registrar_bloqueio(uh, operador, ordem)
    return ordem


def iniciar_os(ordem, usuario):
    if ordem.status != OrdemServico.Status.ABERTA:
        raise ValidationError("Só uma OS aberta pode ser iniciada.")
    ordem.status = OrdemServico.Status.EM_ANDAMENTO
    ordem.iniciada_em = timezone.now()
    ordem.save(update_fields=["status", "iniciada_em"])
    return ordem


@transaction.atomic
def concluir_os(ordem, usuario, *, resolucao="",
                custo_maodeobra=None, custo_pecas=None,
                nota_fiscal=None, garantia_ate=None):
    if not ordem.aberta_ou_andamento:
        raise ValidationError("Esta OS já foi encerrada.")
    if custo_maodeobra is not None:
        ordem.custo_maodeobra = Decimal(custo_maodeobra)
    if custo_pecas is not None:
        ordem.custo_pecas = Decimal(custo_pecas)
    if nota_fiscal is not None:
        ordem.nota_fiscal = nota_fiscal
    if garantia_ate is not None:
        ordem.garantia_ate = garantia_ate
    ordem.resolucao = resolucao or ""
    ordem.status = OrdemServico.Status.CONCLUIDA
    ordem.concluida_em = timezone.now()
    ordem.save(update_fields=[
        "custo_maodeobra", "custo_pecas", "nota_fiscal", "garantia_ate",
        "resolucao", "status", "concluida_em"
    ])

    # Libera o quarto e avisa a Governança (quarto pós-reparo precisa de limpeza).
    if ordem.bloqueia_uh and ordem.uh_id:
        _liberar_uh(ordem.uh, usuario, ordem)
        reparo_concluido.send(
            sender=OrdemServico, uh=ordem.uh, ordem=ordem, usuario=usuario
        )

    # Preventiva com recorrência: agenda a próxima OS.
    proxima = None
    if ordem.tipo == OrdemServico.Tipo.PREVENTIVA and ordem.recorrencia_meses:
        base = ordem.agendada_para or timezone.localdate()
        proxima = OrdemServico.objects.create(
            uh=ordem.uh, area=ordem.area, titulo=ordem.titulo,
            descricao=ordem.descricao, tipo=OrdemServico.Tipo.PREVENTIVA,
            prioridade=ordem.prioridade, responsavel=ordem.responsavel,
            recorrencia_meses=ordem.recorrencia_meses,
            agendada_para=base + timedelta(days=30 * ordem.recorrencia_meses),
            criado_por=usuario,
        )
    return proxima


def _os_bloqueadoras():
    """OS abertas/em andamento que bloqueiam um quarto (com janela de datas)."""
    return OrdemServico.objects.filter(
        bloqueia_uh=True,
        uh__isnull=False,
        bloqueio_inicio__isnull=False,
        status__in=[OrdemServico.Status.ABERTA, OrdemServico.Status.EM_ANDAMENTO],
    )


def uhs_bloqueadas(checkin, checkout) -> set:
    """IDs de UHs com bloqueio de manutenção nas noites [checkin, checkout).

    Interface pública para o Reservas (disponibilidade central). Uma reserva de
    noites [checkin, checkout) colide com o bloqueio [ini, fim] se
    ini < checkout e (fim vazio ou fim >= checkin)."""
    return {
        o.uh_id
        for o in _os_bloqueadoras()
        if o.bloqueio_inicio < checkout
        and (o.bloqueio_fim is None or o.bloqueio_fim >= checkin)
    }


def bloqueios(inicio, fim) -> list:
    """Bloqueios de manutenção que tocam a janela de datas [inicio, fim] (inclusive).

    Interface pública para o mapa de reservas desenhar por célula.
    Cada item: {uh_id, inicio (date), fim (date|None), motivo}."""
    return [
        {"uh_id": o.uh_id, "inicio": o.bloqueio_inicio,
         "fim": o.bloqueio_fim, "motivo": o.titulo}
        for o in _os_bloqueadoras()
        if o.bloqueio_inicio <= fim
        and (o.bloqueio_fim is None or o.bloqueio_fim >= inicio)
    ]


def motivos_bloqueio():
    """{uh_id: motivo} dos quartos bloqueados por manutenção HOJE — para o
    corredor (mapa de quartos), que é a visão operacional do dia."""
    hoje = timezone.localdate()
    return {b["uh_id"]: b["motivo"] for b in bloqueios(hoje, hoje)}


def pendencias_auditoria():
    """Inconsistências de Manutenção para a Auditoria (read-only)."""
    from django.urls import reverse

    from apps.nucleo.models import UH
    achados = []
    limite = timezone.now() - timedelta(days=7)
    for os in OrdemServico.objects.filter(
        status__in=[OrdemServico.Status.ABERTA, OrdemServico.Status.EM_ANDAMENTO],
        aberta_em__lt=limite,
    ):
        achados.append({
            "area": "Manutenção", "tipo": "os_antiga", "gravidade": "media",
            "descricao": f"OS #{os.pk} '{os.titulo}' aberta há mais de 7 dias.",
            "url": reverse("manutencao:detalhe", args=[os.pk]),
        })
    for uh in UH.objects.filter(status=UH.Status.BLOQUEADA):
        achados.append({
            "area": "Manutenção", "tipo": "quarto_bloqueado", "gravidade": "media",
            "descricao": f"{uh.numero} bloqueado (manutenção) — fora da disponibilidade.",
            "url": reverse("manutencao:painel"),
        })
    return achados


@transaction.atomic
def cancelar_os(ordem, usuario, motivo=""):
    if not ordem.aberta_ou_andamento:
        raise ValidationError("Esta OS já foi encerrada.")
    if ordem.bloqueia_uh and ordem.uh_id:
        _liberar_uh(ordem.uh, usuario, ordem)
    ordem.status = OrdemServico.Status.CANCELADA
    ordem.motivo_cancelamento = motivo or ""
    ordem.concluida_em = timezone.now()
    ordem.save(update_fields=["status", "motivo_cancelamento", "concluida_em"])
    registrar_auditoria(usuario, "cancelamento_os", ordem, {"motivo": motivo or ""})
    return ordem

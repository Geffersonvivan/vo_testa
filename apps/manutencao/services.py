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


def _bloquear_uh(uh, usuario, ordem):
    if uh.status == UH.Status.INATIVA:
        raise ValidationError(f"O quarto {uh.numero} está inativo.")
    if uh.status == UH.Status.BLOQUEADA:
        raise ValidationError(f"O quarto {uh.numero} já está bloqueado.")
    # Não bloquear um quarto com hóspede em casa (consulta a fonte: Reservas).
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import uh_ocupada

        if uh_ocupada(uh):
            raise ValidationError(
                f"O quarto {uh.numero} está ocupado — faça o check-out antes de bloquear."
            )
    uh.status = UH.Status.BLOQUEADA
    uh.save(update_fields=["status"])
    registrar_auditoria(usuario, "bloqueio_uh", ordem,
                        {"uh": uh.numero, "motivo": ordem.titulo})


def _liberar_uh(uh, usuario, ordem):
    if uh.status == UH.Status.BLOQUEADA:
        uh.status = UH.Status.ATIVA
        uh.save(update_fields=["status"])
        registrar_auditoria(usuario, "liberacao_uh", ordem, {"uh": uh.numero})


@transaction.atomic
def abrir_os(operador, *, uh=None, area="", titulo, descricao="",
             tipo=OrdemServico.Tipo.CORRETIVA,
             prioridade=OrdemServico.Prioridade.MEDIA,
             responsavel=None, prestador=None, previsto_para=None,
             bloquear=False, recorrencia_meses=None, agendada_para=None):
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

    ordem = OrdemServico.objects.create(
        uh=uh, area=area, titulo=titulo, descricao=descricao or "",
        tipo=tipo, prioridade=prioridade, responsavel=responsavel,
        prestador=prestador, previsto_para=previsto_para,
        bloqueia_uh=bool(bloquear and uh),
        recorrencia_meses=recorrencia_meses or None,
        agendada_para=agendada_para,
        criado_por=operador,
    )
    if ordem.bloqueia_uh:
        _bloquear_uh(uh, operador, ordem)
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

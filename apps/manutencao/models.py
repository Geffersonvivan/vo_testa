"""
Módulo Manutenção (ESPECIFICACAO §5.3) — ordens de serviço para quartos e áreas
comuns, com bloqueio do quarto durante o reparo (some da disponibilidade) e
manutenção preventiva com recorrência. O custo de peças/mão de obra é registrado
na OS; o bloqueio usa o status da UH (fonte de verdade da disponibilidade é
Reservas). Depende de Reservas.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


class OrdemServico(models.Model):
    class Tipo(models.TextChoices):
        CORRETIVA = "corretiva", "Corretiva"
        PREVENTIVA = "preventiva", "Preventiva"

    class Prioridade(models.TextChoices):
        BAIXA = "baixa", "Baixa"
        MEDIA = "media", "Média"
        ALTA = "alta", "Alta"
        URGENTE = "urgente", "Urgente"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"
        CANCELADA = "cancelada", "Cancelada"

    # Alvo: um quarto OU uma área comum (informe um dos dois).
    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordens_servico", verbose_name="quarto",
    )
    area = models.CharField(
        "área comum", max_length=80, blank=True,
        help_text="Preencha quando não for um quarto (ex.: piscina, recepção).",
    )
    titulo = models.CharField("título", max_length=120)
    descricao = models.TextField("descrição", blank=True)
    tipo = models.CharField(
        "tipo", max_length=10, choices=Tipo.choices, default=Tipo.CORRETIVA
    )
    prioridade = models.CharField(
        "prioridade", max_length=8, choices=Prioridade.choices, default=Prioridade.MEDIA
    )
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.ABERTA
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ordens_servico_responsavel", verbose_name="responsável (interno)",
    )
    prestador = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordens_servico", verbose_name="prestador (externo)",
        help_text="Empresa/fornecedor que executou o serviço terceirizado.",
    )
    nota_fiscal = models.CharField("nota fiscal / documento", max_length=60, blank=True)
    garantia_ate = models.DateField("garantia até", null=True, blank=True)
    previsto_para = models.DateField("previsto para", null=True, blank=True)
    bloqueia_uh = models.BooleanField(
        "bloquear o quarto durante o reparo", default=False,
        help_text="O quarto sai da disponibilidade até a OS ser concluída.",
    )
    custo_maodeobra = models.DecimalField(
        "mão de obra (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    custo_pecas = models.DecimalField(
        "peças (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    # Preventiva: gera a próxima OS ao concluir.
    recorrencia_meses = models.PositiveSmallIntegerField(
        "recorrência (meses)", null=True, blank=True,
        help_text="Só para preventiva: repetir a cada N meses.",
    )
    agendada_para = models.DateField("agendada para", null=True, blank=True)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ordens_servico_abertas", verbose_name="aberta por",
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    iniciada_em = models.DateTimeField("iniciada em", null=True, blank=True)
    concluida_em = models.DateTimeField("concluída em", null=True, blank=True)
    resolucao = models.TextField("resolução", blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)

    class Meta:
        verbose_name = "ordem de serviço"
        verbose_name_plural = "ordens de serviço"
        ordering = ["-aberta_em"]

    def __str__(self):
        return f"OS #{self.pk} — {self.titulo}"

    @property
    def alvo(self) -> str:
        if self.uh_id:
            return self.uh.numero
        return self.area or "—"

    @property
    def aberta_ou_andamento(self) -> bool:
        return self.status in (self.Status.ABERTA, self.Status.EM_ANDAMENTO)

    @property
    def custo_total(self) -> Decimal:
        return self.custo_maodeobra + self.custo_pecas

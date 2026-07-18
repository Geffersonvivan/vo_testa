"""
Módulo Governança (ESPECIFICACAO §5.2) — status de limpeza por quarto e fila de
faxinas geradas por evento (check-out/troca). Depende de Reservas (ouve o sinal
`quarto_liberado`). Alimenta o Mapa de quartos com o estado real de limpeza.
"""

from django.conf import settings
from django.db import models


class StatusLimpeza(models.Model):
    """Situação de limpeza atual de cada quarto."""

    class Situacao(models.TextChoices):
        LIMPA = "limpa", "Limpa"
        SUJA = "suja", "Suja"
        EM_LIMPEZA = "em_limpeza", "Em limpeza"
        INSPECIONADA = "inspecionada", "Inspecionada"

    uh = models.OneToOneField(
        "nucleo.UH", on_delete=models.CASCADE,
        related_name="limpeza", verbose_name="quarto",
    )
    situacao = models.CharField(
        "situação", max_length=12, choices=Situacao.choices, default=Situacao.LIMPA
    )
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="atualizado por",
    )

    class Meta:
        verbose_name = "status de limpeza"
        verbose_name_plural = "status de limpeza"

    def __str__(self):
        return f"{self.uh.numero}: {self.get_situacao_display()}"

    @property
    def pronta(self) -> bool:
        return self.situacao in (self.Situacao.LIMPA, self.Situacao.INSPECIONADA)


class TarefaGovernanca(models.Model):
    """Faxina/arrumação de um quarto, atribuída a uma camareira."""

    class Tipo(models.TextChoices):
        FAXINA = "faxina_completa", "Faxina completa"
        ARRUMACAO = "arrumacao", "Arrumação"
        TROCA_ROUPA = "troca_roupa", "Troca de roupa de cama"
        POS_MANUTENCAO = "pos_manutencao", "Pós-manutenção"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="tarefas_governanca", verbose_name="quarto",
    )
    tipo = models.CharField(
        "tipo", max_length=16, choices=Tipo.choices, default=Tipo.FAXINA
    )
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PENDENTE
    )
    camareira = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="faxinas", verbose_name="camareira",
    )
    origem = models.CharField("origem", max_length=20, default="manual")
    observacoes = models.TextField("observações", blank=True)
    gerada_em = models.DateTimeField("gerada em", auto_now_add=True)
    iniciada_em = models.DateTimeField("iniciada em", null=True, blank=True)
    concluida_em = models.DateTimeField("concluída em", null=True, blank=True)

    class Meta:
        verbose_name = "tarefa de governança"
        verbose_name_plural = "tarefas de governança"
        ordering = ["status", "gerada_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.uh.numero} ({self.get_status_display()})"

    @property
    def ativa(self) -> bool:
        return self.status != self.Status.CONCLUIDA

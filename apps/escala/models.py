"""
Módulo Escala (ESPECIFICACAO §5.4 — diferencial; Desbravador não tem). Turnos por
setor; escala funcionário × dia × turno; folgas/férias (ausências); troca de turno
com aprovação da gerência. Depende só do Núcleo (usa Funcionario).
"""
from django.conf import settings
from django.db import models


class Turno(models.Model):
    class Setor(models.TextChoices):
        RECEPCAO = "recepcao", "Recepção"
        GOVERNANCA = "governanca", "Governança"
        COZINHA = "cozinha", "Cozinha/Restaurante"
        MANUTENCAO = "manutencao", "Manutenção"
        GERAL = "geral", "Geral"

    nome = models.CharField("nome", max_length=40, help_text="Ex.: Manhã, Tarde, Noite.")
    setor = models.CharField("setor", max_length=12, choices=Setor.choices,
                             default=Setor.GERAL)
    inicio = models.TimeField("início")
    fim = models.TimeField("fim")
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "turno"
        verbose_name_plural = "turnos"
        ordering = ["setor", "inicio"]

    def __str__(self):
        return f"{self.get_setor_display()} · {self.nome} ({self.inicio:%H:%M}–{self.fim:%H:%M})"


class Atribuicao(models.Model):
    turno = models.ForeignKey(Turno, on_delete=models.CASCADE,
                              related_name="atribuicoes", verbose_name="turno")
    funcionario = models.ForeignKey("nucleo.Funcionario", on_delete=models.CASCADE,
                                    related_name="atribuicoes", verbose_name="funcionário")
    data = models.DateField("data")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="atribuicoes_escala", null=True, blank=True)
    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "atribuição de turno"
        verbose_name_plural = "atribuições de turno"
        ordering = ["data", "turno__inicio"]
        constraints = [
            models.UniqueConstraint(fields=["turno", "funcionario", "data"],
                                    name="escala_atribuicao_unica"),
        ]

    def __str__(self):
        return f"{self.funcionario.pessoa.nome} · {self.turno.nome} · {self.data}"


class Ausencia(models.Model):
    class Tipo(models.TextChoices):
        FOLGA = "folga", "Folga"
        FERIAS = "ferias", "Férias"
        ATESTADO = "atestado", "Atestado"
        OUTRO = "outro", "Outro"

    funcionario = models.ForeignKey("nucleo.Funcionario", on_delete=models.CASCADE,
                                    related_name="ausencias", verbose_name="funcionário")
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices, default=Tipo.FOLGA)
    inicio = models.DateField("início")
    fim = models.DateField("fim")
    observacao = models.CharField("observação", max_length=120, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="ausencias_criadas", null=True, blank=True)

    class Meta:
        verbose_name = "ausência"
        verbose_name_plural = "ausências"
        ordering = ["-inicio"]

    def __str__(self):
        return f"{self.funcionario.pessoa.nome} · {self.get_tipo_display()} ({self.inicio}–{self.fim})"

    def cobre(self, data) -> bool:
        return self.inicio <= data <= self.fim


class TrocaTurno(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADA = "aprovada", "Aprovada"
        RECUSADA = "recusada", "Recusada"

    atribuicao = models.ForeignKey(Atribuicao, on_delete=models.CASCADE,
                                   related_name="trocas", verbose_name="atribuição")
    solicitante = models.ForeignKey("nucleo.Funcionario", on_delete=models.CASCADE,
                                    related_name="trocas_solicitadas", verbose_name="solicitante")
    substituto = models.ForeignKey("nucleo.Funcionario", on_delete=models.CASCADE,
                                   related_name="trocas_recebidas", verbose_name="substituto")
    motivo = models.CharField("motivo", max_length=160, blank=True)
    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.PENDENTE)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="trocas_decididas")
    criado_em = models.DateTimeField("solicitada em", auto_now_add=True)
    decidido_em = models.DateTimeField("decidida em", null=True, blank=True)

    class Meta:
        verbose_name = "troca de turno"
        verbose_name_plural = "trocas de turno"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Troca #{self.pk} — {self.get_status_display()}"

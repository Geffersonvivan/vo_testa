"""Logbook (ESPECIFICACAO §4.7): livro de ocorrências compartilhado entre turnos.

Cada ocorrência é um *tópico* com conversa (comentários) e ciclo de vida
(aberta → em andamento → resolvida). As abertas carregam para o próximo turno
até alguém fechar; o fechamento registra quem/quando/por quê.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class EntradaLogbook(models.Model):
    ABERTA = "aberta"
    EM_ANDAMENTO = "em_andamento"
    RESOLVIDA = "resolvida"
    STATUS = [
        (ABERTA, "Aberta"),
        (EM_ANDAMENTO, "Em andamento"),
        (RESOLVIDA, "Resolvida"),
    ]

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="entradas_logbook", verbose_name="autor",
    )
    texto = models.TextField("ocorrência")
    importante = models.BooleanField(
        "importante", default=False,
        help_text="Destaca a entrada para o próximo turno.",
    )
    status = models.CharField("situação", max_length=20, choices=STATUS, default=ABERTA)
    resolvida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="logbook_resolvidas", null=True, blank=True,
        verbose_name="resolvida por",
    )
    resolvida_em = models.DateTimeField("resolvida em", null=True, blank=True)
    resolucao_nota = models.CharField("como foi resolvida", max_length=280, blank=True)
    criado_em = models.DateTimeField("registrada em", auto_now_add=True)

    class Meta:
        verbose_name = "ocorrência"
        verbose_name_plural = "ocorrências"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.criado_em:%d/%m %H:%M} — {self.autor}"

    @property
    def aberta(self):
        return self.status != self.RESOLVIDA

    def marcar_resolvida(self, usuario, nota=""):
        self.status = self.RESOLVIDA
        self.resolvida_por = usuario
        self.resolvida_em = timezone.now()
        self.resolucao_nota = (nota or "").strip()[:280]

    def reabrir(self):
        self.status = self.EM_ANDAMENTO if self.comentarios.exists() else self.ABERTA
        self.resolvida_por = None
        self.resolvida_em = None
        self.resolucao_nota = ""


class ComentarioLogbook(models.Model):
    """Resposta dentro de um tópico do logbook (a parte 'chat' da ocorrência)."""

    entrada = models.ForeignKey(
        EntradaLogbook, on_delete=models.CASCADE,
        related_name="comentarios", verbose_name="ocorrência",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="comentarios_logbook", verbose_name="autor",
    )
    texto = models.TextField("resposta")
    criado_em = models.DateTimeField("respondido em", auto_now_add=True)

    class Meta:
        verbose_name = "resposta"
        verbose_name_plural = "respostas"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.criado_em:%d/%m %H:%M} — {self.autor}"

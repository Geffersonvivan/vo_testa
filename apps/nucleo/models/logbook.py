"""Logbook (ESPECIFICACAO §4.7): livro de ocorrências compartilhado entre turnos."""

from django.conf import settings
from django.db import models


class EntradaLogbook(models.Model):
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="entradas_logbook", verbose_name="autor",
    )
    texto = models.TextField("ocorrência")
    importante = models.BooleanField(
        "importante", default=False,
        help_text="Destaca a entrada para o próximo turno.",
    )
    criado_em = models.DateTimeField("registrada em", auto_now_add=True)

    class Meta:
        verbose_name = "ocorrência"
        verbose_name_plural = "ocorrências"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.criado_em:%d/%m %H:%M} — {self.autor}"

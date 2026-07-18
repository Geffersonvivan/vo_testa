"""
Módulo Frigobar (ESPECIFICACAO §5.9). Composição padrão do frigobar por TipoUH;
conferência (arrumação diária / check-out) registra o consumo, lança na conta do
quarto (natureza CONSUMO) e gera a lista de reposição; a reposição baixa o estoque
central de frigobar. Depende de Reservas + Estoque.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.nucleo.models import NaturezaFiscal


class ItemComposicao(models.Model):
    """Kit padrão do frigobar para um tipo de quarto (quanto de cada produto)."""
    tipo_uh = models.ForeignKey(
        "nucleo.TipoUH", on_delete=models.CASCADE,
        related_name="composicao_frigobar", verbose_name="tipo de quarto",
    )
    produto = models.ForeignKey(
        "nucleo.Produto", on_delete=models.PROTECT,
        related_name="composicoes_frigobar", verbose_name="produto",
    )
    quantidade = models.PositiveIntegerField("quantidade padrão", default=1)

    class Meta:
        verbose_name = "item de composição"
        verbose_name_plural = "composição do frigobar"
        ordering = ["tipo_uh__nome", "produto__nome"]
        constraints = [
            models.UniqueConstraint(fields=["tipo_uh", "produto"],
                                    name="frigobar_composicao_unica"),
        ]

    def __str__(self):
        return f"{self.tipo_uh}: {self.quantidade}× {self.produto}"


class Conferencia(models.Model):
    class Momento(models.TextChoices):
        ARRUMACAO = "arrumacao", "Arrumação diária"
        CHECKOUT = "checkout", "Check-out"

    class Status(models.TextChoices):
        CONFERIDA = "conferida", "Conferida"
        REPOSTA = "reposta", "Reposta"
        CANCELADA = "cancelada", "Cancelada"

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="conferencias_frigobar", verbose_name="quarto",
    )
    momento = models.CharField("momento", max_length=10, choices=Momento.choices,
                               default=Momento.ARRUMACAO)
    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.CONFERIDA)
    conta_ref = models.CharField("conta do quarto", max_length=120, blank=True)
    # ID da ContaHospedagem (Reservas) — solto de propósito (sem FK cruzada).
    conta_id = models.PositiveIntegerField(
        "conta id", null=True, blank=True, db_index=True,
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="conferencias_frigobar", verbose_name="conferido por",
    )
    criado_em = models.DateTimeField("conferida em", auto_now_add=True)
    reposto_em = models.DateTimeField("reposta em", null=True, blank=True)
    reposto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reposicoes_frigobar", verbose_name="reposta por",
    )

    class Meta:
        verbose_name = "conferência de frigobar"
        verbose_name_plural = "conferências de frigobar"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Conferência #{self.pk} — {self.uh.numero}"

    def total(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0.00"))

    @property
    def pendente_reposicao(self) -> bool:
        return self.status == self.Status.CONFERIDA and self.itens.exists()


class ItemConferencia(models.Model):
    conferencia = models.ForeignKey(Conferencia, on_delete=models.CASCADE,
                                    related_name="itens", verbose_name="conferência")
    produto = models.ForeignKey("nucleo.Produto", on_delete=models.PROTECT,
                                related_name="itens_frigobar", verbose_name="produto")
    descricao = models.CharField("descrição", max_length=120)
    quantidade = models.PositiveIntegerField("consumido")
    preco_unitario = models.DecimalField("preço unitário (R$)", max_digits=10,
                                         decimal_places=2)
    natureza = models.CharField("natureza fiscal", max_length=10,
                                default=NaturezaFiscal.CONSUMO)

    class Meta:
        verbose_name = "item consumido"
        verbose_name_plural = "itens consumidos"
        ordering = ["descricao"]

    def __str__(self):
        return f"{self.quantidade} × {self.descricao}"

    @property
    def subtotal(self) -> Decimal:
        return (self.preco_unitario * self.quantidade).quantize(Decimal("0.01"))

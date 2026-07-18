"""
Módulo Loja (ESPECIFICACAO §5.6) — primeiro PDV. Usa os dois motores do núcleo:
estoque (baixa na venda) e caixa (recebimento). Cobra por dois destinos:
pagamento imediato (caixa do operador) ou conta do quarto (lança na hospedagem,
via reservas.services — degrada para só balcão se Reservas estiver inativo).

Só importa models do NÚCLEO; fala com Reservas por services.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class Venda(models.Model):
    class Destino(models.TextChoices):
        CAIXA = "caixa", "Pagamento imediato"
        CONTA = "conta", "Conta do quarto"

    class Status(models.TextChoices):
        FECHADA = "fechada", "Fechada"
        CANCELADA = "cancelada", "Cancelada"

    local = models.ForeignKey(
        "nucleo.LocalEstoque", on_delete=models.PROTECT,
        related_name="vendas_loja", verbose_name="local de estoque",
    )
    destino = models.CharField("destino", max_length=8, choices=Destino.choices)
    cliente = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="compras_loja", verbose_name="cliente",
    )
    desconto = models.DecimalField(
        "desconto (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField("total (R$)", max_digits=10, decimal_places=2)

    # Pagamento imediato
    forma_pagamento = models.ForeignKey(
        "nucleo.FormaPagamento", on_delete=models.PROTECT, null=True, blank=True,
        related_name="vendas_loja", verbose_name="forma de pagamento",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="venda_loja", verbose_name="recebimento no caixa",
    )
    # Conta do quarto (referência frouxa — Reservas é outro módulo)
    conta_ref = models.CharField(
        "conta do quarto", max_length=120, blank=True,
        help_text="Quarto/hóspede onde o consumo foi lançado.",
    )

    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.FECHADA
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="vendas_loja", verbose_name="operador",
    )
    criado_em = models.DateTimeField("data/hora", auto_now_add=True)
    cancelada_em = models.DateTimeField("cancelada em", null=True, blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)

    class Meta:
        verbose_name = "venda"
        verbose_name_plural = "vendas"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Venda #{self.pk} — R$ {self.total}"

    @property
    def subtotal(self) -> Decimal:
        return self.total + self.desconto


class ItemVenda(models.Model):
    venda = models.ForeignKey(
        Venda, on_delete=models.CASCADE, related_name="itens", verbose_name="venda"
    )
    produto = models.ForeignKey(
        "nucleo.Produto", on_delete=models.PROTECT,
        related_name="itens_venda_loja", verbose_name="produto",
    )
    descricao = models.CharField("descrição", max_length=120)
    natureza = models.CharField("natureza fiscal", max_length=10)
    quantidade = models.DecimalField("quantidade", max_digits=12, decimal_places=3)
    preco_unitario = models.DecimalField(
        "preço unitário (R$)", max_digits=10, decimal_places=2
    )
    subtotal = models.DecimalField("subtotal (R$)", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "item da venda"
        verbose_name_plural = "itens da venda"

    def __str__(self):
        return f"{self.quantidade} × {self.descricao}"

"""
Módulo Restaurante Piscina (ESPECIFICACAO §5.7) — comandas abertas por mesa,
hóspede ou cliente avulso; itens lançados ao longo do dia (baixa estoque);
fechamento com pagamento imediato (caixa) ou conta do quarto. Usa os motores
do núcleo (estoque + caixa) e a conta do quarto via reservas.services.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class Mesa(models.Model):
    nome = models.CharField("nome/número", max_length=40, unique=True)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "ponto de atendimento"
        verbose_name_plural = "pontos de atendimento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Comanda(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"
        CANCELADA = "cancelada", "Cancelada"

    class Destino(models.TextChoices):
        CAIXA = "caixa", "Pagamento imediato"
        CONTA = "conta", "Conta do quarto"

    mesa = models.ForeignKey(
        Mesa, on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="ponto",
    )
    cliente = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="cliente/hóspede",
    )
    rotulo = models.CharField(
        "identificação", max_length=60, blank=True,
        help_text="Ex.: guarda-sol 4, espreguiçadeira 2.",
    )
    local = models.ForeignKey(
        "nucleo.LocalEstoque", on_delete=models.PROTECT,
        related_name="comandas", verbose_name="estoque de origem",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    destino = models.CharField(
        "destino", max_length=8, choices=Destino.choices, blank=True
    )
    desconto = models.DecimalField(
        "desconto (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    forma_pagamento = models.ForeignKey(
        "nucleo.FormaPagamento", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="forma de pagamento",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comanda", verbose_name="recebimento no caixa",
    )
    conta_ref = models.CharField("conta do quarto", max_length=120, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="comandas", verbose_name="aberta por",
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)

    class Meta:
        verbose_name = "comanda"
        verbose_name_plural = "comandas"
        ordering = ["-aberta_em"]

    def __str__(self):
        return f"Comanda #{self.pk} — {self.titulo}"

    @property
    def titulo(self) -> str:
        if self.mesa_id:
            return str(self.mesa)
        if self.rotulo:
            return self.rotulo
        if self.cliente_id:
            return self.cliente.nome
        return f"Comanda #{self.pk}"

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    def subtotal(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0.00"))

    def total(self) -> Decimal:
        return self.subtotal() - self.desconto


class ItemComanda(models.Model):
    comanda = models.ForeignKey(
        Comanda, on_delete=models.CASCADE, related_name="itens", verbose_name="comanda"
    )
    produto = models.ForeignKey(
        "nucleo.Produto", on_delete=models.PROTECT,
        related_name="itens_comanda", verbose_name="produto",
    )
    descricao = models.CharField("descrição", max_length=120)
    natureza = models.CharField("natureza fiscal", max_length=10)
    quantidade = models.DecimalField("quantidade", max_digits=12, decimal_places=3)
    preco_unitario = models.DecimalField(
        "preço unitário (R$)", max_digits=10, decimal_places=2
    )
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)

    class Meta:
        verbose_name = "item da comanda"
        verbose_name_plural = "itens da comanda"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.quantidade} × {self.descricao}"

    @property
    def subtotal(self) -> Decimal:
        return (self.preco_unitario * self.quantidade).quantize(Decimal("0.01"))

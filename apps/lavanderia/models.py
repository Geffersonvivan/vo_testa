"""
Módulo Lavanderia (ESPECIFICACAO §5.8). Duas metades:

(a) Serviço ao hóspede — ordem de lavagem (peças × tabela de preços), ciclo
    recebida → lavando → pronta → entregue; cobrança na conta do quarto (natureza
    SERVIÇO) ou no caixa. Reusa as veias do núcleo (caixa) e do Reservas (folio).

(b) Rouparia interna — enxoval da casa (lençol, toalha…) com ciclo rastreado por
    estado: limpa → em uso → suja → lavando → limpa. A coleta de roupa suja é
    disparada pela conclusão da faxina na Governança (sinal). Movimentos são
    imutáveis (livro-razão do enxoval).

Depende de Estoque; integra Governança.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.nucleo.models import NaturezaFiscal

# ───────────────────────── (a) Serviço ao hóspede ─────────────────────────

class ServicoLavanderia(models.Model):
    class Unidade(models.TextChoices):
        PECA = "peca", "Peça"
        KG = "kg", "Quilo"

    nome = models.CharField("serviço", max_length=80, unique=True)
    unidade = models.CharField("unidade", max_length=4, choices=Unidade.choices,
                               default=Unidade.PECA)
    preco = models.DecimalField("preço (R$)", max_digits=10, decimal_places=2)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "serviço de lavanderia"
        verbose_name_plural = "tabela de preços"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} (R$ {self.preco}/{self.get_unidade_display().lower()})"


class OrdemLavanderia(models.Model):
    class Status(models.TextChoices):
        RECEBIDA = "recebida", "Recebida"
        LAVANDO = "lavando", "Lavando"
        PRONTA = "pronta", "Pronta"
        ENTREGUE = "entregue", "Entregue"
        CANCELADA = "cancelada", "Cancelada"

    class Destino(models.TextChoices):
        CAIXA = "caixa", "Pagamento imediato"
        CONTA = "conta", "Conta do quarto"

    # Fluxo linear de produção antes da entrega.
    FLUXO = [Status.RECEBIDA, Status.LAVANDO, Status.PRONTA]

    cliente = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordens_lavanderia", verbose_name="cliente/hóspede",
    )
    rotulo = models.CharField("identificação", max_length=60, blank=True,
                              help_text="Ex.: quarto 12, avulso balcão.")
    prazo = models.DateField("pronto para", null=True, blank=True)
    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.RECEBIDA)
    destino = models.CharField("destino", max_length=8, choices=Destino.choices, blank=True)
    desconto = models.DecimalField("desconto (R$)", max_digits=10, decimal_places=2,
                                   default=Decimal("0.00"))
    forma_pagamento = models.ForeignKey(
        "nucleo.FormaPagamento", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordens_lavanderia", verbose_name="forma de pagamento",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordem_lavanderia", verbose_name="recebimento no caixa",
    )
    conta_ref = models.CharField("conta do quarto", max_length=120, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ordens_lavanderia", verbose_name="recebida por",
    )
    recebida_em = models.DateTimeField("recebida em", auto_now_add=True)
    entregue_em = models.DateTimeField("entregue em", null=True, blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)

    class Meta:
        verbose_name = "ordem de lavanderia"
        verbose_name_plural = "ordens de lavanderia"
        ordering = ["-recebida_em"]

    def __str__(self):
        return f"Lavanderia #{self.pk} — {self.titulo}"

    @property
    def titulo(self) -> str:
        if self.rotulo:
            return self.rotulo
        if self.cliente_id:
            return self.cliente.nome
        return f"Ordem #{self.pk}"

    @property
    def em_producao(self) -> bool:
        return self.status in self.FLUXO

    def subtotal(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0.00"))

    def total(self) -> Decimal:
        return self.subtotal() - self.desconto


class ItemOrdemLavanderia(models.Model):
    ordem = models.ForeignKey(OrdemLavanderia, on_delete=models.CASCADE,
                              related_name="itens", verbose_name="ordem")
    servico = models.ForeignKey(ServicoLavanderia, on_delete=models.PROTECT,
                                related_name="itens", verbose_name="serviço")
    descricao = models.CharField("descrição", max_length=120)
    quantidade = models.DecimalField("quantidade", max_digits=10, decimal_places=3)
    preco_unitario = models.DecimalField("preço unitário (R$)", max_digits=10,
                                         decimal_places=2)
    # Lavanderia do hóspede é sempre SERVIÇO (NFS-e), nunca consumo.
    natureza = models.CharField("natureza fiscal", max_length=10,
                                default=NaturezaFiscal.SERVICO)
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)

    class Meta:
        verbose_name = "item da ordem"
        verbose_name_plural = "itens da ordem"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.quantidade} × {self.descricao}"

    @property
    def subtotal(self) -> Decimal:
        return (self.preco_unitario * self.quantidade).quantize(Decimal("0.01"))


# ───────────────────────── (b) Rouparia interna ─────────────────────────

class ItemEnxoval(models.Model):
    nome = models.CharField("item de enxoval", max_length=80, unique=True)
    unidade = models.CharField("unidade", max_length=20, default="peça")
    minimo = models.PositiveIntegerField("estoque mínimo (limpo)", default=0)
    por_faxina = models.PositiveSmallIntegerField(
        "peças por faxina", default=0,
        help_text="Quantas peças deste item uma faxina recolhe (em uso → suja).",
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "item de enxoval"
        verbose_name_plural = "enxoval"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class MovimentoEnxoval(models.Model):
    """Livro-razão do enxoval — imutável. Cada transição de estado gera dois
    movimentos (saída do estado de origem, entrada no destino)."""

    class Estado(models.TextChoices):
        LIMPA = "limpa", "Limpa (rouparia)"
        EM_USO = "em_uso", "Em uso"
        SUJA = "suja", "Suja"
        LAVANDO = "lavando", "Lavando"

    item = models.ForeignKey(ItemEnxoval, on_delete=models.PROTECT,
                             related_name="movimentos", verbose_name="item")
    estado = models.CharField("estado", max_length=8, choices=Estado.choices)
    quantidade = models.IntegerField("quantidade (± no estado)")
    motivo = models.CharField("motivo", max_length=40)
    uh = models.ForeignKey("nucleo.UH", on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="movimentos_enxoval", verbose_name="quarto")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="movimentos_enxoval")
    criado_em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "movimento de enxoval"
        verbose_name_plural = "movimentos de enxoval"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.item} {self.get_estado_display()} {self.quantidade:+d}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Movimento de enxoval é imutável.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Movimento de enxoval não pode ser apagado.")

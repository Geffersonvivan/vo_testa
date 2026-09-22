"""Models da conciliação bancária (OFX) e de cartão (NSU/SafraPay).

Área-core do Financeiro (não é módulo contratável). Referencia livremente os models
do núcleo (`MovimentoCaixa`, `ContaPagarReceber`, `LancamentoFinanceiro`) — o núcleo é a
exceção à regra de não-importação entre apps.

Princípio: **nada aqui altera os movimentos do CRM.** As linhas importadas (extrato/cartão)
são imutáveis e a conciliação só grava o *vínculo* (qual registro do CRM casou), o status e
a trilha (quem/quando). O motor de pareamento vive em `matching.py` (funções puras).
"""
from django.conf import settings
from django.db import models

from apps.nucleo.models.financeiro import (
    ContaPagarReceber,
    LancamentoFinanceiro,
    MovimentoCaixa,
)


# ── Extrato bancário (OFX) ────────────────────────────────────────────────────
class ExtratoBancario(models.Model):
    """Lote de importação de um extrato (OFX) de uma conta bancária."""

    banco = models.CharField("banco", max_length=60, default="Banco Safra")
    conta = models.CharField("conta", max_length=40, blank=True)
    periodo_inicio = models.DateField("período de", null=True, blank=True)
    periodo_fim = models.DateField("período até", null=True, blank=True)
    arquivo_nome = models.CharField("arquivo", max_length=200, blank=True)
    importado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="extratos_importados", verbose_name="importado por",
    )
    importado_em = models.DateTimeField("importado em", auto_now_add=True)

    class Meta:
        verbose_name = "extrato bancário"
        verbose_name_plural = "extratos bancários"
        ordering = ["-importado_em"]

    def __str__(self):
        return f"{self.banco} {self.conta} — {self.periodo_inicio}…{self.periodo_fim}"


class LancamentoExtrato(models.Model):
    """Uma linha do extrato — IMUTÁVEL. valor > 0 = crédito, valor < 0 = débito."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONCILIADO = "conciliado", "Conciliado"
        IGNORADO = "ignorado", "Ignorado"

    extrato = models.ForeignKey(
        ExtratoBancario, on_delete=models.CASCADE, related_name="lancamentos",
        verbose_name="extrato",
    )
    data = models.DateField("data")
    valor = models.DecimalField(
        "valor (R$)", max_digits=12, decimal_places=2,
        help_text="Positivo = crédito (entrada); negativo = débito (saída).",
    )
    descricao = models.CharField("descrição", max_length=255, blank=True)
    fitid = models.CharField("id da transação (FITID)", max_length=100, blank=True)
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PENDENTE
    )
    # Vínculo de conciliação (o registro do CRM que casou — no máximo um).
    movimento_caixa = models.ForeignKey(
        MovimentoCaixa, on_delete=models.PROTECT, null=True, blank=True,
        related_name="conciliacoes_extrato", verbose_name="movimento de caixa",
    )
    conta = models.ForeignKey(
        ContaPagarReceber, on_delete=models.PROTECT, null=True, blank=True,
        related_name="conciliacoes_extrato", verbose_name="conta a pagar/receber",
    )
    confianca = models.CharField("confiança", max_length=10, blank=True)  # exata/provavel/manual
    conciliado_em = models.DateTimeField("conciliado em", null=True, blank=True)
    conciliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="lancamentos_extrato_conciliados", verbose_name="conciliado por",
    )

    class Meta:
        verbose_name = "lançamento do extrato"
        verbose_name_plural = "lançamentos do extrato"
        ordering = ["data", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["extrato", "fitid"],
                condition=~models.Q(fitid=""),
                name="lancext_fitid_unico_por_extrato",
            ),
        ]

    def __str__(self):
        return f"{self.data} R$ {self.valor} — {self.descricao[:40]}"

    @property
    def credito(self) -> bool:
        return self.valor > 0


# ── Vendas de cartão (adquirente / SafraPay) ─────────────────────────────────
class LoteCartao(models.Model):
    """Lote de importação do arquivo de vendas da adquirente."""

    adquirente = models.CharField("adquirente", max_length=40, default="SafraPay")
    arquivo_nome = models.CharField("arquivo", max_length=200, blank=True)
    importado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="lotes_cartao", verbose_name="importado por",
    )
    importado_em = models.DateTimeField("importado em", auto_now_add=True)

    class Meta:
        verbose_name = "lote de cartão"
        verbose_name_plural = "lotes de cartão"
        ordering = ["-importado_em"]

    def __str__(self):
        return f"{self.adquirente} — {self.arquivo_nome or self.importado_em:%d/%m/%Y}"


class TransacaoCartao(models.Model):
    """Uma venda no cartão pela adquirente, identificada por NSU — IMUTÁVEL."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONCILIADO = "conciliado", "Conciliado"
        SEM_VENDA = "sem_venda", "Sem venda no caixa"

    lote = models.ForeignKey(
        LoteCartao, on_delete=models.CASCADE, related_name="transacoes", verbose_name="lote",
    )
    data_venda = models.DateField("data da venda")
    data_liquidacao = models.DateField("data da liquidação", null=True, blank=True)
    nsu = models.CharField("NSU", max_length=40)
    autorizacao = models.CharField("autorização", max_length=40, blank=True)
    bandeira = models.CharField("bandeira", max_length=30, blank=True)
    bruto = models.DecimalField("valor bruto (R$)", max_digits=12, decimal_places=2)
    taxa = models.DecimalField("taxa (R$)", max_digits=12, decimal_places=2, default=0)
    liquido = models.DecimalField("valor líquido (R$)", max_digits=12, decimal_places=2)
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PENDENTE
    )
    # Vínculo de conciliação
    movimento_caixa = models.ForeignKey(
        MovimentoCaixa, on_delete=models.PROTECT, null=True, blank=True,
        related_name="conciliacoes_cartao", verbose_name="recebimento no caixa",
    )
    divergencia_valor = models.DecimalField(
        "divergência de valor (R$)", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    lancamento_taxa = models.OneToOneField(
        LancamentoFinanceiro, on_delete=models.PROTECT, null=True, blank=True,
        related_name="taxa_cartao", verbose_name="lançamento da taxa",
    )
    conciliado_em = models.DateTimeField("conciliado em", null=True, blank=True)
    conciliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transacoes_cartao_conciliadas", verbose_name="conciliado por",
    )

    class Meta:
        verbose_name = "transação de cartão"
        verbose_name_plural = "transações de cartão"
        ordering = ["data_venda", "id"]

    def __str__(self):
        return f"NSU {self.nsu} — R$ {self.bruto} ({self.bandeira})"

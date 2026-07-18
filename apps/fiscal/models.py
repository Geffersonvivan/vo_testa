"""
Módulo Fiscal (ESPECIFICACAO §14) — emissão de nota eletrônica com **gateway
plugável** (mesmo padrão de Pagamentos): SERVIÇO → NFS-e (Nacional); CONSUMO →
NFC-e (SEFAZ-SC). Provedor real a definir (Focus NFe recomendado; rota grátis pelo
governo possível). Ver docs/Implementar_fiscal.md.

Este é o ESQUELETO: o backend `simulado` (sandbox) já funciona ponta a ponta para
testar o fluxo; `focus` e `governo` são stubs a preencher com credenciais/endpoints.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.nucleo.models import NaturezaFiscal


class ConfigFiscalProduto(models.Model):
    """Códigos fiscais por produto (fornecidos pelo contador) — para o CONSUMO/NFC-e."""
    produto = models.OneToOneField(
        "nucleo.Produto", on_delete=models.CASCADE,
        related_name="config_fiscal", verbose_name="produto",
    )
    ncm = models.CharField("NCM", max_length=10, blank=True)
    cfop = models.CharField("CFOP", max_length=5, blank=True)
    cst_csosn = models.CharField("CST/CSOSN", max_length=5, blank=True)
    origem = models.CharField("origem", max_length=1, blank=True, default="0")

    class Meta:
        verbose_name = "configuração fiscal do produto"
        verbose_name_plural = "configuração fiscal dos produtos"

    def __str__(self):
        return f"Fiscal: {self.produto}"


class DocumentoFiscal(models.Model):
    class Tipo(models.TextChoices):
        NFSE = "nfse", "NFS-e (serviço)"
        NFCE = "nfce", "NFC-e (consumo)"
        NFE = "nfe", "NF-e"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PROCESSANDO = "processando", "Processando"
        AUTORIZADA = "autorizada", "Autorizada"
        REJEITADA = "rejeitada", "Rejeitada"
        CANCELADA = "cancelada", "Cancelada"

    tipo = models.CharField("tipo", max_length=5, choices=Tipo.choices)
    natureza = models.CharField("natureza", max_length=10, choices=NaturezaFiscal.choices)
    status = models.CharField("status", max_length=12, choices=Status.choices,
                              default=Status.PENDENTE)
    descricao = models.CharField("descrição", max_length=200)
    valor = models.DecimalField("valor (R$)", max_digits=12, decimal_places=2,
                                default=Decimal("0.00"))
    tomador = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="documentos_fiscais", verbose_name="tomador/destinatário",
    )
    # Origem no sistema (conta/venda/comanda) — referência solta para não acoplar models.
    referencia = models.CharField("origem", max_length=120, blank=True)

    # Retorno do provedor/fisco.
    gateway = models.CharField("gateway", max_length=20, blank=True)
    gateway_id = models.CharField("id no gateway", max_length=80, blank=True)
    numero = models.CharField("número", max_length=30, blank=True)
    serie = models.CharField("série", max_length=10, blank=True)
    chave = models.CharField("chave de acesso", max_length=60, blank=True)
    protocolo = models.CharField("protocolo", max_length=60, blank=True)
    xml_url = models.URLField("XML", blank=True)
    pdf_url = models.URLField("PDF/DANFE", blank=True)
    motivo_rejeicao = models.CharField("motivo da rejeição", max_length=255, blank=True)
    payload = models.JSONField("payload", default=dict, blank=True)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="documentos_fiscais", verbose_name="emitido por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    autorizada_em = models.DateTimeField("autorizada em", null=True, blank=True)

    class Meta:
        verbose_name = "documento fiscal"
        verbose_name_plural = "documentos fiscais"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} #{self.pk} — {self.get_status_display()}"

    @property
    def autorizada(self) -> bool:
        return self.status == self.Status.AUTORIZADA


class EventoFiscal(models.Model):
    """Trilha do ciclo de vida do documento (emissão, autorização, rejeição, cancelamento)."""
    documento = models.ForeignKey(DocumentoFiscal, on_delete=models.CASCADE,
                                  related_name="eventos", verbose_name="documento")
    tipo = models.CharField("evento", max_length=20)
    detalhe = models.JSONField("detalhe", default=dict, blank=True)
    criado_em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "evento fiscal"
        verbose_name_plural = "eventos fiscais"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.tipo} · doc #{self.documento_id}"

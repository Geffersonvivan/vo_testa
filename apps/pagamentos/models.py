"""
Módulo Pagamentos Online (ESPECIFICACAO §5.10). Cobranças por Pix, cartão, boleto
ou link de pagamento, com gateway **plugável** (o gateway brasileiro fica a definir,
§9). A confirmação (webhook do gateway) marca a cobrança como paga e, quando é sinal
de reserva, confirma a reserva. Estorno e conciliação (gateway × sistema) previstos.
Depende só do Núcleo; integra Reservas por service (degradação graciosa).
"""
import uuid

from django.conf import settings
from django.db import models


class Cobranca(models.Model):
    class Metodo(models.TextChoices):
        PIX = "pix", "Pix"
        CARTAO = "cartao", "Cartão de crédito"
        BOLETO = "boleto", "Boleto"
        LINK = "link", "Link de pagamento"

    class Finalidade(models.TextChoices):
        SINAL = "sinal_reserva", "Sinal de reserva"
        SALDO = "saldo_conta", "Saldo da conta"
        AVULSO = "avulso", "Avulso"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        EXPIRADO = "expirado", "Expirado"
        CANCELADO = "cancelado", "Cancelado"
        ESTORNADO = "estornado", "Estornado"

    token = models.UUIDField("token público", default=uuid.uuid4, unique=True, editable=False)
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)
    metodo = models.CharField("método", max_length=8, choices=Metodo.choices)
    parcelas = models.PositiveSmallIntegerField("parcelas", default=1)
    descricao = models.CharField("descrição", max_length=160)
    finalidade = models.CharField("finalidade", max_length=14, choices=Finalidade.choices,
                                  default=Finalidade.AVULSO)
    pagador = models.ForeignKey("nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
                                related_name="cobrancas", verbose_name="pagador")
    # Referência solta à reserva (sem import cruzado de model).
    reserva_id = models.PositiveIntegerField("reserva", null=True, blank=True)

    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.PENDENTE)
    # Dados devolvidos pelo gateway.
    gateway = models.CharField("gateway", max_length=30, blank=True)
    gateway_id = models.CharField("id no gateway", max_length=80, blank=True)
    pix_copia_cola = models.TextField("Pix copia-e-cola", blank=True)
    expira_em = models.DateTimeField("expira em", null=True, blank=True)
    payload = models.JSONField("payload do gateway", default=dict, blank=True)

    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="cobrancas", verbose_name="criada por")
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    pago_em = models.DateTimeField("paga em", null=True, blank=True)

    class Meta:
        verbose_name = "cobrança"
        verbose_name_plural = "cobranças"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Cobrança #{self.pk} — {self.get_metodo_display()} R$ {self.valor}"

    @property
    def paga(self) -> bool:
        return self.status == self.Status.PAGO

    @property
    def pendente(self) -> bool:
        return self.status == self.Status.PENDENTE


class EventoPagamento(models.Model):
    """Trilha do ciclo de vida da cobrança (inclui webhooks) — imutável."""
    class Tipo(models.TextChoices):
        CRIADA = "criada", "Criada"
        PAGA = "paga", "Paga"
        ESTORNADA = "estornada", "Estornada"
        CANCELADA = "cancelada", "Cancelada"
        WEBHOOK = "webhook", "Webhook"

    cobranca = models.ForeignKey(Cobranca, on_delete=models.CASCADE,
                                 related_name="eventos", verbose_name="cobrança")
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    origem = models.CharField("origem", max_length=30, blank=True)
    detalhe = models.JSONField("detalhe", default=dict, blank=True)
    criado_em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "evento de pagamento"
        verbose_name_plural = "eventos de pagamento"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} · cobrança #{self.cobranca_id}"

"""
Portal do Hóspede (ESPECIFICACAO §5.11, metade B). Área pública acessada por
QR Code/link com token opaco durante a estadia. Não tem lógica própria: lê a conta
via reservas.services e dispara comanda/faxina/OS/pagamento pelos services dos
módulos. Depende de Reservas + Pagamentos.
"""
import uuid

from django.db import models


class AcessoPortal(models.Model):
    """Token opaco por reserva — a chave do portal (não expõe o pk da reserva)."""
    reserva_id = models.PositiveIntegerField("reserva", unique=True)
    token = models.UUIDField("token", default=uuid.uuid4, unique=True, editable=False)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "acesso ao portal"
        verbose_name_plural = "acessos ao portal"

    def __str__(self):
        return f"Portal reserva #{self.reserva_id}"


class SolicitacaoPortal(models.Model):
    """Registro leve do que o hóspede pediu pelo portal (para trilha/painel)."""
    class Tipo(models.TextChoices):
        RESTAURANTE = "restaurante", "Pedido no restaurante"
        LIMPEZA = "limpeza", "Limpeza extra"
        MANUTENCAO = "manutencao", "Manutenção"
        CHECKOUT = "checkout", "Check-out expresso"

    reserva_id = models.PositiveIntegerField("reserva")
    uh_numero = models.CharField("quarto", max_length=20, blank=True)
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    detalhe = models.CharField("detalhe", max_length=200, blank=True)
    criado_em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "solicitação do portal"
        verbose_name_plural = "solicitações do portal"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} · quarto {self.uh_numero}"

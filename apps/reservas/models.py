"""
Módulo Reservas (ESPECIFICACAO §5.1) — o carro-chefe.

Fonte de verdade da DISPONIBILIDADE. Regras que não se quebram:
- Overbooking é impossível no banco: ExclusionConstraint (PostgreSQL) impede
  duas reservas ativas na mesma UH com períodos sobrepostos.
- Todo lançamento da conta carrega natureza fiscal (SERVIÇO | CONSUMO),
  obrigatória, sem default silencioso.
- Pagamento da conta passa pelo caixa do operador (MovimentoCaixa do núcleo).
- Cancelamento exige motivo; ações sensíveis são auditadas.

Só importa models do NÚCLEO (permitido) — nunca de outros módulos.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Func, Q, Sum
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, Temporada, registrar_auditoria


class Tarifa(models.Model):
    """Matriz TipoUH × classificação de temporada. Sem linha → tarifa_base do tipo."""

    tipo_uh = models.ForeignKey(
        "nucleo.TipoUH", on_delete=models.CASCADE,
        related_name="tarifas", verbose_name="tipo de UH",
    )
    classificacao = models.CharField(
        "classificação da temporada", max_length=12,
        choices=Temporada.Classificacao.choices,
    )
    valor = models.DecimalField(
        "diária (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        verbose_name = "tarifa"
        verbose_name_plural = "tarifas"
        ordering = ["tipo_uh__nome", "classificacao"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_uh", "classificacao"],
                name="tarifa_unica_por_tipo_e_classificacao",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_uh.nome} / {self.get_classificacao_display()}: R$ {self.valor}"


class Reserva(models.Model):
    """
    Ciclo: Orçamento → Pré-reserva → Confirmada → Hospedada → Check-out.
    Orçamento não segura UH; os demais estados ativos seguram (constraint).
    """

    class Status(models.TextChoices):
        ORCAMENTO = "orcamento", "Orçamento"
        PRE_RESERVA = "pre_reserva", "Pré-reserva"
        CONFIRMADA = "confirmada", "Confirmada"
        HOSPEDADA = "hospedada", "Hospedada"
        CHECKOUT = "checkout", "Saída"
        CANCELADA = "cancelada", "Cancelada"
        NO_SHOW = "no_show", "Não compareceu"

    # Estados que seguram a UH (entram na constraint antioverbooking)
    STATUS_ATIVOS = [Status.PRE_RESERVA, Status.CONFIRMADA, Status.HOSPEDADA]

    class Canal(models.TextChoices):
        BALCAO = "balcao", "Balcão/telefone"
        WHATSAPP = "whatsapp", "WhatsApp"
        SITE = "site", "Site/APP"
        OTA = "ota", "Sites de reserva (Booking/Airbnb)"

    class Faturamento(models.TextChoices):
        PARTICULAR = "particular", "Particular (o hóspede paga)"
        AGENCIA = "agencia", "Agência"
        EMPRESA = "empresa", "Empresa"

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="reservas", verbose_name="quarto",
    )
    hospede = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT,
        related_name="reservas", verbose_name="hóspede",
    )
    faturamento = models.CharField(
        "faturamento", max_length=12, choices=Faturamento.choices,
        default=Faturamento.PARTICULAR,
    )
    titular = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="reservas_faturadas", verbose_name="titular do faturamento",
        help_text="Quem paga a conta, quando não é o próprio hóspede (agência/empresa).",
    )
    checkin = models.DateField("entrada (check-in)")
    checkout = models.DateField("saída (check-out)")
    adultos = models.PositiveSmallIntegerField("adultos", default=2)
    criancas = models.PositiveSmallIntegerField("crianças", default=0)
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PRE_RESERVA
    )
    canal = models.CharField(
        "canal", max_length=10, choices=Canal.choices, default=Canal.BALCAO
    )
    valor_diaria = models.DecimalField(
        "diária acordada (R$)", max_digits=10, decimal_places=2,
        help_text="Preenchida pela tarifa vigente; alteração manual exige gerência.",
    )
    observacoes = models.TextField("observações", blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)
    expira_em = models.DateTimeField(
        "retenção até", null=True, blank=True,
        help_text="Pré-reserva de canal (site) segura o quarto só até aqui; depois expira.",
    )
    checkin_real = models.DateTimeField("entrada realizada em", null=True, blank=True)
    checkout_real = models.DateTimeField("saída realizada em", null=True, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="reservas_criadas", verbose_name="criada por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["-checkin"]
        constraints = [
            models.CheckConstraint(
                condition=Q(checkout__gt=F("checkin")),
                name="reserva_checkout_depois_do_checkin",
            ),
            # Antioverbooking: duas reservas ativas não podem ocupar a mesma UH
            # em períodos sobrepostos. daterange é [checkin, checkout) — a noite
            # do checkout fica livre para a próxima entrada.
            ExclusionConstraint(
                name="reserva_sem_overbooking",
                expressions=[
                    (F("uh"), RangeOperators.EQUAL),
                    (
                        Func(
                            F("checkin"), F("checkout"),
                            function="daterange",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status__in=["pre_reserva", "confirmada", "hospedada"]),
            ),
        ]

    def __str__(self):
        return (
            f"Reserva #{self.pk} — {self.hospede.nome} — {self.uh.numero} "
            f"({self.checkin:%d/%m} → {self.checkout:%d/%m})"
        )

    @property
    def noites(self) -> int:
        return (self.checkout - self.checkin).days

    @property
    def ativa(self) -> bool:
        return self.status in self.STATUS_ATIVOS

    @property
    def pagador(self):
        """Quem paga: o titular do faturamento ou, se particular, o próprio hóspede."""
        return self.titular or self.hospede

    @property
    def status_ajuda(self) -> str:
        """Explicação do status, para dica ao passar o mouse."""
        return {
            self.Status.ORCAMENTO: "Cotação de preço — não segura o quarto.",
            self.Status.PRE_RESERVA: "Reserva provisória — segura o quarto por um tempo até a confirmação.",
            self.Status.CONFIRMADA: "Sinal recebido ou garantia registrada.",
            self.Status.HOSPEDADA: "Hóspede em casa (entrada já feita).",
            self.Status.CHECKOUT: "Estadia encerrada (saída já feita).",
            self.Status.CANCELADA: "Reserva cancelada.",
            self.Status.NO_SHOW: "Confirmada, mas o hóspede não compareceu.",
        }.get(self.status, "")

    def clean(self):
        if self.checkin and self.checkout and self.checkout <= self.checkin:
            raise ValidationError(
                {"checkout": "A saída (check-out) deve ser depois da entrada (check-in)."}
            )
        if self.faturamento != self.Faturamento.PARTICULAR and not self.titular_id:
            raise ValidationError(
                {"titular": "Faturamento por agência/empresa exige o titular."}
            )
        if self.faturamento == self.Faturamento.PARTICULAR:
            # Particular: o hóspede é o pagador; não guardamos titular separado.
            self.titular = None

    # ---- Transições de estado ----

    def _exige_status(self, *validos):
        if self.status not in validos:
            nomes = ", ".join(self.Status(s).label for s in validos)
            raise ValidationError(
                f"Ação disponível apenas para reserva em: {nomes}."
            )

    def confirmar(self, usuario):
        """Pré-reserva/orçamento → confirmada (sinal recebido ou garantia)."""
        self._exige_status(self.Status.ORCAMENTO, self.Status.PRE_RESERVA)
        self.status = self.Status.CONFIRMADA
        self.expira_em = None  # confirmada não expira mais
        self.save()

    def fazer_checkin(self, usuario):
        self._exige_status(self.Status.CONFIRMADA, self.Status.PRE_RESERVA)
        if self.uh.status != self.uh.Status.ATIVA:
            raise ValidationError(
                f"O quarto {self.uh.numero} está {self.uh.get_status_display().lower()}."
            )
        # Governança ativa: só entra em quarto limpo/inspecionado (degrada se off).
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if modulo_ativo(Modulo.GOVERNANCA):
            from apps.governanca.services import uh_pronta_para_checkin

            if not uh_pronta_para_checkin(self.uh):
                raise ValidationError(
                    f"O quarto {self.uh.numero} não está limpo/inspecionado — "
                    "aguarde a governança."
                )
        self.status = self.Status.HOSPEDADA
        self.checkin_real = timezone.now()
        self.save()
        conta = ContaHospedagem.objects.create(reserva=self)
        conta.lancar_diarias(usuario)
        return conta

    def fazer_checkout(self, usuario):
        self._exige_status(self.Status.HOSPEDADA)
        conta = self.conta
        if conta.saldo() != Decimal("0.00"):
            raise ValidationError(
                f"A conta tem saldo de R$ {conta.saldo()} — receba ou ajuste antes."
            )
        # Frigobar ativo: exige conferência de check-out (mesmo zerada).
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if (
            modulo_ativo(Modulo.FRIGOBAR)
            and getattr(settings, "FRIGOBAR_BLOQUEAR_CHECKOUT", True)
        ):
            from apps.frigobar.services import conferencia_checkout_feita

            if not conferencia_checkout_feita(conta=conta):
                raise ValidationError(
                    "Conferência do frigobar pendente — registre o consumo "
                    "(mesmo zerado) antes da saída."
                )
        conta.status = ContaHospedagem.Status.FECHADA
        conta.fechada_em = timezone.now()
        conta.save()
        self.status = self.Status.CHECKOUT
        self.checkout_real = timezone.now()
        self.save()
        # Governança (se ativa) escuta este sinal para gerar a faxina.
        from .signals import quarto_liberado

        quarto_liberado.send(
            sender=self.__class__, uh=self.uh, reserva=self,
            usuario=usuario, origem="checkout",
        )

    def cancelar(self, usuario, motivo: str):
        self._exige_status(
            self.Status.ORCAMENTO, self.Status.PRE_RESERVA, self.Status.CONFIRMADA
        )
        if not motivo.strip():
            raise ValidationError("Informe o motivo do cancelamento.")
        self.status = self.Status.CANCELADA
        self.motivo_cancelamento = motivo
        self.save()
        registrar_auditoria(
            usuario, "cancelamento_reserva", self, {"motivo": motivo}
        )
        from .signals import reserva_encerrada

        reserva_encerrada.send(
            sender=self.__class__, reserva=self, evento="cancelada",
            motivo=motivo, usuario=usuario,
        )

    def marcar_no_show(self, usuario):
        self._exige_status(self.Status.CONFIRMADA)
        self.status = self.Status.NO_SHOW
        self.save()
        registrar_auditoria(usuario, "no_show", self, {})
        from .signals import reserva_encerrada

        reserva_encerrada.send(
            sender=self.__class__, reserva=self, evento="no_show",
            motivo="", usuario=usuario,
        )


class Acompanhante(models.Model):
    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE,
        related_name="acompanhantes", verbose_name="reserva",
    )
    nome = models.CharField("nome", max_length=150)
    documento = models.CharField("documento", max_length=30, blank=True)

    class Meta:
        verbose_name = "acompanhante"
        verbose_name_plural = "acompanhantes"

    def __str__(self):
        return self.nome


class ContaHospedagem(models.Model):
    """Folio: diárias, consumos, serviços e descontos; crédito de adiantamentos."""

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"

    reserva = models.OneToOneField(
        Reserva, on_delete=models.PROTECT, related_name="conta", verbose_name="reserva"
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)

    class Meta:
        verbose_name = "conta do quarto"
        verbose_name_plural = "contas de quarto"

    def __str__(self):
        return f"Conta da reserva #{self.reserva_id} ({self.get_status_display()})"

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    def lancar_diarias(self, usuario):
        """Lança uma diária (SERVIÇO) por noite, pela diária acordada da reserva."""
        reserva = self.reserva
        for n in range(reserva.noites):
            dia = reserva.checkin + timezone.timedelta(days=n)
            LancamentoConta.objects.create(
                conta=self,
                tipo=LancamentoConta.Tipo.DIARIA,
                natureza=NaturezaFiscal.SERVICO,
                descricao=f"Diária {dia:%d/%m/%Y} — {reserva.uh.numero}",
                valor=reserva.valor_diaria,
                criado_por=usuario,
            )

    # ---- Totais ----

    def _total(self, **filtros) -> Decimal:
        return self.lancamentos.filter(**filtros).aggregate(t=Sum("valor"))[
            "t"
        ] or Decimal("0.00")

    def total_lancamentos(self) -> Decimal:
        """Débitos menos descontos."""
        debitos = self._total(tipo__in=LancamentoConta.TIPOS_DEBITO)
        descontos = self._total(tipo=LancamentoConta.Tipo.DESCONTO)
        return debitos - descontos

    def total_por_natureza(self) -> dict:
        """Subtotais SERVIÇO × CONSUMO (descontos abatem da própria natureza)."""
        resultado = {}
        for natureza in NaturezaFiscal:
            debitos = self._total(
                tipo__in=LancamentoConta.TIPOS_DEBITO, natureza=natureza
            )
            descontos = self._total(
                tipo=LancamentoConta.Tipo.DESCONTO, natureza=natureza
            )
            resultado[natureza.label] = debitos - descontos
        return resultado

    def total_pago(self) -> Decimal:
        return self.pagamentos.aggregate(t=Sum("valor"))["t"] or Decimal("0.00")

    def total_adiantamentos(self) -> Decimal:
        return self.reserva.adiantamentos.aggregate(t=Sum("valor"))["t"] or Decimal(
            "0.00"
        )

    def saldo(self) -> Decimal:
        """O que falta receber: lançamentos − pagamentos − adiantamentos."""
        return self.total_lancamentos() - self.total_pago() - self.total_adiantamentos()


class LancamentoConta(models.Model):
    """
    Lançamento do folio. Natureza fiscal obrigatória (4ª veia): SERVIÇO ou
    CONSUMO, para extrato separado e futura emissão de nota (módulo Fiscal).
    """

    class Tipo(models.TextChoices):
        DIARIA = "diaria", "Diária"
        CONSUMO = "consumo", "Consumo"
        SERVICO = "servico", "Serviço"
        DESCONTO = "desconto", "Desconto"

    TIPOS_DEBITO = [Tipo.DIARIA, Tipo.CONSUMO, Tipo.SERVICO]

    conta = models.ForeignKey(
        ContaHospedagem, on_delete=models.PROTECT,
        related_name="lancamentos", verbose_name="conta",
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    natureza = models.CharField(
        "natureza fiscal", max_length=10, choices=NaturezaFiscal.choices
    )
    descricao = models.CharField("descrição", max_length=200)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="lancamentos_conta", verbose_name="lançado por",
    )
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)

    class Meta:
        verbose_name = "lançamento da conta"
        verbose_name_plural = "lançamentos da conta"
        ordering = ["criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valor__gt=0), name="lancamento_conta_valor_positivo"
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.descricao} (R$ {self.valor})"

    def clean(self):
        if self.conta_id and not self.conta.aberta:
            raise ValidationError("A conta deste quarto já foi fechada.")
        if not self.natureza:
            raise ValidationError({"natureza": "Informe a natureza fiscal."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Lançamento de conta não é editado — lance um desconto/ajuste."
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Lançamento de conta não é apagado — lance um desconto/ajuste."
        )


class PagamentoConta(models.Model):
    """
    Pagamento da conta: sempre atrelado a um movimento do caixa do operador
    (a veia do dinheiro). Estorno = estorno do movimento no caixa.
    """

    conta = models.ForeignKey(
        ContaHospedagem, on_delete=models.PROTECT,
        related_name="pagamentos", verbose_name="conta",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT,
        related_name="pagamento_conta", verbose_name="movimento de caixa",
    )
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)
    observacao = models.CharField(
        "pagador / observação", max_length=120, blank=True,
        help_text="Quem pagou esta parte (ex.: 'Casal A', 'cartão do João') — para rateio.",
    )
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "pagamento da conta"
        verbose_name_plural = "pagamentos da conta"
        ordering = ["criado_em"]

    def __str__(self):
        return f"Pagamento R$ {self.valor} — conta #{self.conta_id}"


class Adiantamento(models.Model):
    """Valor recebido antes do check-in, vinculado à reserva; crédito na conta."""

    reserva = models.ForeignKey(
        Reserva, on_delete=models.PROTECT,
        related_name="adiantamentos", verbose_name="reserva",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT,
        related_name="adiantamento", verbose_name="movimento de caixa",
    )
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField("recebido em", auto_now_add=True)

    class Meta:
        verbose_name = "adiantamento"
        verbose_name_plural = "adiantamentos"
        ordering = ["criado_em"]

    def __str__(self):
        return f"Adiantamento R$ {self.valor} — reserva #{self.reserva_id}"

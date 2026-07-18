"""
Financeiro & Caixa do núcleo (ESPECIFICACAO §4.3) — a "veia" do dinheiro:
toda cobrança de qualquer módulo passa por aqui, pelo caixa do operador
daquele módulo.

Regras que não se quebram:
- Dinheiro é DecimalField, nunca float.
- MovimentoCaixa é imutável: correção = movimento inverso (estorno), nunca
  update/delete.
- Estorno exige motivo e referência ao movimento original; sempre auditado.
- Uma sessão de caixa aberta por operador × módulo (constraint no banco).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from ..modulos import Modulo

CENTRO_NUCLEO = "nucleo"


def centro_choices() -> list[tuple[str, str]]:
    """Centros de receita/custo = núcleo (recepção/administração) + módulos."""
    return [(CENTRO_NUCLEO, "Núcleo / Recepção")] + list(Modulo.choices)


class NaturezaFiscal(models.TextChoices):
    """
    4ª veia transversal: todo item vendável e todo lançamento de conta nasce
    SERVIÇO (NFS-e/ISS) ou CONSUMO (NF-e/NFC-e/ICMS). Obrigatória, sem default.
    """

    SERVICO = "servico", "Serviço"
    CONSUMO = "consumo", "Consumo"


class FormaPagamento(models.Model):
    class Tipo(models.TextChoices):
        DINHEIRO = "dinheiro", "Dinheiro"
        PIX = "pix", "Pix"
        CARTAO_DEBITO = "cartao_debito", "Cartão de débito"
        CARTAO_CREDITO = "cartao_credito", "Cartão de crédito"
        TRANSFERENCIA = "transferencia", "Transferência"
        CORTESIA = "cortesia", "Cortesia"

    nome = models.CharField("nome", max_length=60, unique=True)
    tipo = models.CharField("tipo", max_length=15, choices=Tipo.choices)
    permite_parcelamento = models.BooleanField("permite parcelamento", default=False)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "forma de pagamento"
        verbose_name_plural = "formas de pagamento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class SessaoCaixa(models.Model):
    """
    Sessão de caixa de um operador em um módulo: abre com fundo de troco,
    registra movimentos, fecha com conferência cega do dinheiro em gaveta.
    """

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"

    operador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="sessoes_caixa", verbose_name="operador",
    )
    modulo = models.CharField("módulo (centro)", max_length=20)
    fundo_troco = models.DecimalField(
        "fundo de troco (R$)", max_digits=10, decimal_places=2,
        default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)
    valor_contado = models.DecimalField(
        "dinheiro contado no fechamento (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    diferenca = models.DecimalField(
        "diferença (contado − esperado)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    observacoes_fechamento = models.TextField("observações do fechamento", blank=True)

    class Meta:
        verbose_name = "sessão de caixa"
        verbose_name_plural = "sessões de caixa"
        ordering = ["-aberta_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["operador", "modulo"],
                condition=Q(status="aberta"),
                name="uma_sessao_aberta_por_operador_modulo",
            ),
        ]

    def __str__(self):
        return (
            f"Caixa {self.get_modulo_display()} — {self.operador} "
            f"({self.get_status_display()})"
        )

    def get_modulo_display(self):
        return dict(centro_choices()).get(self.modulo, self.modulo)

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    def _soma(self, **filtros) -> Decimal:
        total = self.movimentos.filter(**filtros).aggregate(t=Sum("valor"))["t"]
        return total or Decimal("0.00")

    def esperado_em_dinheiro(self) -> Decimal:
        """
        Dinheiro que deve estar na gaveta: fundo + recebimentos em dinheiro
        + reforços − sangrias − estornos devolvidos em dinheiro.
        """
        recebido = self._soma(
            tipo=MovimentoCaixa.Tipo.RECEBIMENTO,
            forma_pagamento__tipo=FormaPagamento.Tipo.DINHEIRO,
        )
        estornado = self._soma(
            tipo=MovimentoCaixa.Tipo.ESTORNO,
            forma_pagamento__tipo=FormaPagamento.Tipo.DINHEIRO,
        )
        reforcos = self._soma(tipo=MovimentoCaixa.Tipo.REFORCO)
        sangrias = self._soma(tipo=MovimentoCaixa.Tipo.SANGRIA)
        return self.fundo_troco + recebido + reforcos - sangrias - estornado

    def totais_por_forma(self):
        """Recebimentos líquidos (recebido − estornado) por forma de pagamento."""
        linhas = (
            self.movimentos.filter(
                tipo__in=[MovimentoCaixa.Tipo.RECEBIMENTO, MovimentoCaixa.Tipo.ESTORNO]
            )
            .values("forma_pagamento__nome", "tipo")
            .annotate(total=Sum("valor"))
        )
        totais: dict[str, Decimal] = {}
        for linha in linhas:
            nome = linha["forma_pagamento__nome"]
            sinal = 1 if linha["tipo"] == MovimentoCaixa.Tipo.RECEBIMENTO else -1
            totais[nome] = totais.get(nome, Decimal("0.00")) + sinal * linha["total"]
        return sorted(totais.items())

    def fechar(self, valor_contado: Decimal, usuario, observacoes: str = ""):
        """Fechamento com conferência cega: operador informa o contado,
        o sistema aponta a diferença. Sessão fechada não recebe movimento."""
        if not self.aberta:
            raise ValidationError("Esta sessão de caixa já está fechada.")
        self.valor_contado = valor_contado
        self.diferenca = valor_contado - self.esperado_em_dinheiro()
        self.status = self.Status.FECHADA
        self.fechada_em = timezone.now()
        self.save()
        registrar_auditoria(
            usuario, "fechamento_caixa", self,
            {"contado": str(valor_contado), "diferenca": str(self.diferenca)},
        )

    def reabrir(self, usuario, motivo: str):
        """Reabertura é ação sensível: exige gerência (verificada na view) e motivo."""
        if self.aberta:
            raise ValidationError("Esta sessão já está aberta.")
        if not motivo.strip():
            raise ValidationError("Informe o motivo da reabertura.")
        if SessaoCaixa.objects.filter(
            operador=self.operador, modulo=self.modulo, status=self.Status.ABERTA
        ).exists():
            raise ValidationError(
                "O operador já tem outra sessão aberta neste módulo."
            )
        self.status = self.Status.ABERTA
        self.fechada_em = None
        self.valor_contado = None
        self.diferenca = None
        self.save()
        registrar_auditoria(usuario, "reabertura_caixa", self, {"motivo": motivo})


class MovimentoCaixa(models.Model):
    """
    Movimento de caixa — IMUTÁVEL. Nunca é alterado nem apagado; correção é
    um movimento de estorno referenciando o original.
    """

    class Tipo(models.TextChoices):
        RECEBIMENTO = "recebimento", "Recebimento"
        REFORCO = "reforco", "Reforço"
        SANGRIA = "sangria", "Sangria"
        ESTORNO = "estorno", "Estorno"

    sessao = models.ForeignKey(
        SessaoCaixa, on_delete=models.PROTECT,
        related_name="movimentos", verbose_name="sessão",
    )
    tipo = models.CharField("tipo", max_length=12, choices=Tipo.choices)
    forma_pagamento = models.ForeignKey(
        FormaPagamento, on_delete=models.PROTECT, null=True, blank=True,
        related_name="movimentos", verbose_name="forma de pagamento",
        help_text="Obrigatória em recebimentos e estornos; reforço e sangria são dinheiro.",
    )
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    parcelas = models.PositiveSmallIntegerField("parcelas", default=1)
    descricao = models.CharField("descrição", max_length=200)
    motivo = models.TextField(
        "motivo", blank=True, help_text="Obrigatório em estornos."
    )
    movimento_origem = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="estornos", verbose_name="movimento original",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="movimentos_caixa", verbose_name="registrado por",
    )
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "movimento de caixa"
        verbose_name_plural = "movimentos de caixa"
        ordering = ["-criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valor__gt=0), name="movimento_caixa_valor_positivo"
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor} — {self.descricao}"

    @property
    def tipo_ajuda(self) -> str:
        """Explicação do tipo de movimento, para dica ao passar o mouse."""
        return {
            self.Tipo.RECEBIMENTO: "Entrada de dinheiro por um pagamento.",
            self.Tipo.REFORCO: "Reforço — dinheiro colocado no caixa (ex.: troco).",
            self.Tipo.SANGRIA: "Sangria — retirada de dinheiro do caixa (ex.: para o cofre).",
            self.Tipo.ESTORNO: "Estorno — devolução de um recebimento.",
        }.get(self.tipo, "")

    def clean(self):
        if self.sessao_id and not self.sessao.aberta:
            raise ValidationError("A sessão de caixa está fechada.")
        if self.tipo in (self.Tipo.RECEBIMENTO, self.Tipo.ESTORNO):
            if not self.forma_pagamento_id:
                raise ValidationError(
                    {"forma_pagamento": "Informe a forma de pagamento."}
                )
        if self.tipo == self.Tipo.ESTORNO:
            if not self.movimento_origem_id:
                raise ValidationError("Estorno exige o movimento original.")
            if not self.motivo.strip():
                raise ValidationError({"motivo": "Estorno exige motivo."})
            origem = self.movimento_origem
            if origem.tipo != self.Tipo.RECEBIMENTO:
                raise ValidationError("Só recebimentos podem ser estornados.")
            ja_estornado = origem.estornos.aggregate(t=Sum("valor"))["t"] or Decimal(
                "0.00"
            )
            if self.valor + ja_estornado > origem.valor:
                raise ValidationError(
                    {"valor": "O estorno excede o valor restante do recebimento."}
                )
        if (
            self.parcelas > 1
            and self.forma_pagamento_id
            and not self.forma_pagamento.permite_parcelamento
        ):
            raise ValidationError(
                {"parcelas": "Esta forma de pagamento não permite parcelamento."}
            )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Movimento de caixa é imutável — registre um estorno."
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Movimento de caixa não pode ser apagado — registre um estorno."
        )


def receber_no_caixa(usuario, forma, valor: Decimal, descricao: str, parcelas: int = 1):
    """
    Recebimento pela sessão de caixa aberta do operador — a "veia do dinheiro".
    Interface pública para os módulos (Loja, PDV...) cobrarem no caixa.
    """
    sessao = SessaoCaixa.objects.filter(
        operador=usuario, status=SessaoCaixa.Status.ABERTA
    ).first()
    if not sessao:
        raise ValidationError(
            "Você precisa de um caixa aberto para receber — abra em Operação → Caixa."
        )
    movimento = MovimentoCaixa(
        sessao=sessao,
        tipo=MovimentoCaixa.Tipo.RECEBIMENTO,
        forma_pagamento=forma,
        valor=valor,
        parcelas=parcelas,
        descricao=descricao,
        criado_por=usuario,
    )
    movimento.save()
    return movimento


def estornar_movimento(origem: MovimentoCaixa, sessao: SessaoCaixa, usuario, motivo: str,
                       valor: Decimal | None = None) -> MovimentoCaixa:
    """
    Cria o movimento inverso de um recebimento (total ou parcial) e audita.
    A permissão de gerência é verificada na view.
    """
    estorno = MovimentoCaixa(
        sessao=sessao,
        tipo=MovimentoCaixa.Tipo.ESTORNO,
        forma_pagamento=origem.forma_pagamento,
        valor=valor if valor is not None else origem.valor,
        descricao=f"Estorno de: {origem.descricao}",
        motivo=motivo,
        movimento_origem=origem,
        criado_por=usuario,
    )
    estorno.save()
    registrar_auditoria(
        usuario, "estorno", estorno,
        {"movimento_origem": origem.pk, "valor": str(estorno.valor), "motivo": motivo},
    )
    return estorno


class CategoriaFinanceira(models.Model):
    class Tipo(models.TextChoices):
        RECEITA = "receita", "Receita"
        DESPESA = "despesa", "Despesa"

    nome = models.CharField("nome", max_length=80)
    tipo = models.CharField("tipo", max_length=8, choices=Tipo.choices)
    ativo = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "categoria financeira"
        verbose_name_plural = "categorias financeiras"
        ordering = ["tipo", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["nome", "tipo"], name="categoria_unica_por_tipo"
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"


class LancamentoFinanceiro(models.Model):
    """Receita ou despesa classificada por categoria e centro (= módulo)."""

    tipo = models.CharField(
        "tipo", max_length=8, choices=CategoriaFinanceira.Tipo.choices
    )
    categoria = models.ForeignKey(
        CategoriaFinanceira, on_delete=models.PROTECT,
        related_name="lancamentos", verbose_name="categoria",
    )
    centro = models.CharField(
        "centro de receita/custo", max_length=20, default=CENTRO_NUCLEO,
        help_text="Módulo de origem do lançamento.",
    )
    descricao = models.CharField("descrição", max_length=200)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    data = models.DateField("data de competência", default=timezone.localdate)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="lancamentos_financeiros", verbose_name="registrado por",
    )
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "lançamento financeiro"
        verbose_name_plural = "lançamentos financeiros"
        ordering = ["-data", "-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.descricao} (R$ {self.valor})"

    def get_centro_display(self):
        return dict(centro_choices()).get(self.centro, self.centro)

    def clean(self):
        if self.categoria_id and self.tipo and self.categoria.tipo != self.tipo:
            raise ValidationError(
                {"categoria": "A categoria não é do mesmo tipo do lançamento."}
            )


class ContaPagarReceber(models.Model):
    """Título a pagar (fornecedor) ou a receber (cliente), com baixa."""

    class Tipo(models.TextChoices):
        PAGAR = "pagar", "A pagar"
        RECEBER = "receber", "A receber"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        BAIXADA = "baixada", "Baixada"
        CANCELADA = "cancelada", "Cancelada"

    tipo = models.CharField("tipo", max_length=8, choices=Tipo.choices)
    pessoa = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="contas", verbose_name="fornecedor/cliente",
    )
    categoria = models.ForeignKey(
        CategoriaFinanceira, on_delete=models.PROTECT,
        related_name="contas", verbose_name="categoria",
    )
    centro = models.CharField(
        "centro de receita/custo", max_length=20, default=CENTRO_NUCLEO
    )
    descricao = models.CharField("descrição", max_length=200)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    vencimento = models.DateField("vencimento")
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    baixada_em = models.DateField("baixada em", null=True, blank=True)
    baixada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="contas_baixadas", verbose_name="baixada por",
    )
    lancamento = models.OneToOneField(
        LancamentoFinanceiro, on_delete=models.PROTECT, null=True, blank=True,
        related_name="conta", verbose_name="lançamento da baixa",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "conta a pagar/receber"
        verbose_name_plural = "contas a pagar/receber"
        ordering = ["status", "vencimento"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.descricao} (venc. {self.vencimento})"

    @property
    def vencida(self) -> bool:
        return self.status == self.Status.ABERTA and self.vencimento < timezone.localdate()

    def clean(self):
        if self.categoria_id and self.tipo:
            esperado = (
                CategoriaFinanceira.Tipo.DESPESA
                if self.tipo == self.Tipo.PAGAR
                else CategoriaFinanceira.Tipo.RECEITA
            )
            if self.categoria.tipo != esperado:
                raise ValidationError(
                    {"categoria": "Conta a pagar usa categoria de despesa; "
                                  "a receber, de receita."}
                )

    def baixar(self, usuario, data=None):
        """Baixa o título e gera o lançamento financeiro correspondente."""
        if self.status != self.Status.ABERTA:
            raise ValidationError("Só contas abertas podem ser baixadas.")
        data = data or timezone.localdate()
        lancamento = LancamentoFinanceiro(
            tipo=(
                CategoriaFinanceira.Tipo.DESPESA
                if self.tipo == self.Tipo.PAGAR
                else CategoriaFinanceira.Tipo.RECEITA
            ),
            categoria=self.categoria,
            centro=self.centro,
            descricao=f"Baixa: {self.descricao}",
            valor=self.valor,
            data=data,
            criado_por=usuario,
        )
        lancamento.full_clean()
        lancamento.save()
        self.lancamento = lancamento
        self.status = self.Status.BAIXADA
        self.baixada_em = data
        self.baixada_por = usuario
        self.save()
        registrar_auditoria(
            usuario, "baixa_conta", self, {"valor": str(self.valor), "data": str(data)}
        )
        return lancamento


class TrilhaAuditoria(models.Model):
    """Registro de operações sensíveis: quem, quando, o quê e por quê."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="auditorias", verbose_name="usuário",
    )
    acao = models.CharField("ação", max_length=40)
    alvo = models.CharField("alvo", max_length=80)
    alvo_id = models.CharField("id do alvo", max_length=40)
    detalhe = models.JSONField("detalhe", default=dict, blank=True)
    criado_em = models.DateTimeField("em", auto_now_add=True)

    class Meta:
        verbose_name = "trilha de auditoria"
        verbose_name_plural = "trilhas de auditoria"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.acao} — {self.alvo}#{self.alvo_id} por {self.usuario}"


def registrar_auditoria(usuario, acao: str, objeto, detalhe: dict | None = None):
    TrilhaAuditoria.objects.create(
        usuario=usuario,
        acao=acao,
        alvo=objeto.__class__.__name__,
        alvo_id=str(objeto.pk),
        detalhe=detalhe or {},
    )

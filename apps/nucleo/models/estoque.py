"""
Motor de estoque (ESPECIFICACAO §4.4) — engine interna do núcleo e fonte de
verdade única do estoque. Loja, Restaurante, Frigobar e Lavanderia baixam/entram
produtos SEMPRE por estas funções (nunca mexendo direto nos movimentos).

Regras que não se quebram:
- MovimentoEstoque é IMUTÁVEL (correção = movimento inverso/ajuste, nunca update/delete).
- Custo é DecimalField; custo médio ponderado atualizado a cada entrada.
- Saída não pode deixar o saldo do local negativo.
- Todo produto carrega natureza fiscal (SERVIÇO|CONSUMO), obrigatória.
- Transferência entre locais é registrada dos dois lados (movimentos ligados).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum

from .financeiro import NaturezaFiscal, centro_choices, registrar_auditoria

ZERO = Decimal("0")
Q_QTD = Decimal("0.001")


class CategoriaProduto(models.Model):
    nome = models.CharField("nome", max_length=80, unique=True)
    ativo = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "categoria de produto"
        verbose_name_plural = "categorias de produto"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Produto(models.Model):
    class Unidade(models.TextChoices):
        UNIDADE = "un", "Unidade"
        KG = "kg", "Quilo"
        GRAMA = "g", "Grama"
        LITRO = "l", "Litro"
        ML = "ml", "Mililitro"
        CAIXA = "cx", "Caixa"
        PACOTE = "pct", "Pacote"
        DUZIA = "dz", "Dúzia"

    codigo_barras = models.CharField(
        "código de barras", max_length=40, blank=True, db_index=True
    )
    nome = models.CharField("nome", max_length=120)
    categoria = models.ForeignKey(
        CategoriaProduto, on_delete=models.PROTECT,
        related_name="produtos", verbose_name="categoria",
    )
    unidade = models.CharField(
        "unidade", max_length=4, choices=Unidade.choices, default=Unidade.UNIDADE
    )
    natureza = models.CharField(
        "natureza fiscal", max_length=10, choices=NaturezaFiscal.choices,
        default=NaturezaFiscal.CONSUMO,
        help_text="Produto físico é consumo (NF-e/NFC-e). Sem default silencioso.",
    )
    custo_medio = models.DecimalField(
        "custo médio (R$)", max_digits=12, decimal_places=4, default=ZERO,
        help_text="Calculado pelo sistema a cada entrada — não editar à mão.",
    )
    preco_venda = models.DecimalField(
        "preço de venda (R$)", max_digits=10, decimal_places=2, default=ZERO
    )
    estoque_minimo = models.DecimalField(
        "estoque mínimo", max_digits=12, decimal_places=3, default=ZERO,
        help_text="Abaixo disso, o produto entra nos alertas do painel.",
    )
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def saldo(self, local=None) -> Decimal:
        return saldo(self, local)

    @property
    def margem(self) -> Decimal | None:
        if self.custo_medio and self.preco_venda:
            return (self.preco_venda - self.custo_medio) / self.custo_medio * 100
        return None


class LocalEstoque(models.Model):
    """Depósito. Um por módulo que usa estoque + almoxarifado central (núcleo)."""

    nome = models.CharField("nome", max_length=80, unique=True)
    modulo = models.CharField(
        "vínculo (centro)", max_length=20, default="nucleo",
        help_text="Módulo dono deste depósito (almoxarifado central = Núcleo).",
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "local de estoque"
        verbose_name_plural = "locais de estoque"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def get_modulo_display(self):
        return dict(centro_choices()).get(self.modulo, self.modulo)


class MovimentoEstoque(models.Model):
    """
    Movimento do kardex — IMUTÁVEL. `quantidade` é sinalizada: positiva entra,
    negativa sai. O saldo de um produto/local é a soma das quantidades.
    """

    class Tipo(models.TextChoices):
        ENTRADA_COMPRA = "entrada_compra", "Entrada por compra"
        SAIDA_VENDA = "saida_venda", "Saída por venda"
        CONSUMO_INTERNO = "consumo_interno", "Consumo interno"
        PERDA = "perda", "Perda/quebra/vencimento"
        TRANSFERENCIA_SAIDA = "transf_saida", "Transferência (saída)"
        TRANSFERENCIA_ENTRADA = "transf_entrada", "Transferência (entrada)"
        AJUSTE = "ajuste", "Ajuste de inventário"

    produto = models.ForeignKey(
        Produto, on_delete=models.PROTECT,
        related_name="movimentos", verbose_name="produto",
    )
    local = models.ForeignKey(
        LocalEstoque, on_delete=models.PROTECT,
        related_name="movimentos", verbose_name="local",
    )
    tipo = models.CharField("tipo", max_length=16, choices=Tipo.choices)
    quantidade = models.DecimalField(
        "quantidade (sinalizada)", max_digits=12, decimal_places=3
    )
    custo_unitario = models.DecimalField(
        "custo unitário (R$)", max_digits=12, decimal_places=4, default=ZERO
    )
    documento = models.CharField(
        "documento de origem", max_length=80, blank=True,
        help_text="Nota fiscal, comanda, ordem — de onde veio o movimento.",
    )
    observacao = models.CharField("observação", max_length=200, blank=True)
    transferencia_par = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="par", verbose_name="par da transferência",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="movimentos_estoque", verbose_name="registrado por",
    )
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "movimento de estoque"
        verbose_name_plural = "movimentos de estoque"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.quantidade} {self.produto}"

    @property
    def entrada(self) -> bool:
        return self.quantidade > 0

    def clean(self):
        if self.quantidade == ZERO:
            raise ValidationError({"quantidade": "A quantidade não pode ser zero."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Movimento de estoque é imutável — registre um ajuste/inverso."
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Movimento de estoque não pode ser apagado — registre um ajuste."
        )


# ---------- Consultas de saldo ----------


def saldo(produto: Produto, local: LocalEstoque | None = None) -> Decimal:
    """Saldo de um produto (no local, ou total se local=None)."""
    filtros = {"produto": produto}
    if local is not None:
        filtros["local"] = local
    total = MovimentoEstoque.objects.filter(**filtros).aggregate(
        s=Sum("quantidade")
    )["s"]
    return total or ZERO


def posicao_estoque(local: LocalEstoque | None = None):
    """Saldo por produto (opcionalmente de um local) + flag de estoque mínimo."""
    qs = MovimentoEstoque.objects.all()
    if local is not None:
        qs = qs.filter(local=local)
    saldos = {
        linha["produto"]: linha["s"]
        for linha in qs.values("produto").annotate(s=Sum("quantidade"))
    }
    linhas = []
    for produto in Produto.objects.filter(ativo=True).select_related("categoria"):
        atual = saldos.get(produto.pk, ZERO)
        linhas.append(
            {
                "produto": produto,
                "saldo": atual,
                "abaixo_minimo": atual <= produto.estoque_minimo,
                "valor": (atual * produto.custo_medio).quantize(Decimal("0.01")),
            }
        )
    return linhas


def produtos_abaixo_minimo() -> int:
    return sum(1 for linha in posicao_estoque() if linha["abaixo_minimo"])


# ---------- Movimentações (interface pública do motor) ----------


def _novo_movimento(produto, local, tipo, quantidade, usuario, **extra):
    mov = MovimentoEstoque(
        produto=produto, local=local, tipo=tipo,
        quantidade=quantidade, criado_por=usuario, **extra,
    )
    mov.save()
    return mov


@transaction.atomic
def registrar_entrada(
    produto, local, quantidade, custo_unitario, usuario, documento="", observacao=""
):
    """Entrada por compra: soma ao saldo e recalcula o custo médio ponderado."""
    quantidade = Decimal(quantidade)
    custo_unitario = Decimal(custo_unitario)
    if quantidade <= ZERO:
        raise ValidationError("A quantidade de entrada deve ser positiva.")
    saldo_atual = saldo(produto)
    valor_atual = saldo_atual * produto.custo_medio
    novo_saldo = saldo_atual + quantidade
    produto.custo_medio = (
        (valor_atual + quantidade * custo_unitario) / novo_saldo
    ).quantize(Decimal("0.0001"))
    produto.save(update_fields=["custo_medio"])
    return _novo_movimento(
        produto, local, MovimentoEstoque.Tipo.ENTRADA_COMPRA, quantidade, usuario,
        custo_unitario=custo_unitario, documento=documento, observacao=observacao,
    )


@transaction.atomic
def registrar_saida(
    produto, local, quantidade, usuario,
    tipo=MovimentoEstoque.Tipo.SAIDA_VENDA, documento="", observacao="",
):
    """Saída (venda/consumo/perda): valida saldo e baixa pelo custo médio."""
    quantidade = Decimal(quantidade)
    if quantidade <= ZERO:
        raise ValidationError("A quantidade de saída deve ser positiva.")
    if saldo(produto, local) < quantidade:
        raise ValidationError(
            f"Saldo insuficiente de {produto} em {local} "
            f"(disponível: {saldo(produto, local)})."
        )
    return _novo_movimento(
        produto, local, tipo, -quantidade, usuario,
        custo_unitario=produto.custo_medio, documento=documento, observacao=observacao,
    )


@transaction.atomic
def transferir(produto, origem, destino, quantidade, usuario, observacao=""):
    """Transferência entre locais — registrada dos dois lados (movimentos ligados)."""
    quantidade = Decimal(quantidade)
    if origem == destino:
        raise ValidationError("Origem e destino não podem ser o mesmo local.")
    if quantidade <= ZERO:
        raise ValidationError("A quantidade transferida deve ser positiva.")
    if saldo(produto, origem) < quantidade:
        raise ValidationError(
            f"Saldo insuficiente em {origem} (disponível: {saldo(produto, origem)})."
        )
    custo = produto.custo_medio
    saida = _novo_movimento(
        produto, origem, MovimentoEstoque.Tipo.TRANSFERENCIA_SAIDA, -quantidade,
        usuario, custo_unitario=custo,
        observacao=observacao or f"Transferência para {destino}",
    )
    entrada = _novo_movimento(
        produto, destino, MovimentoEstoque.Tipo.TRANSFERENCIA_ENTRADA, quantidade,
        usuario, custo_unitario=custo, transferencia_par=saida,
        observacao=observacao or f"Transferência de {origem}",
    )
    saida.transferencia_par = entrada
    MovimentoEstoque.objects.filter(pk=saida.pk).update(transferencia_par=entrada)
    registrar_auditoria(
        usuario, "transferencia_estoque", saida,
        {"produto": produto.pk, "de": origem.pk, "para": destino.pk,
         "quantidade": str(quantidade)},
    )
    return saida, entrada


@transaction.atomic
def ajustar(produto, local, nova_quantidade, usuario, motivo=""):
    """Ajusta o saldo de um local para `nova_quantidade` (movimento de diferença)."""
    nova_quantidade = Decimal(nova_quantidade)
    if nova_quantidade < ZERO:
        raise ValidationError("O saldo ajustado não pode ser negativo.")
    diferenca = nova_quantidade - saldo(produto, local)
    if diferenca == ZERO:
        return None
    mov = _novo_movimento(
        produto, local, MovimentoEstoque.Tipo.AJUSTE, diferenca, usuario,
        custo_unitario=produto.custo_medio, observacao=motivo,
    )
    registrar_auditoria(
        usuario, "ajuste_estoque", mov,
        {"produto": produto.pk, "local": local.pk,
         "diferenca": str(diferenca), "motivo": motivo},
    )
    return mov


# ---------- Inventário ----------


class Inventario(models.Model):
    class Status(models.TextChoices):
        ABERTO = "aberto", "Em contagem"
        APLICADO = "aplicado", "Aplicado"
        CANCELADO = "cancelado", "Cancelado"

    local = models.ForeignKey(
        LocalEstoque, on_delete=models.PROTECT,
        related_name="inventarios", verbose_name="local",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTO
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="inventarios", verbose_name="responsável",
    )
    criado_em = models.DateTimeField("aberto em", auto_now_add=True)
    aplicado_em = models.DateTimeField("aplicado em", null=True, blank=True)

    class Meta:
        verbose_name = "inventário"
        verbose_name_plural = "inventários"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Inventário {self.local} ({self.get_status_display()})"

    @transaction.atomic
    def aplicar(self, usuario):
        """Gera um ajuste para cada item com diferença e fecha o inventário."""
        if self.status != self.Status.ABERTO:
            raise ValidationError("Este inventário já foi aplicado ou cancelado.")
        for item in self.itens.select_related("produto"):
            ajustar(
                item.produto, self.local, item.quantidade_contada, usuario,
                motivo=f"Inventário #{self.pk}",
            )
        from django.utils import timezone

        self.status = self.Status.APLICADO
        self.aplicado_em = timezone.now()
        self.save()
        registrar_auditoria(usuario, "inventario_aplicado", self, {})


class ItemInventario(models.Model):
    inventario = models.ForeignKey(
        Inventario, on_delete=models.CASCADE,
        related_name="itens", verbose_name="inventário",
    )
    produto = models.ForeignKey(
        Produto, on_delete=models.PROTECT,
        related_name="itens_inventario", verbose_name="produto",
    )
    saldo_sistema = models.DecimalField(
        "saldo do sistema", max_digits=12, decimal_places=3, default=ZERO
    )
    quantidade_contada = models.DecimalField(
        "quantidade contada", max_digits=12, decimal_places=3, default=ZERO
    )

    class Meta:
        verbose_name = "item de inventário"
        verbose_name_plural = "itens de inventário"
        constraints = [
            models.UniqueConstraint(
                fields=["inventario", "produto"], name="item_unico_por_inventario"
            ),
        ]

    def __str__(self):
        return f"{self.produto}: {self.quantidade_contada}"

    @property
    def diferenca(self) -> Decimal:
        return self.quantidade_contada - self.saldo_sistema

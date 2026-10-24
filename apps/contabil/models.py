"""
Camada Contábil / Gerencial — Etapa 1: a espinha de classificação.

Ver docs/FINANCEIRO/Mockup_Estrutural_Contabil.md e
docs/FINANCEIRO/Plano_Saneamento_Financeiro.md.

Princípios (herdados do mockup, validados com o usuário):
- Camada ADITIVA e de LEITURA: não reescreve o financeiro operacional
  (MovimentoCaixa, LancamentoFinanceiro, ContaPagarReceber permanecem).
- SEM partidas dobradas: a DRE sai por soma dos lançamentos por competência,
  agrupados pela conta mapeada.
- Plano de contas enxuto de pousada, mas guardando o `codigo_contador` para o
  export casar 1:1 com o balancete do contador.
- Patrimonial (grupos 1 Ativo e 2 Passivo) fora de escopo por ora.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.nucleo.models.financeiro import CategoriaFinanceira, NaturezaFiscal, centro_choices


class ContaContabil(models.Model):
    """Uma conta do plano de contas hierárquico (enxuto de pousada)."""

    class Grupo(models.TextChoices):
        RECEITA = "receita", "Receita"
        CUSTO = "custo", "Custo"
        DESPESA = "despesa", "Despesa"

    class Natureza(models.TextChoices):
        CREDORA = "credora", "Credora"
        DEVEDORA = "devedora", "Devedora"

    class Tipo(models.TextChoices):
        SINTETICA = "sintetica", "Sintética (agrupadora)"
        ANALITICA = "analitica", "Analítica (recebe lançamento)"

    classificacao = models.CharField(
        "classificação", max_length=20, unique=True,
        help_text="Código hierárquico, ex.: 3.1.01.03",
    )
    codigo_contador = models.IntegerField(
        "código do contador", null=True, blank=True,
        help_text="Código numérico da conta no sistema do contador (para o export).",
    )
    nome = models.CharField("nome", max_length=120)
    grupo = models.CharField("grupo", max_length=8, choices=Grupo.choices)
    natureza = models.CharField(
        "natureza", max_length=8, choices=Natureza.choices,
        default=Natureza.CREDORA,
    )
    tipo = models.CharField(
        "tipo", max_length=10, choices=Tipo.choices, default=Tipo.ANALITICA,
    )
    conta_pai = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="filhas", verbose_name="conta superior",
    )
    ordem = models.PositiveIntegerField("ordem", default=0)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "conta contábil"
        verbose_name_plural = "plano de contas"
        ordering = ["classificacao"]

    def __str__(self):
        return f"{self.classificacao} {self.nome}"

    @property
    def analitica(self) -> bool:
        return self.tipo == self.Tipo.ANALITICA

    def clean(self):
        if self.conta_pai_id and self.conta_pai.tipo != self.Tipo.SINTETICA:
            raise ValidationError(
                {"conta_pai": "A conta superior precisa ser sintética (agrupadora)."}
            )


class MapeamentoContabil(models.Model):
    """
    De-Para: regra que resolve a conta contábil de um lançamento/movimento.

    Resolução por PRIORIDADE (maior vence) e, no empate, por especificidade
    (mais campos de origem preenchidos vence). Uma regra "casa" quando TODOS os
    seus campos de origem preenchidos batem com a entrada; campos vazios são
    curinga. Nunca fica órfão: há fallback por tipo (receita/despesa).
    """

    FALLBACK_RECEITA = "fallback_receita"
    FALLBACK_DESPESA = "fallback_despesa"

    conta = models.ForeignKey(
        ContaContabil, on_delete=models.PROTECT, related_name="mapeamentos",
        verbose_name="conta contábil",
    )
    # --- Origens (todas opcionais; a regra casa pelos campos preenchidos) ---
    categoria = models.ForeignKey(
        CategoriaFinanceira, on_delete=models.CASCADE, null=True, blank=True,
        related_name="mapeamentos_contabeis", verbose_name="categoria financeira",
    )
    centro = models.CharField("centro / setor", max_length=20, blank=True)
    natureza_folio = models.CharField(
        "natureza do folio", max_length=8, choices=NaturezaFiscal.choices, blank=True,
    )
    origem_sistema = models.CharField(
        "origem de sistema", max_length=30, blank=True,
        help_text="Ex.: cmv, pagamento_taxa, comissao_ota, simples, "
                  "fallback_receita, fallback_despesa.",
    )
    prioridade = models.IntegerField("prioridade", default=0)
    ativo = models.BooleanField("ativo", default=True)
    observacao = models.CharField("observação", max_length=200, blank=True)

    class Meta:
        verbose_name = "mapeamento contábil (de-para)"
        verbose_name_plural = "mapeamentos contábeis (de-para)"
        ordering = ["-prioridade", "id"]

    def __str__(self):
        return f"{self.origem_descricao()} → {self.conta.classificacao}"

    @property
    def especificidade(self) -> int:
        """Quantos campos de origem estão preenchidos (desempate)."""
        return sum(
            1 for v in (self.categoria_id, self.centro, self.natureza_folio,
                        self.origem_sistema) if v
        )

    def origem_descricao(self) -> str:
        partes = []
        if self.categoria_id:
            partes.append(f"categoria={self.categoria}")
        if self.centro:
            partes.append(f"centro={self.centro}")
        if self.natureza_folio:
            partes.append(f"natureza={self.natureza_folio}")
        if self.origem_sistema:
            partes.append(self.origem_sistema)
        return " · ".join(partes) or "(curinga)"

    def clean(self):
        if not self.especificidade:
            raise ValidationError(
                "Preencha ao menos um campo de origem (categoria, centro, "
                "natureza do folio ou origem de sistema)."
            )
        if self.centro:
            validos = {c for c, _ in centro_choices()}
            if self.centro not in validos:
                raise ValidationError({"centro": "Centro/setor inválido."})


class FechamentoMensal(models.Model):
    """
    Fechamento mensal guiado (Etapa 4): os números de baixa frequência que NÃO
    nascem no sistema (folha, encargos, pró-labore, DAS/Simples). Digitados uma
    vez por mês; `aplicar()` gera/atualiza os `LancamentoFinanceiro` de competência
    já classificados. Recomputável e idempotente (chave `referencia`).
    """

    # (atributo, chave de referência, nome da categoria, classificação contábil, descrição)
    COMPONENTES = [
        ("folha", "folha", "Folha de pagamento", "4.2.01.01", "Folha de pagamento"),
        ("encargos", "encargos", "Encargos sociais (FGTS/INSS)", "4.2.01.01", "Encargos (FGTS/INSS)"),
        ("pro_labore", "pro_labore", "Pró-labore", "5.1.02.02", "Pró-labore dos sócios"),
        ("das", "das", "Simples Nacional (DAS)", "3.1.02.01", "DAS — Simples Nacional"),
    ]

    ano = models.PositiveIntegerField("ano")
    mes = models.PositiveSmallIntegerField("mês")
    folha = models.DecimalField("folha de pagamento (R$)", max_digits=12, decimal_places=2,
                                default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    encargos = models.DecimalField("encargos FGTS/INSS (R$)", max_digits=12, decimal_places=2,
                                   default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    pro_labore = models.DecimalField("pró-labore (R$)", max_digits=12, decimal_places=2,
                                     default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    das = models.DecimalField("DAS / Simples Nacional (R$)", max_digits=12, decimal_places=2,
                              default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    observacao = models.CharField("observação", max_length=200, blank=True)
    fechado_em = models.DateTimeField("fechado em", auto_now=True)
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fechamentos_mensais", verbose_name="fechado por",
    )

    class Meta:
        verbose_name = "fechamento mensal"
        verbose_name_plural = "fechamentos mensais"
        ordering = ["-ano", "-mes"]
        constraints = [
            models.UniqueConstraint(fields=["ano", "mes"], name="fechamento_unico_por_mes"),
        ]

    def __str__(self):
        return f"Fechamento {self.ano:04d}/{self.mes:02d}"

    def _ultimo_dia(self) -> date:
        return date(self.ano, self.mes, calendar.monthrange(self.ano, self.mes)[1])

    def aplicar(self):
        """Gera/atualiza os lançamentos do mês. Valor 0 apaga o lançamento (correção)."""
        from apps.nucleo.models.financeiro import CENTRO_NUCLEO, LancamentoFinanceiro
        from apps.nucleo.sistema import usuario_de_sistema

        autor = self.fechado_por or usuario_de_sistema("_contabil", "Contábil (automático)")
        data = self._ultimo_dia()
        for attr, chave, nome_cat, classif, descricao in self.COMPONENTES:
            valor = getattr(self, attr) or Decimal("0")
            ref = f"fechamento:{self.ano:04d}-{self.mes:02d}:{chave}"
            if valor > 0:
                cat, criada = CategoriaFinanceira.objects.get_or_create(
                    nome=nome_cat, tipo=CategoriaFinanceira.Tipo.DESPESA,
                    defaults={"automatica": True},
                )
                if not criada and not cat.automatica:
                    cat.automatica = True
                    cat.save(update_fields=["automatica"])
                LancamentoFinanceiro.objects.update_or_create(
                    referencia=ref,
                    defaults=dict(
                        tipo=CategoriaFinanceira.Tipo.DESPESA, categoria=cat,
                        centro=CENTRO_NUCLEO,
                        descricao=f"{descricao} — {self.ano:04d}/{self.mes:02d}",
                        valor=valor, data=data, criado_por=autor,
                        origem="fechamento", conta_contabil=classif,
                    ),
                )
            else:
                LancamentoFinanceiro.objects.filter(referencia=ref).delete()

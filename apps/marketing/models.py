"""Models do módulo Marketing — a camada de FLUXO das campanhas.

Decisão do dono (ROTEIRO-MARKETING.md §3.1): o marketing **embrulha** a
`comercial.Campanha` (que os leads já usam como origem) por um `OneToOne` (`anuncio`).
Assim há **uma fonte só** de origem (leads em `Oportunidade.campanha`) e de gasto
(`comercial.GastoCampanha`) — o marketing acrescenta as 7 fases, a verba mensal, o
checklist/portões, as peças datadas e a retrospectiva, sem duplicar o que o comercial faz.

Nada aqui reescreve reservas nem o funil — os passos 7–9 (elo com o CRM) reusam os
services do comercial. Dinheiro é `DecimalField` (nunca float).
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class VerbaMarketing(models.Model):
    """Teto de verba POR MÊS (singleton com histórico).

    `tetos` = {"2026-09": 18000.00, …}. Guardar por mês (e não um número único) é o que
    impede que um relatório de mês fechado mude porque alguém ajustou o teto de hoje.
    `travada` e `gasta` NÃO são campos — são soma das campanhas (fonte única).
    """

    tetos = models.JSONField("tetos por mês", default=dict, blank=True)
    alerta_pct = models.PositiveSmallIntegerField("alerta em (% do teto)", default=80)

    class Meta:
        verbose_name = "verba de marketing"
        verbose_name_plural = "verba de marketing"

    def __str__(self):
        return "Verba de marketing (teto por mês)"

    @classmethod
    def atual(cls) -> "VerbaMarketing":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def teto_do_mes(self, aaaa_mm: str) -> Decimal:
        return Decimal(str((self.tetos or {}).get(aaaa_mm, 0)))


class Campanha(models.Model):
    """A campanha como FLUXO: da ideia à retrospectiva, com verba e calendário.

    `anuncio` liga à `comercial.Campanha` (origem dos leads) — criado/garantido quando a
    campanha entra em Aprovação, para os leads poderem se prender (passo 7).
    """

    class Fase(models.TextChoices):
        IDEIA = "ideia", "Ideia"
        PROPOSTA = "proposta", "Proposta"
        APROVACAO = "aprovacao", "Aprovação"
        ESTRUTURACAO = "estruturacao", "Estruturação"
        PRODUCAO = "producao", "Produção"
        NOAR = "noar", "No ar"
        ENCERRADA = "encerrada", "Encerrada"

    nome = models.CharField("nome", max_length=140)
    objetivo = models.TextField("objetivo", blank=True)
    publico = models.CharField("público-alvo", max_length=140, blank=True)
    canais = models.JSONField("canais", default=list, blank=True)  # Instagram, Meta Ads…
    inicio = models.DateField("início", null=True, blank=True)
    fim = models.DateField("fim", null=True, blank=True)
    fase = models.CharField("fase", max_length=14, choices=Fase.choices, default=Fase.IDEIA)

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="campanhas_mkt_pedidas", verbose_name="solicitante",
        null=True, blank=True,
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="campanhas_mkt_sob", verbose_name="responsável",
        null=True, blank=True,
    )
    criativo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campanhas_mkt_criativo", verbose_name="criação",
    )
    fornecedor = models.CharField("fornecedor externo", max_length=140, blank=True)

    verba_prevista = models.DecimalField(
        "verba prevista (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    verba_travada = models.DecimalField(
        "verba travada (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Travada no teto do mês ao aprovar; devolvida (não gasta) ao encerrar.")

    aprovada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campanhas_mkt_aprovadas", verbose_name="aprovada por")
    aprovada_em = models.DateTimeField("aprovada em", null=True, blank=True)

    retro_funcionou = models.TextField("retrospectiva — o que funcionou", blank=True)
    retro_nao = models.TextField("retrospectiva — o que não funcionou", blank=True)
    retro_diferente = models.TextField("retrospectiva — o que fazer diferente", blank=True)

    # Elo de origem (uma fonte só de leads/gasto). Garantido na Aprovação.
    anuncio = models.OneToOneField(
        "comercial.Campanha", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fluxo", verbose_name="campanha de anúncio (origem)")

    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "campanha de marketing"
        verbose_name_plural = "campanhas de marketing"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.nome

    @property
    def codigo(self) -> str:
        return f"CP-{self.pk:02d}" if self.pk else "CP—"

    @property
    def iniciais(self) -> str:
        r = self.responsavel
        if not r:
            return "—"
        nome = (r.get_full_name() or r.username or "").strip()
        partes = nome.split()
        if not partes:
            return "—"
        ini = partes[0][:1] + (partes[-1][:1] if len(partes) > 1 else "")
        return ini.upper()

    @property
    def gasta(self) -> Decimal:
        """Gasto real = Σ dos gastos da campanha de anúncio (fonte única, comercial)."""
        if not self.anuncio_id:
            return Decimal("0.00")
        from apps.comercial.models import GastoDiario
        total = (GastoDiario.objects.filter(campanha_id=self.anuncio_id)
                 .aggregate(s=Sum("valor"))["s"])
        return total or Decimal("0.00")

    @property
    def sobra_travada(self) -> Decimal:
        """Verba comprometida ainda não gasta (o que 'Encerrar' devolve ao mês)."""
        resto = self.verba_travada - self.gasta
        return resto if resto > 0 else Decimal("0.00")


class PecaCampanha(models.Model):
    """Peça com DATA: é o que o calendário desenha e o que a equipe consulta hoje."""

    class Status(models.TextChoices):
        A_FAZER = "a_fazer", "A fazer"
        EM_PRODUCAO = "em_producao", "Em produção"
        PRONTA = "pronta", "Pronta"

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="pecas", verbose_name="campanha")
    nome = models.CharField("nome", max_length=140)
    canal = models.CharField("canal", max_length=40, blank=True)
    data = models.DateField("data", null=True, blank=True)
    status = models.CharField(
        "status", max_length=14, choices=Status.choices, default=Status.A_FAZER)

    class Meta:
        verbose_name = "peça de campanha"
        verbose_name_plural = "peças de campanha"
        ordering = ["data", "id"]

    def __str__(self):
        return f"{self.nome} ({self.get_status_display()})"


class EtapaCampanha(models.Model):
    """Tarefa da campanha com dono e prazo (as etapas de execução, não as 7 fases)."""

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="etapas", verbose_name="campanha")
    texto = models.CharField("tarefa", max_length=200)
    dono = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="etapas_mkt", verbose_name="dono")
    prazo = models.DateField("prazo", null=True, blank=True)
    feito = models.BooleanField("feito", default=False)

    class Meta:
        verbose_name = "etapa de campanha"
        verbose_name_plural = "etapas de campanha"
        ordering = ["feito", "prazo", "id"]

    def __str__(self):
        return self.texto


class ItemChecklist(models.Model):
    """Critério de fase (portão de Aprovação). Dispensável pelo Gestor, com motivo."""

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="checks", verbose_name="campanha")
    chave = models.CharField("critério", max_length=40)  # identifica o item da fase
    feito = models.BooleanField("cumprido", default=False)
    por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="checks_mkt", verbose_name="marcado por")
    em = models.DateTimeField("marcado em", null=True, blank=True)
    dispensado = models.BooleanField("dispensado", default=False)
    motivo_dispensa = models.CharField("motivo da dispensa", max_length=200, blank=True)
    arquivo = models.FileField(
        "evidência (anexo)", upload_to="marketing/checklist/", null=True, blank=True,
        help_text="Alguns itens só fecham com um arquivo anexado (referência, briefing, arte).")

    class Meta:
        verbose_name = "item de checklist"
        verbose_name_plural = "itens de checklist"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["campanha", "chave"], name="check_unico_por_campanha"),
        ]

    def __str__(self):
        return f"{self.chave} — {'ok' if self.feito or self.dispensado else 'pendente'}"

    @property
    def ok(self) -> bool:
        return self.feito or self.dispensado


class Comentario(models.Model):
    """Conversa da campanha (trilha leve de decisões)."""

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="conversa", verbose_name="campanha")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="comentarios_mkt", verbose_name="autor")
    texto = models.TextField("texto")
    em = models.DateTimeField("em", default=timezone.now)

    class Meta:
        verbose_name = "comentário"
        verbose_name_plural = "comentários"
        ordering = ["em"]

    def __str__(self):
        return f"{self.autor}: {self.texto[:40]}"

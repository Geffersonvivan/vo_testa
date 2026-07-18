"""
Módulo Comercial — funil de vendas (ESPECIFICACAO: extensão comercial).

Um LEAD é uma `nucleo.Pessoa` (PF, agência ou empresa) — sem cadastro duplicado.
A `Oportunidade` é o card do funil: caminha por `EtapaFunil` até ser **ganha**
(via conversão em Reserva) ou **perdida** (com motivo). Cotação, score e metas
apoiam a gestão do funil (Plano Comercial P0–P3).
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


class EtapaFunil(models.Model):
    """Coluna do funil. Configurável no admin (nome, ordem, probabilidade)."""

    class Tipo(models.TextChoices):
        ABERTA = "aberta", "Em aberto"
        GANHO = "ganho", "Ganho"
        PERDIDO = "perdido", "Perdido"

    nome = models.CharField("nome", max_length=60, unique=True)
    ordem = models.PositiveSmallIntegerField("ordem", default=0)
    probabilidade = models.PositiveSmallIntegerField(
        "probabilidade (%)", default=0,
        help_text="Chance de fechar nesta etapa — usada na previsão ponderada.",
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices,
                            default=Tipo.ABERTA)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "etapa do funil"
        verbose_name_plural = "etapas do funil"

    def __str__(self):
        return self.nome


class MotivoPerda(models.Model):
    """Por que uma oportunidade foi perdida — para aprender o que derruba vendas."""

    nome = models.CharField("motivo", max_length=60, unique=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "motivo de perda"
        verbose_name_plural = "motivos de perda"

    def __str__(self):
        return self.nome


class Oportunidade(models.Model):
    """O card do funil — um lead caminhando até virar reserva."""

    class Faturamento(models.TextChoices):
        PARTICULAR = "particular", "Particular (B2C)"
        AGENCIA = "agencia", "Agência (B2B)"
        EMPRESA = "empresa", "Empresa (B2B)"

    class Origem(models.TextChoices):
        SITE = "site", "Site"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEFONE = "telefone", "Telefone"
        INDICACAO = "indicacao", "Indicação"
        AGENCIA = "agencia", "Agência/OTA"
        PRESENCIAL = "presencial", "Presencial"
        OUTRO = "outro", "Outro"

    class TipoInteresse(models.TextChoices):
        HOSPEDAGEM = "hospedagem", "Hospedagem"
        EVENTO = "evento", "Evento / confraternização"
        DAY_USE = "day_use", "Dia na Pousada"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        GANHA = "ganha", "Ganha"
        PERDIDA = "perdida", "Perdida"

    pessoa = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT,
        related_name="oportunidades", verbose_name="lead (pessoa/agência/empresa)",
    )
    titulo = models.CharField("título", max_length=120)
    etapa = models.ForeignKey(
        EtapaFunil, on_delete=models.PROTECT,
        related_name="oportunidades", verbose_name="etapa",
    )
    faturamento = models.CharField(
        "faturamento", max_length=12, choices=Faturamento.choices,
        default=Faturamento.PARTICULAR,
    )
    origem = models.CharField("origem", max_length=12, choices=Origem.choices,
                              default=Origem.OUTRO)
    tipo_interesse = models.CharField(
        "tipo de interesse", max_length=12, choices=TipoInteresse.choices,
        default=TipoInteresse.HOSPEDAGEM,
    )
    valor_estimado = models.DecimalField(
        "valor estimado (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )
    checkin_previsto = models.DateField("check-in previsto", null=True, blank=True)
    checkout_previsto = models.DateField("check-out previsto", null=True, blank=True)
    quartos = models.PositiveSmallIntegerField("quartos", default=1)
    hospedes = models.PositiveSmallIntegerField("hóspedes", default=2)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="oportunidades", verbose_name="responsável",
    )
    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.ABERTA)
    motivo_perda = models.ForeignKey(
        MotivoPerda, on_delete=models.PROTECT, null=True, blank=True,
        related_name="oportunidades", verbose_name="motivo da perda",
    )
    observacao = models.TextField("observação", blank=True)
    # Vínculos soltos (sem FK cruzada entre módulos).
    reserva_id = models.PositiveIntegerField("reserva vinculada", null=True, blank=True)
    cobranca_sinal_id = models.PositiveIntegerField(
        "cobrança de sinal", null=True, blank=True,
    )
    score = models.PositiveSmallIntegerField(
        "score", default=0,
        help_text="0–100: valor + datas + origem + engajamento.",
    )
    nps_convidado_em = models.DateTimeField("NPS convidado em", null=True, blank=True)

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="oportunidades_criadas", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)
    fechado_em = models.DateTimeField("fechada em", null=True, blank=True)

    class Meta:
        ordering = ["-atualizado_em"]
        verbose_name = "oportunidade"
        verbose_name_plural = "oportunidades"

    def __str__(self):
        return f"{self.titulo} — {self.pessoa.nome}"

    @property
    def valor_ponderado(self) -> Decimal:
        return (self.valor_estimado * Decimal(self.etapa.probabilidade) / Decimal(100)
                ).quantize(Decimal("0.01"))

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    @property
    def proxima_tarefa(self):
        return self.atividades.filter(concluida=False).order_by("quando").first()

    @property
    def ultima_cotacao(self):
        return self.cotacoes.order_by("-criado_em").first()


class Cotacao(models.Model):
    """Orçamento enviado ao lead — torna a etapa 'Cotação' concreta."""

    oportunidade = models.ForeignKey(
        Oportunidade, on_delete=models.CASCADE,
        related_name="cotacoes", verbose_name="oportunidade",
    )
    tipo_uh = models.ForeignKey(
        "nucleo.TipoUH", on_delete=models.PROTECT,
        related_name="cotacoes_comerciais", verbose_name="tipo de quarto",
    )
    checkin = models.DateField("check-in")
    checkout = models.DateField("check-out")
    valor_diaria = models.DecimalField("diária (R$)", max_digits=10, decimal_places=2)
    valor_total = models.DecimalField("total estimado (R$)", max_digits=10, decimal_places=2)
    validade = models.DateField("válida até")
    observacao = models.TextField("observação", blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="cotacoes_criadas", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "cotação"
        verbose_name_plural = "cotações"

    def __str__(self):
        return f"Cotação #{self.pk} — {self.oportunidade_id}"

    @property
    def noites(self) -> int:
        return max(0, (self.checkout - self.checkin).days)


class PermanenciaEtapa(models.Model):
    """Trilha de tempo em cada etapa (para média no painel)."""

    oportunidade = models.ForeignKey(
        Oportunidade, on_delete=models.CASCADE,
        related_name="permanencias", verbose_name="oportunidade",
    )
    etapa = models.ForeignKey(
        EtapaFunil, on_delete=models.PROTECT,
        related_name="permanencias", verbose_name="etapa",
    )
    iniciado_em = models.DateTimeField("entrou em")
    finalizado_em = models.DateTimeField("saiu em", null=True, blank=True)

    class Meta:
        ordering = ["-iniciado_em"]
        verbose_name = "permanência em etapa"
        verbose_name_plural = "permanências em etapa"


class MetaComercial(models.Model):
    """Meta mensal de receita ganha (fechamentos)."""

    mes = models.DateField("mês", unique=True, help_text="Use o 1º dia do mês.")
    valor_meta = models.DecimalField(
        "meta de receita (R$)", max_digits=12, decimal_places=2, default=Decimal("0.00"),
    )
    oportunidades_meta = models.PositiveIntegerField(
        "meta de ganhos (qtd)", default=0,
    )

    class Meta:
        ordering = ["-mes"]
        verbose_name = "meta comercial"
        verbose_name_plural = "metas comerciais"

    def __str__(self):
        return f"Meta {self.mes:%m/%Y}"


class AtividadeComercial(models.Model):
    """Linha do tempo da oportunidade: interações registradas e tarefas agendadas."""

    class Tipo(models.TextChoices):
        LIGACAO = "ligacao", "Ligação"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"
        REUNIAO = "reuniao", "Reunião"
        NOTA = "nota", "Nota"
        TAREFA = "tarefa", "Tarefa"
        COTACAO = "cotacao", "Cotação"
        SISTEMA = "sistema", "Sistema"

    oportunidade = models.ForeignKey(
        Oportunidade, on_delete=models.CASCADE,
        related_name="atividades", verbose_name="oportunidade",
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices,
                            default=Tipo.NOTA)
    descricao = models.CharField("descrição", max_length=255)
    quando = models.DateTimeField("quando")
    concluida = models.BooleanField(
        "concluída", default=True,
        help_text="Desmarcada = tarefa/follow-up agendado ainda por fazer.",
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="atividades_comerciais", verbose_name="responsável",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="atividades_criadas", verbose_name="registrado por",
    )
    criado_em = models.DateTimeField("registrada em", auto_now_add=True)

    class Meta:
        ordering = ["-quando"]
        verbose_name = "atividade comercial"
        verbose_name_plural = "atividades comerciais"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.descricao[:40]}"

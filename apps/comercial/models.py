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
    pagina_captacao = models.ForeignKey(
        "PaginaCaptacao", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="oportunidades", verbose_name="página de captação",
        help_text="Campanha/Landing Page que gerou este lead (se veio de uma).",
    )
    campanha = models.ForeignKey(
        "Campanha", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="oportunidades", verbose_name="campanha de anúncio",
        help_text="Campanha paga que trouxe o lead (casada pelo utm_campaign).",
    )
    origem_rastreio = models.JSONField(
        "rastreio de origem", default=dict, blank=True,
        help_text="UTM + identificadores de clique (fbclid/gclid) para atribuição.",
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
    def titulo_curto(self) -> str:
        """Título sem o nome do lead ao final (o nome já é exibido à parte).

        Ex.: "Proposta 31/10→02/11 — Kelly Mazzocco" → "Proposta 31/10→02/11".
        """
        nome = (self.pessoa.nome or "").strip() if self.pessoa_id else ""
        titulo = (self.titulo or "").strip()
        if not nome:
            return titulo
        # Corta o nome completo ou só o primeiro nome ao final ("… — Marina").
        candidatos = [nome]
        primeiro = nome.split()[0]
        if primeiro != nome:
            candidatos.append(primeiro)
        for alvo in candidatos:
            sufixo = f"— {alvo}"
            if titulo.endswith(sufixo):
                return titulo[: -len(sufixo)].strip()
        return titulo

    @property
    def proxima_tarefa(self):
        return self.atividades.filter(concluida=False).order_by("quando").first()

    @property
    def ultima_cotacao(self):
        return self.cotacoes.order_by("-criado_em").first()

    @property
    def temperatura(self):
        """quente/morno/frio da análise (ou None se ainda não analisado)."""
        try:
            return self.analise.temperatura
        except Exception:
            return None

    @property
    def temperatura_display(self):
        try:
            return self.analise.get_temperatura_display()
        except Exception:
            return ""

    @property
    def dias_parado(self) -> int:
        from django.utils import timezone
        return (timezone.now() - self.atualizado_em).days

    @property
    def eh_novo(self) -> bool:
        """Captado nas últimas 24h — para o time atacar os quentes primeiro."""
        from datetime import timedelta

        from django.utils import timezone
        return self.criado_em >= timezone.now() - timedelta(hours=24)

    @property
    def whatsapp_url(self) -> str:
        """Link wa.me a partir do telefone do lead (assume Brasil)."""
        import re
        tel = re.sub(r"\D", "", (self.pessoa.telefone or ""))
        if len(tel) < 10:
            return ""
        if not tel.startswith("55"):
            tel = "55" + tel
        return f"https://wa.me/{tel}"


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


class AnaliseLead(models.Model):
    """Análise do Caçador sobre um lead (Fase 1 da Máquina de Vendas).

    Não duplica o `score` numérico da Oportunidade — guarda a leitura
    qualitativa: temperatura, os motivos, os sinais extraídos, o rascunho do
    próximo passo e o feedback do atendente (que semeia o loop de aprendizado).
    Por enquanto é preenchida por REGRAS (`services.analisar_lead`); a camada de
    IA entra depois, alimentando os mesmos campos.
    """

    class Temperatura(models.TextChoices):
        QUENTE = "quente", "Quente"
        MORNO = "morno", "Morno"
        FRIO = "frio", "Frio"

    oportunidade = models.OneToOneField(
        Oportunidade, on_delete=models.CASCADE,
        related_name="analise", verbose_name="oportunidade",
    )
    temperatura = models.CharField(
        "temperatura", max_length=6, choices=Temperatura.choices,
        default=Temperatura.FRIO,
    )
    motivos = models.JSONField("motivos do score", default=list, blank=True)
    sinais = models.JSONField("sinais extraídos", default=dict, blank=True)
    rascunho = models.TextField("rascunho do próximo passo", blank=True)
    # Feedback do atendente — base do loop de aprendizado.
    util = models.BooleanField("útil?", null=True, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="analises_revisadas", verbose_name="revisado por",
    )
    revisado_em = models.DateTimeField("revisado em", null=True, blank=True)
    gerado_em = models.DateTimeField("analisado em", auto_now=True)

    class Meta:
        verbose_name = "análise de lead"
        verbose_name_plural = "análises de leads"

    def __str__(self):
        return f"Análise {self.get_temperatura_display()} — {self.oportunidade.pessoa.nome}"


class PaginaCaptacao(models.Model):
    """Página de Captação (Landing Page) de campanha, gerenciável no Comercial.

    Vira DADO editável: você cria, publica e obtém uma URL pública
    (`/captacao/<slug>/`) para colar na bio do Instagram. Os cadastros da página
    caem no funil (`Oportunidade`) já etiquetados com esta campanha
    (`Oportunidade.pagina_captacao`). Conversão = leads ÷ visitas.
    """

    class Status(models.TextChoices):
        RASCUNHO = "rascunho", "Rascunho"
        PUBLICADA = "publicada", "Publicada"
        ENCERRADA = "encerrada", "Encerrada"

    class Tema(models.TextChoices):
        FUNDADOR = "fundador", "Fundador (inauguração)"

    nome = models.CharField("nome (interno)", max_length=80)
    slug = models.SlugField(
        "endereço (slug)", max_length=60, unique=True,
        help_text="Vira a URL pública: /captacao/<slug>/",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.RASCUNHO,
    )
    tema = models.CharField(
        "modelo visual", max_length=12, choices=Tema.choices, default=Tema.FUNDADOR,
    )
    tipo_interesse = models.CharField(
        "cai no funil como", max_length=12,
        choices=Oportunidade.TipoInteresse.choices,
        default=Oportunidade.TipoInteresse.HOSPEDAGEM,
        help_text="Tipo de interesse aplicado ao lead capturado nesta página.",
    )

    # Conteúdo editável (mostrado na página pública).
    selo_texto = models.CharField(
        "selo (topo)", max_length=80, blank=True,
        default="Inauguração · 31 de Outubro",
    )
    tagline = models.CharField(
        "mote (aparece em minúsculas)", max_length=120, blank=True,
        default="a invenção que virou história.",
    )
    hero_titulo = models.CharField(
        "título principal", max_length=160,
        default="O Vô Testa recebia todo mundo. Agora o neto abre as portas para você.",
    )
    hero_subtitulo = models.TextField(
        "subtítulo", blank=True,
        default="Uma pousada fora do tempo, em Itá, Santa Catarina, erguida para honrar "
                "o inventor que transformou engenhosidade em acolhimento. Seja um dos fundadores.",
    )
    historia_titulo = models.CharField(
        "título da história", max_length=120, blank=True,
        default="O Inventor que Moveu as Águas",
    )
    historia_texto = models.TextField(
        "texto da história", blank=True,
        help_text="Parágrafos separados por linha em branco.",
    )
    oferta_titulo = models.CharField(
        "título da oferta", max_length=80, blank=True, default="Tarifa de Fundador",
    )
    oferta_texto = models.TextField(
        "texto da oferta", blank=True,
        default="Ser fundador é dormir aqui antes de todo mundo — e pagar menos por isso. "
                "A tarifa sobe a cada faixa esgotada.",
    )
    cta_texto = models.CharField(
        "texto do botão", max_length=60, default="Quero minha tarifa de fundador",
    )
    vagas_restantes = models.PositiveSmallIntegerField(
        "vagas restantes (opcional)", null=True, blank=True,
        help_text="Mostra 'restam X vagas' na página. Deixe em branco para ocultar.",
    )
    data_evento = models.DateTimeField(
        "data do evento (contador)", null=True, blank=True,
        help_text="Se preenchida, mostra o contador regressivo até esta data.",
    )

    # Contato / conversão.
    whatsapp_destino = models.CharField(
        "WhatsApp para conversão", max_length=20, blank=True,
        help_text="Só números com país+DDD (ex.: 5549999990000). Após o cadastro, o "
                  "lead é levado ao WhatsApp com uma mensagem pronta.",
    )
    meta_pixel_id = models.CharField(
        "Meta Pixel (ID)", max_length=32, blank=True,
        help_text="ID do Pixel do Meta (Instagram/Facebook) para rastrear e refazer "
                  "anúncios (retargeting). Dispara o evento 'Lead' ao cadastrar.",
    )
    google_tag_id = models.CharField(
        "Google (ID da tag)", max_length=32, blank=True,
        help_text="ID do Google (ex.: G-XXXX ou AW-XXXX) para medir a conversão.",
    )

    # Blocos opcionais da página.
    faq_texto = models.TextField(
        "perguntas frequentes", blank=True,
        help_text="Uma pergunta por bloco. Formato: linha 'P: pergunta' e linha "
                  "'R: resposta'. Blocos separados por linha em branco.",
    )
    endereco = models.CharField("endereço (texto)", max_length=200, blank=True)
    mapa_embed = models.URLField(
        "mapa (URL de incorporação)", blank=True,
        help_text="URL de 'incorporar' do Google Maps (o src do iframe).",
    )

    # Metas e medição.
    meta_leads = models.PositiveIntegerField("meta de leads", default=0)
    visitas = models.PositiveIntegerField("visitas", default=0)

    publicada_em = models.DateTimeField("publicada em", null=True, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="paginas_captacao", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-atualizado_em"]
        verbose_name = "página de captação"
        verbose_name_plural = "páginas de captação"

    def __str__(self):
        return self.nome

    @property
    def publicada(self) -> bool:
        return self.status == self.Status.PUBLICADA

    def get_absolute_url(self) -> str:
        from django.urls import reverse
        return reverse("captacao:publica", args=[self.slug])

    @property
    def leads(self) -> int:
        return self.oportunidades.count()

    @property
    def conversao(self) -> float:
        """Percentual leads ÷ visitas (0 se sem visitas)."""
        if not self.visitas:
            return 0.0
        return round(self.leads * 100 / self.visitas, 1)

    @property
    def reservas_geradas(self) -> int:
        return self.oportunidades.filter(status=Oportunidade.Status.GANHA).count()

    @property
    def faq_itens(self) -> list:
        """Parseia faq_texto em [{'pergunta':…, 'resposta':…}] (blocos P:/R:)."""
        import re
        texto = (self.faq_texto or "").replace("\r\n", "\n").replace("\r", "\n")
        itens = []
        for bloco in re.split(r"\n\s*\n", texto):
            pergunta, resposta = "", []
            for linha in bloco.strip().splitlines():
                s = linha.strip()
                if s[:2].upper() == "P:":
                    pergunta = s[2:].strip()
                elif s[:2].upper() == "R:":
                    resposta.append(s[2:].strip())
                elif pergunta:
                    resposta.append(s)
            if pergunta:
                itens.append({"pergunta": pergunta, "resposta": " ".join(resposta).strip()})
        return itens


class Campanha(models.Model):
    """Campanha de anúncio pago (Impulsionamento) — item do Comercial.

    Liga um investimento de mídia a uma Página de Captação (destino) e aos leads
    que gerou (via `Oportunidade.campanha`, casada pelo `utm_campaign`). Base do
    painel de custo por lead/reserva e retorno. Fase A do Gestor de Impulsionamento.
    """

    class Provedor(models.TextChoices):
        META = "meta", "Meta (Instagram/Facebook)"
        GOOGLE = "google", "Google"
        OUTRO = "outro", "Outra"

    nome = models.CharField("nome", max_length=100)
    codigo = models.SlugField(
        "código (casa com utm_campaign)", max_length=80, unique=True,
        help_text="Use este valor no utm_campaign do anúncio para atribuir os leads.",
    )
    provedor = models.CharField(
        "provedor", max_length=10, choices=Provedor.choices, default=Provedor.META,
    )
    pagina_captacao = models.ForeignKey(
        PaginaCaptacao, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campanhas", verbose_name="página de captação (destino)",
    )
    verba = models.DecimalField(
        "verba planejada (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )
    id_externo = models.CharField(
        "ID na plataforma", max_length=64, blank=True,
        help_text="ID da campanha no Meta/Google (para a Fase C — sincronizar gasto).",
    )
    ativa = models.BooleanField("ativa", default=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="campanhas_criadas", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-atualizado_em"]
        verbose_name = "campanha de anúncio"
        verbose_name_plural = "campanhas de anúncio"

    def __str__(self):
        return self.nome

    @property
    def gasto_total(self) -> Decimal:
        from django.db.models import Sum
        return self.gastos.aggregate(s=Sum("valor"))["s"] or Decimal("0.00")

    @property
    def leads(self) -> int:
        return self.oportunidades.count()

    @property
    def reservas(self) -> int:
        return self.oportunidades.filter(status=Oportunidade.Status.GANHA).count()

    @property
    def receita(self) -> Decimal:
        from django.db.models import Sum
        total = self.oportunidades.filter(status=Oportunidade.Status.GANHA).aggregate(
            s=Sum("valor_estimado"))["s"]
        return total or Decimal("0.00")

    @property
    def custo_por_lead(self) -> Decimal:
        if not self.leads:
            return Decimal("0.00")
        return (self.gasto_total / self.leads).quantize(Decimal("0.01"))

    @property
    def custo_por_reserva(self) -> Decimal:
        if not self.reservas:
            return Decimal("0.00")
        return (self.gasto_total / self.reservas).quantize(Decimal("0.01"))

    @property
    def retorno(self) -> Decimal:
        """Retorno sobre o investimento (receita ÷ gasto). 0 se sem gasto."""
        if not self.gasto_total:
            return Decimal("0.00")
        return (self.receita / self.gasto_total).quantize(Decimal("0.01"))


class GastoDiario(models.Model):
    """Lançamento de gasto de uma campanha (manual na Fase A; sincronizado na Fase C)."""

    class Origem(models.TextChoices):
        MANUAL = "manual", "Manual"
        SINCRONIZADO = "sincronizado", "Sincronizado (API)"

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="gastos",
        verbose_name="campanha",
    )
    data = models.DateField("data")
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)
    origem = models.CharField(
        "origem do dado", max_length=12, choices=Origem.choices, default=Origem.MANUAL,
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="gastos_midia", verbose_name="lançado por",
    )
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "gasto de anúncio"
        verbose_name_plural = "gastos de anúncio"

    def __str__(self):
        return f"{self.campanha.nome} — {self.data:%d/%m}: R$ {self.valor}"


class ConversaoEnviada(models.Model):
    """Trilha das conversões devolvidas às plataformas (Fase B). Garante idempotência:
    uma conversão ENVIADA por (oportunidade, evento) — reenvios ficam registrados."""

    class Evento(models.TextChoices):
        LEAD = "lead", "Lead"
        COMPRA = "compra", "Compra / Reserva"

    class Status(models.TextChoices):
        ENVIADA = "enviada", "Enviada"
        ERRO = "erro", "Erro"

    oportunidade = models.ForeignKey(
        Oportunidade, on_delete=models.CASCADE, related_name="conversoes_enviadas",
        verbose_name="oportunidade",
    )
    evento = models.CharField("evento", max_length=8, choices=Evento.choices)
    provedor = models.CharField("provedor", max_length=12)
    status = models.CharField("status", max_length=8, choices=Status.choices)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2, null=True, blank=True)
    id_externo = models.CharField("ID na plataforma", max_length=120, blank=True)
    erro = models.TextField("erro", blank=True)
    enviado_em = models.DateTimeField("enviada em", auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "conversão enviada"
        verbose_name_plural = "conversões enviadas"
        indexes = [models.Index(fields=["oportunidade", "evento", "status"])]

    def __str__(self):
        return f"{self.get_evento_display()} → {self.provedor} ({self.status})"


class RespostaRapida(models.Model):
    """Texto pré-salvo (canned response). Independe da API do WhatsApp: aparece como
    chip com 'Copiar' hoje e passa a inserir no chat quando a integração entrar.
    Variáveis suportadas no texto: {nome} {checkin} {checkout} {noites} {valor} {vagas}.
    """

    titulo = models.CharField("título (rótulo do chip)", max_length=60)
    texto = models.TextField("texto")
    atalho = models.CharField("atalho", max_length=20, blank=True)
    ordem = models.PositiveSmallIntegerField("ordem", default=0)
    ativo = models.BooleanField("ativo", default=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="respostas_rapidas", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["ordem", "titulo"]
        verbose_name = "resposta rápida"
        verbose_name_plural = "respostas rápidas"

    def __str__(self):
        return self.titulo


class ConversaWhatsApp(models.Model):
    """Fio de conversa do WhatsApp de um lead (MVP simulado / Cloud API depois)."""

    oportunidade = models.OneToOneField(
        Oportunidade, on_delete=models.CASCADE, related_name="conversa_whatsapp",
        verbose_name="oportunidade",
    )
    telefone = models.CharField("telefone", max_length=20, blank=True)
    ultima_msg_cliente_em = models.DateTimeField(
        "última mensagem do cliente", null=True, blank=True,
        help_text="Abre a janela de 24h para mensagens livres.",
    )
    nao_lidas = models.PositiveSmallIntegerField("não lidas", default=0)
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "conversa de WhatsApp"
        verbose_name_plural = "conversas de WhatsApp"

    def __str__(self):
        return f"WhatsApp — {self.oportunidade.pessoa.nome}"

    @property
    def janela_aberta(self) -> bool:
        """True se a última mensagem do cliente foi há menos de 24h (mensagem livre ok)."""
        from datetime import timedelta

        from django.utils import timezone
        if not self.ultima_msg_cliente_em:
            return False
        return timezone.now() - self.ultima_msg_cliente_em < timedelta(hours=24)


class MensagemWhatsApp(models.Model):
    """Cada mensagem trocada (entrada = do cliente, saída = da pousada)."""

    class Direcao(models.TextChoices):
        ENTRADA = "entrada", "Recebida"
        SAIDA = "saida", "Enviada"

    class Status(models.TextChoices):
        RECEBIDA = "recebida", "Recebida"
        ENVIADA = "enviada", "Enviada"
        ERRO = "erro", "Erro"

    conversa = models.ForeignKey(
        ConversaWhatsApp, on_delete=models.CASCADE, related_name="mensagens",
        verbose_name="conversa",
    )
    direcao = models.CharField("direção", max_length=8, choices=Direcao.choices)
    texto = models.TextField("texto")
    status = models.CharField("status", max_length=10, choices=Status.choices)
    id_externo = models.CharField("ID externo", max_length=120, blank=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mensagens_whatsapp", verbose_name="autor (envio)",
    )
    horario = models.DateTimeField("horário")
    criado_em = models.DateTimeField("registrada em", auto_now_add=True)

    class Meta:
        ordering = ["horario", "id"]
        verbose_name = "mensagem de WhatsApp"
        verbose_name_plural = "mensagens de WhatsApp"

    def __str__(self):
        return f"{self.get_direcao_display()}: {self.texto[:40]}"


class EnvioEmail(models.Model):
    """Livro-razão (append-only) de cada e-mail enviado a um destinatário.

    Compartilhado entre o trilho 1:1 (enviado do lead) e a futura campanha em massa
    (FK campanha entra na Fase 3). Nunca se edita destrutivamente: correção = novo envio.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENVIADO = "enviado", "Enviado"
        ENTREGUE = "entregue", "Entregue"
        BOUNCE = "bounce", "Devolvido (bounce)"
        RECLAMADO = "reclamado", "Reclamação"
        ABERTO = "aberto", "Aberto"
        ERRO = "erro", "Erro"

    oportunidade = models.ForeignKey(
        Oportunidade, on_delete=models.CASCADE, related_name="emails",
        null=True, blank=True, verbose_name="oportunidade",
    )
    campanha = models.ForeignKey(
        "CampanhaEmail", on_delete=models.CASCADE, related_name="envios",
        null=True, blank=True, verbose_name="campanha",
    )
    pessoa = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.SET_NULL, related_name="emails_comerciais",
        null=True, blank=True, verbose_name="destinatário (pessoa)",
    )
    email = models.EmailField("e-mail")
    assunto = models.CharField("assunto", max_length=200)
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.PENDENTE)
    message_id = models.CharField("message-id", max_length=120, blank=True, db_index=True)
    erro = models.TextField("erro", blank=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="emails_enviados", verbose_name="autor (envio)",
    )
    enviado_em = models.DateTimeField("enviado em", null=True, blank=True)
    evento_em = models.DateTimeField("último evento em", null=True, blank=True)
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "envio de e-mail"
        verbose_name_plural = "envios de e-mail"

    def __str__(self):
        return f"{self.email}: {self.assunto[:40]}"


class TemplateEmail(models.Model):
    """E-mail salvo e reutilizável (assunto + corpo com variáveis).

    Base tanto do 1:1 (aplicado ao lead) quanto da campanha em massa (Fase 3). Variáveis
    no texto: {primeiro_nome} {nome} {quarto} {checkin} {checkout} {noites} {pessoas}
    {total}. `blocos` reserva o liga/desliga de blocos 1:1 (resumo/link) para o massa.
    """

    nome = models.CharField("nome", max_length=80)
    assunto = models.CharField("assunto", max_length=200)
    corpo = models.TextField("corpo (abertura, com variáveis)")
    blocos = models.JSONField("blocos opcionais", default=dict, blank=True)
    ativo = models.BooleanField("ativo", default=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="templates_email", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "template de e-mail"
        verbose_name_plural = "templates de e-mail"

    def __str__(self):
        return self.nome


class CampanhaEmail(models.Model):
    """Disparo de e-mail em massa para um segmento do funil.

    `segmento` é um dict de filtros (etapa/temperatura/origem/pagina). O envio materializa
    um EnvioEmail por destinatário (idempotente). Os contadores são desnormalizados.
    """

    class Status(models.TextChoices):
        RASCUNHO = "rascunho", "Rascunho"
        AGENDADA = "agendada", "Agendada"
        ENVIANDO = "enviando", "Enviando"
        ENVIADA = "enviada", "Enviada"
        CANCELADA = "cancelada", "Cancelada"

    nome = models.CharField("nome", max_length=100)
    assunto = models.CharField("assunto", max_length=200)
    corpo = models.TextField("corpo (com variáveis)")
    template = models.ForeignKey(
        "TemplateEmail", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campanhas", verbose_name="template de origem",
    )
    segmento = models.JSONField("segmento (filtros)", default=dict, blank=True)
    status = models.CharField("status", max_length=10, choices=Status.choices,
                              default=Status.RASCUNHO)
    agendar_para = models.DateTimeField("agendar para", null=True, blank=True)
    # Contadores desnormalizados (atualizados no envio).
    total = models.PositiveIntegerField("público-alvo", default=0)
    enviados = models.PositiveIntegerField("enviados", default=0)
    erros = models.PositiveIntegerField("erros", default=0)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="campanhas_email", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    enviada_em = models.DateTimeField("enviada em", null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "campanha de e-mail"
        verbose_name_plural = "campanhas de e-mail"

    def __str__(self):
        return self.nome

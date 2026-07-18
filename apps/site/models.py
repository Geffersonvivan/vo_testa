import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Tempo que uma reserva fica "segurando" o quarto antes de expirar (sem pagamento).
RESERVA_VALIDADE_MINUTOS = 30

# Tamanho máximo de upload de imagem.
MAX_UPLOAD_IMAGEM_MB = 5


def validar_tamanho_imagem(arquivo):
    """Impede uploads de imagem acima do limite definido."""
    limite = MAX_UPLOAD_IMAGEM_MB * 1024 * 1024
    if arquivo.size and arquivo.size > limite:
        raise ValidationError(f'A imagem não pode passar de {MAX_UPLOAD_IMAGEM_MB} MB.')


class CategoriaQuarto(models.Model):
    nome = models.CharField('Nome', max_length=50)
    descricao = models.TextField('Descrição', blank=True)
    ordem = models.PositiveSmallIntegerField('Ordem de exibição', default=0)

    class Meta:
        verbose_name = 'Categoria de Quarto'
        verbose_name_plural = 'Categorias de Quartos'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Quarto(models.Model):
    STATUS_CHOICES = [
        ('disponivel', 'Disponível'),
        ('manutencao', 'Em Manutenção'),
        ('inativo', 'Inativo'),
    ]

    nome = models.CharField('Nome', max_length=100)
    # Fonte da verdade: cada "quarto do site" é a vitrine de um TipoUH do CRM.
    # Disponibilidade e preço vêm do CRM; foto/descrição ficam aqui (marketing).
    tipo_uh = models.ForeignKey(
        'nucleo.TipoUH', on_delete=models.PROTECT, null=True, blank=True,
        related_name='vitrine_site', verbose_name='Tipo de quarto (CRM)',
        help_text='Vincula este card ao tipo real do CRM (disponibilidade e preço).',
    )
    categoria = models.ForeignKey(
        CategoriaQuarto,
        on_delete=models.PROTECT,
        related_name='quartos',
        verbose_name='Categoria',
    )
    descricao = models.TextField('Descrição')
    descricao_curta = models.CharField('Descrição curta', max_length=200, help_text='Texto exibido no card do site')
    capacidade = models.PositiveSmallIntegerField('Capacidade (hóspedes)')
    metragem = models.PositiveSmallIntegerField('Metragem (m²)')
    preco_base = models.DecimalField('Preço base (noite)', max_digits=8, decimal_places=2)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='disponivel')
    destaque = models.BooleanField('Exibir em destaque na home', default=False)
    foto_principal = models.ImageField('Foto principal', upload_to='quartos/', blank=True, validators=[validar_tamanho_imagem])
    nota_avaliacao = models.DecimalField(
        'Nota de avaliação',
        max_digits=2,
        decimal_places=1,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        default=5.0,
    )
    ordem = models.PositiveSmallIntegerField('Ordem de exibição', default=0)
    criado_em = models.DateTimeField('Criado em', auto_now_add=True)
    atualizado_em = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Quarto'
        verbose_name_plural = 'Quartos'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return f'{self.nome} ({self.categoria})'


class FotoQuarto(models.Model):
    quarto = models.ForeignKey(Quarto, on_delete=models.CASCADE, related_name='fotos', verbose_name='Quarto')
    imagem = models.ImageField('Imagem', upload_to='quartos/', validators=[validar_tamanho_imagem])
    legenda = models.CharField('Legenda', max_length=150, blank=True)
    ordem = models.PositiveSmallIntegerField('Ordem', default=0)

    class Meta:
        verbose_name = 'Foto do Quarto'
        verbose_name_plural = 'Fotos do Quarto'
        ordering = ['ordem']

    def __str__(self):
        return f'Foto {self.ordem} — {self.quarto.nome}'


class Temporada(models.Model):
    TIPO_CHOICES = [
        ('alta', 'Alta Temporada'),
        ('baixa', 'Baixa Temporada'),
        ('feriado', 'Feriado / Evento'),
    ]

    nome = models.CharField('Nome', max_length=100, help_text='Ex: Réveillon 2026, Verão 2027')
    tipo = models.CharField('Tipo', max_length=10, choices=TIPO_CHOICES)
    data_inicio = models.DateField('Data de início')
    data_fim = models.DateField('Data de fim')
    multiplicador = models.DecimalField(
        'Multiplicador de preço',
        max_digits=4,
        decimal_places=2,
        default=1.00,
        help_text='1.00 = preço base, 1.30 = +30%, 0.80 = -20%',
    )

    class Meta:
        verbose_name = 'Temporada'
        verbose_name_plural = 'Temporadas'
        ordering = ['data_inicio']

    def __str__(self):
        return f'{self.nome} ({self.get_tipo_display()})'


class Hospede(models.Model):
    nome = models.CharField('Nome completo', max_length=150)
    email = models.EmailField('Email', unique=True)
    telefone = models.CharField('Telefone / WhatsApp', max_length=20)
    cpf = models.CharField('CPF', max_length=14, unique=True, null=True, blank=True)
    observacoes = models.TextField('Observações', blank=True, help_text='Preferências, alergias, etc.')
    criado_em = models.DateTimeField('Cadastrado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Hóspede'
        verbose_name_plural = 'Hóspedes'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Experiencia(models.Model):
    nome = models.CharField('Nome', max_length=100)
    descricao = models.TextField('Descrição')
    icone = models.CharField(
        'Ícone SVG',
        max_length=500,
        blank=True,
        help_text='Path SVG do ícone (Heroicons)',
    )
    destaque = models.BooleanField('Exibir na home', default=True)
    ordem = models.PositiveSmallIntegerField('Ordem de exibição', default=0)

    class Meta:
        verbose_name = 'Experiência'
        verbose_name_plural = 'Experiências'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Depoimento(models.Model):
    PLATAFORMA_CHOICES = [
        ('booking', 'Booking.com'),
        ('google', 'Google'),
        ('tripadvisor', 'TripAdvisor'),
        ('instagram', 'Instagram'),
        ('site', 'Site'),
        ('outro', 'Outro'),
    ]

    nome_hospede = models.CharField('Nome do hóspede', max_length=100)
    texto = models.TextField('Depoimento')
    nota = models.PositiveSmallIntegerField(
        'Nota',
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=5,
    )
    plataforma = models.CharField('Plataforma de origem', max_length=20, choices=PLATAFORMA_CHOICES)
    data_avaliacao = models.DateField('Data da avaliação')
    destaque = models.BooleanField('Exibir na home', default=True)
    ordem = models.PositiveSmallIntegerField('Ordem de exibição', default=0)

    class Meta:
        verbose_name = 'Depoimento'
        verbose_name_plural = 'Depoimentos'
        ordering = ['ordem', '-data_avaliacao']

    def __str__(self):
        return f'{self.nome_hospede} — {self.get_plataforma_display()} ({self.nota}★)'


class FotoGaleria(models.Model):
    CATEGORIA_CHOICES = [
        ('pousada', 'Pousada'),
        ('quartos', 'Quartos'),
        ('natureza', 'Natureza'),
        ('gastronomia', 'Gastronomia'),
        ('experiencias', 'Experiências'),
        ('eventos', 'Eventos'),
    ]

    imagem = models.ImageField('Imagem', upload_to='galeria/', validators=[validar_tamanho_imagem])
    legenda = models.CharField('Legenda', max_length=150, blank=True)
    categoria = models.CharField('Categoria', max_length=20, choices=CATEGORIA_CHOICES)
    destaque = models.BooleanField('Destaque (tamanho grande no grid)', default=False)
    ordem = models.PositiveSmallIntegerField('Ordem de exibição', default=0)
    criado_em = models.DateTimeField('Adicionada em', auto_now_add=True)

    class Meta:
        verbose_name = 'Foto da Galeria'
        verbose_name_plural = 'Fotos da Galeria'
        ordering = ['ordem', '-criado_em']

    def __str__(self):
        return f'{self.legenda or "Sem legenda"} ({self.get_categoria_display()})'


class ConfiguracaoSite(models.Model):
    # Hero
    texto_boas_vindas = models.CharField('Texto de boas-vindas', max_length=100, default='Bem-vindo(a), viajante ao')
    frase_hero = models.CharField('Frase do hero', max_length=200, default='As engrenagens do tempo desaceleraram para você apreciar a beleza da natureza')

    # Contato
    telefone = models.CharField('Telefone', max_length=20, default='+49 9 9999-9999')
    whatsapp = models.CharField('WhatsApp (com DDI)', max_length=20, default='5549999999999')
    email = models.EmailField('Email', default='contato@pousadavotesta.com.br')
    endereco = models.CharField('Endereço', max_length=200, default='Rodovia SC 117, KM 130 — Lago Azul, 89760-000 Ita - SC')

    # Redes sociais
    instagram_url = models.URLField('Instagram', blank=True)
    facebook_url = models.URLField('Facebook', blank=True)
    tiktok_url = models.URLField('TikTok', blank=True)

    # Números de impacto (hero)
    numero_viajantes = models.CharField('Número de viajantes', max_length=20, default='+5 mil')
    numero_quartos = models.CharField('Número de quartos', max_length=20, default='+30')
    numero_zonas = models.CharField('Número de zonas', max_length=20, default='05')
    numero_avaliacoes = models.CharField('Número de avaliações', max_length=20, default='19 mil')

    # Desconto
    desconto_pix = models.PositiveSmallIntegerField('Desconto Pix (%)', default=5)

    class Meta:
        verbose_name = 'Configuração do Site'
        verbose_name_plural = 'Configuração do Site'

    def __str__(self):
        return 'Configuração do Site'

    def save(self, *args, **kwargs):
        # Singleton — garante que só existe uma configuração
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Reserva(models.Model):
    STATUS_CHOICES = [
        ('aguardando', 'Aguardando Pagamento'),
        ('confirmada', 'Confirmada'),
        ('checkin', 'Check-in Realizado'),
        ('finalizada', 'Finalizada'),
        ('cancelada', 'Cancelada'),
        ('expirada', 'Expirada'),
    ]

    PAGAMENTO_CHOICES = [
        ('pendente', 'Pendente'),
        ('pix', 'Pix'),
        ('cartao', 'Cartão de Crédito'),
        ('boleto', 'Boleto'),
    ]

    codigo = models.CharField('Código da reserva', max_length=16, unique=True, editable=False)
    # Token aleatório para a URL pública (o código é previsível e não deve ir na URL).
    token = models.UUIDField('Token público', default=uuid.uuid4, editable=False, unique=True)
    hospede = models.ForeignKey(
        Hospede,
        on_delete=models.PROTECT,
        related_name='reservas',
        verbose_name='Hóspede',
    )
    quarto = models.ForeignKey(
        Quarto,
        on_delete=models.PROTECT,
        related_name='reservas',
        verbose_name='Quarto',
    )
    data_checkin = models.DateField('Check-in')
    data_checkout = models.DateField('Check-out')
    num_hospedes = models.PositiveSmallIntegerField('Número de hóspedes', default=1)

    preco_noite = models.DecimalField('Preço por noite', max_digits=8, decimal_places=2)
    desconto_percentual = models.DecimalField(
        'Desconto (%)',
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='Ex: 5.00 para 5% de desconto (Pix)',
    )
    valor_total = models.DecimalField('Valor total', max_digits=10, decimal_places=2, editable=False, default=0)

    metodo_pagamento = models.CharField('Método de pagamento', max_length=10, choices=PAGAMENTO_CHOICES, default='pendente')
    pagamento_id = models.CharField('ID do pagamento (Mercado Pago)', max_length=100, blank=True)

    status = models.CharField('Status', max_length=15, choices=STATUS_CHOICES, default='aguardando')
    observacoes = models.TextField('Observações', blank=True)

    # Vínculo com a reserva real no CRM (fonte da verdade da disponibilidade).
    # Esta Reserva do site é só o recibo/confirmação do canal.
    crm_reserva_id = models.PositiveIntegerField('Reserva no CRM', null=True, blank=True)

    # Reservas 'aguardando' seguram o quarto só até expira_em (evita bloqueio eterno sem pagamento).
    expira_em = models.DateTimeField('Expira em', null=True, blank=True, editable=False)

    criado_em = models.DateTimeField('Criado em', auto_now_add=True)
    atualizado_em = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Reserva'
        verbose_name_plural = 'Reservas'
        ordering = ['-criado_em']
        constraints = [
            models.CheckConstraint(
                condition=Q(data_checkout__gt=models.F('data_checkin')),
                name='checkout_depois_checkin',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.hospede.nome} ({self.quarto.nome})'

    @property
    def noites(self):
        if self.data_checkin and self.data_checkout:
            return (self.data_checkout - self.data_checkin).days
        return 0

    def calcular_valor_total(self):
        preco = Decimal(str(self.preco_noite))
        subtotal = preco * self.noites
        if self.desconto_percentual:
            desconto = Decimal(str(self.desconto_percentual))
            subtotal -= subtotal * desconto / 100
        return subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        novo = self._state.adding
        if not self.codigo:
            now = datetime.now()
            self.codigo = f"VT-{now:%d%m%y}-{now:%H%M}"
        # Ao criar uma reserva aguardando pagamento, define o prazo de validade.
        if novo and self.status == 'aguardando' and not self.expira_em:
            self.expira_em = timezone.now() + timedelta(minutes=RESERVA_VALIDADE_MINUTOS)
        self.valor_total = self.calcular_valor_total()
        super().save(*args, **kwargs)

    @staticmethod
    def filtro_ativas(agora=None):
        """Q das reservas que realmente ocupam um quarto.

        'confirmada'/'checkin' sempre ocupam; 'aguardando' só ocupa enquanto não expira.
        """
        agora = agora or timezone.now()
        return (
            Q(status__in=['confirmada', 'checkin'])
            | Q(status='aguardando', expira_em__isnull=True)
            | Q(status='aguardando', expira_em__gt=agora)
        )

    @staticmethod
    def quarto_disponivel(quarto, checkin, checkout, excluir_reserva_id=None):
        """Verifica se o quarto está livre no período. Retorna True se disponível."""
        conflitos = Reserva.objects.filter(
            Reserva.filtro_ativas(),
            quarto=quarto,
            data_checkin__lt=checkout,
            data_checkout__gt=checkin,
        )
        if excluir_reserva_id:
            conflitos = conflitos.exclude(pk=excluir_reserva_id)
        return not conflitos.exists()

    @staticmethod
    def calcular_preco_noite(quarto, data_checkin):
        """Retorna o preço da noite com multiplicador de temporada aplicado."""
        temporada = Temporada.objects.filter(
            data_inicio__lte=data_checkin,
            data_fim__gte=data_checkin,
        ).order_by('-multiplicador').first()
        multiplicador = Decimal(str(temporada.multiplicador)) if temporada else Decimal('1')
        return (quarto.preco_base * multiplicador).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

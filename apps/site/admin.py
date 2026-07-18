from django.contrib import admin

from .models import (
    CategoriaQuarto,
    ConfiguracaoSite,
    Depoimento,
    Experiencia,
    FotoGaleria,
    FotoQuarto,
    Hospede,
    Quarto,
    Reserva,
    Temporada,
)

# ==========================================
# QUARTOS
# ==========================================

class FotoQuartoInline(admin.TabularInline):
    model = FotoQuarto
    extra = 1
    fields = ['imagem', 'legenda', 'ordem']


@admin.register(CategoriaQuarto)
class CategoriaQuartoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'ordem']
    list_editable = ['ordem']
    search_fields = ['nome']


@admin.register(Quarto)
class QuartoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'categoria', 'capacidade', 'metragem', 'preco_base', 'status', 'destaque', 'ordem']
    list_filter = ['categoria', 'status', 'destaque']
    list_editable = ['status', 'destaque', 'ordem']
    search_fields = ['nome', 'descricao']
    inlines = [FotoQuartoInline]
    fieldsets = [
        ('Informações', {
            'fields': ['nome', 'categoria', 'descricao', 'descricao_curta'],
        }),
        ('Detalhes', {
            'fields': ['capacidade', 'metragem', 'preco_base', 'nota_avaliacao'],
        }),
        ('Foto e Exibição', {
            'fields': ['foto_principal', 'destaque', 'status', 'ordem'],
        }),
    ]


# ==========================================
# TEMPORADAS
# ==========================================

@admin.register(Temporada)
class TemporadaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'data_inicio', 'data_fim', 'multiplicador']
    list_filter = ['tipo']
    search_fields = ['nome']


# ==========================================
# HÓSPEDES
# ==========================================

@admin.register(Hospede)
class HospedeAdmin(admin.ModelAdmin):
    list_display = ['nome', 'email', 'telefone', 'cpf', 'criado_em']
    search_fields = ['nome', 'email', 'cpf', 'telefone']
    list_filter = ['criado_em']
    readonly_fields = ['criado_em']


# ==========================================
# EXPERIÊNCIAS
# ==========================================

@admin.register(Experiencia)
class ExperienciaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'destaque', 'ordem']
    list_filter = ['destaque']
    list_editable = ['destaque', 'ordem']
    search_fields = ['nome']


# ==========================================
# DEPOIMENTOS
# ==========================================

@admin.register(Depoimento)
class DepoimentoAdmin(admin.ModelAdmin):
    list_display = ['nome_hospede', 'nota', 'plataforma', 'data_avaliacao', 'destaque', 'ordem']
    list_filter = ['plataforma', 'nota', 'destaque']
    list_editable = ['destaque', 'ordem']
    search_fields = ['nome_hospede', 'texto']


# ==========================================
# GALERIA
# ==========================================

@admin.register(FotoGaleria)
class FotoGaleriaAdmin(admin.ModelAdmin):
    list_display = ['legenda', 'categoria', 'destaque', 'ordem', 'criado_em']
    list_filter = ['categoria', 'destaque']
    list_editable = ['categoria', 'destaque', 'ordem']
    search_fields = ['legenda']


# ==========================================
# RESERVAS
# ==========================================

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'hospede', 'quarto', 'data_checkin', 'data_checkout', 'noites', 'valor_total', 'status', 'metodo_pagamento', 'criado_em']
    list_filter = ['status', 'metodo_pagamento', 'data_checkin', 'quarto']
    search_fields = ['codigo', 'hospede__nome', 'hospede__email', 'hospede__cpf']
    readonly_fields = ['codigo', 'valor_total', 'noites', 'criado_em', 'atualizado_em']
    list_editable = ['status']
    date_hierarchy = 'data_checkin'
    fieldsets = [
        ('Reserva', {
            'fields': ['codigo', 'status'],
        }),
        ('Hóspede e Quarto', {
            'fields': ['hospede', 'quarto', 'num_hospedes'],
        }),
        ('Datas', {
            'fields': ['data_checkin', 'data_checkout', 'noites'],
        }),
        ('Valores', {
            'fields': ['preco_noite', 'desconto_percentual', 'valor_total'],
        }),
        ('Pagamento', {
            'fields': ['metodo_pagamento', 'pagamento_id'],
        }),
        ('Observações', {
            'fields': ['observacoes'],
            'classes': ['collapse'],
        }),
        ('Datas do sistema', {
            'fields': ['criado_em', 'atualizado_em'],
            'classes': ['collapse'],
        }),
    ]

    @admin.display(description='Noites')
    def noites(self, obj):
        return obj.noites


# ==========================================
# CONFIGURAÇÃO DO SITE (Singleton)
# ==========================================

@admin.register(ConfiguracaoSite)
class ConfiguracaoSiteAdmin(admin.ModelAdmin):
    fieldsets = [
        ('Hero', {
            'fields': ['texto_boas_vindas', 'frase_hero'],
        }),
        ('Números de Impacto', {
            'fields': ['numero_viajantes', 'numero_quartos', 'numero_zonas', 'numero_avaliacoes'],
        }),
        ('Contato', {
            'fields': ['telefone', 'whatsapp', 'email', 'endereco'],
        }),
        ('Redes Sociais', {
            'fields': ['instagram_url', 'facebook_url', 'tiktok_url'],
        }),
        ('Promoções', {
            'fields': ['desconto_pix'],
        }),
    ]

    def has_add_permission(self, request):
        # Só permite um registro
        return not ConfiguracaoSite.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

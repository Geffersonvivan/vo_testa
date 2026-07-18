from django.contrib import admin

from .models import (
    AtividadeComercial,
    Cotacao,
    EtapaFunil,
    MetaComercial,
    MotivoPerda,
    Oportunidade,
)


@admin.register(EtapaFunil)
class EtapaFunilAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "probabilidade", "tipo", "ativa")
    list_editable = ("ordem", "probabilidade", "ativa")
    ordering = ("ordem",)


@admin.register(MotivoPerda)
class MotivoPerdaAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativo")
    list_editable = ("ativo",)


class AtividadeInline(admin.TabularInline):
    model = AtividadeComercial
    extra = 0
    fields = ("tipo", "descricao", "quando", "concluida", "responsavel")


class CotacaoInline(admin.TabularInline):
    model = Cotacao
    extra = 0
    readonly_fields = ("valor_total", "criado_em")


@admin.register(Oportunidade)
class OportunidadeAdmin(admin.ModelAdmin):
    list_display = ("titulo", "pessoa", "etapa", "tipo_interesse", "faturamento", "status",
                    "score", "valor_estimado", "responsavel", "atualizado_em")
    list_filter = ("status", "etapa", "tipo_interesse", "faturamento", "origem")
    search_fields = ("titulo", "pessoa__nome")
    autocomplete_fields = ("pessoa",)
    readonly_fields = ("reserva_id", "cobranca_sinal_id", "score",
                       "nps_convidado_em", "criado_em", "atualizado_em", "fechado_em")
    inlines = [CotacaoInline, AtividadeInline]


@admin.register(MetaComercial)
class MetaComercialAdmin(admin.ModelAdmin):
    list_display = ("mes", "valor_meta", "oportunidades_meta")

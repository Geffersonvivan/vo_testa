from django.contrib import admin

from .models import (
    AtividadeComercial,
    Campanha,
    ConversaoEnviada,
    Cotacao,
    EnvioEmail,
    EtapaFunil,
    GastoDiario,
    MetaComercial,
    MotivoPerda,
    Oportunidade,
    PaginaCaptacao,
    RespostaRapida,
    TemplateEmail,
)


@admin.register(RespostaRapida)
class RespostaRapidaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "atalho", "ordem", "ativo")
    list_editable = ("ordem", "ativo")
    search_fields = ("titulo", "texto")


@admin.register(ConversaoEnviada)
class ConversaoEnviadaAdmin(admin.ModelAdmin):
    list_display = ("oportunidade", "evento", "provedor", "status", "valor", "enviado_em")
    list_filter = ("evento", "provedor", "status")
    readonly_fields = ("oportunidade", "evento", "provedor", "status", "valor",
                       "id_externo", "erro", "enviado_em")


@admin.register(Campanha)
class CampanhaAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo", "provedor", "gasto_total", "leads",
                    "custo_por_lead", "reservas", "retorno", "ativa")
    list_filter = ("provedor", "ativa")
    search_fields = ("nome", "codigo")
    prepopulated_fields = {"codigo": ("nome",)}


@admin.register(GastoDiario)
class GastoDiarioAdmin(admin.ModelAdmin):
    list_display = ("campanha", "data", "valor", "origem", "criado_em")
    list_filter = ("origem", "campanha")
    date_hierarchy = "data"


@admin.register(PaginaCaptacao)
class PaginaCaptacaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "status", "tipo_interesse", "visitas",
                    "leads", "conversao", "atualizado_em")
    list_filter = ("status", "tema", "tipo_interesse")
    search_fields = ("nome", "slug")
    prepopulated_fields = {"slug": ("nome",)}
    readonly_fields = ("visitas", "criado_por", "criado_em", "atualizado_em", "publicada_em")


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


@admin.register(EnvioEmail)
class EnvioEmailAdmin(admin.ModelAdmin):
    list_display = ("email", "assunto", "status", "oportunidade", "autor",
                    "enviado_em", "criado_em")
    list_filter = ("status",)
    search_fields = ("email", "assunto", "message_id", "oportunidade__pessoa__nome")
    readonly_fields = ("oportunidade", "pessoa", "email", "assunto", "status",
                       "message_id", "erro", "autor", "enviado_em", "evento_em",
                       "criado_em")


@admin.register(TemplateEmail)
class TemplateEmailAdmin(admin.ModelAdmin):
    list_display = ("nome", "assunto", "ativo", "criado_por", "atualizado_em")
    list_filter = ("ativo",)
    search_fields = ("nome", "assunto", "corpo")

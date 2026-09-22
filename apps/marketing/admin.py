from django.contrib import admin

from .models import (
    Campanha,
    Comentario,
    EtapaCampanha,
    ItemChecklist,
    PecaCampanha,
    VerbaMarketing,
)


class PecaInline(admin.TabularInline):
    model = PecaCampanha
    extra = 0


class EtapaInline(admin.TabularInline):
    model = EtapaCampanha
    extra = 0


class ChecklistInline(admin.TabularInline):
    model = ItemChecklist
    extra = 0


@admin.register(Campanha)
class CampanhaAdmin(admin.ModelAdmin):
    list_display = ("nome", "fase", "inicio", "fim", "verba_prevista", "verba_travada", "responsavel")
    list_filter = ("fase",)
    search_fields = ("nome", "objetivo", "publico")
    inlines = [ChecklistInline, PecaInline, EtapaInline]
    raw_id_fields = ("anuncio", "solicitante", "responsavel", "criativo", "aprovada_por")


@admin.register(PecaCampanha)
class PecaCampanhaAdmin(admin.ModelAdmin):
    list_display = ("nome", "campanha", "canal", "data", "status")
    list_filter = ("status",)


@admin.register(VerbaMarketing)
class VerbaMarketingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "alerta_pct")


admin.site.register(EtapaCampanha)
admin.site.register(ItemChecklist)
admin.site.register(Comentario)

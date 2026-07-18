from django.contrib import admin

from .models import Cobranca, EventoPagamento


class EventoInline(admin.TabularInline):
    model = EventoPagamento
    extra = 0
    readonly_fields = ("tipo", "origem", "detalhe", "criado_em")


@admin.register(Cobranca)
class CobrancaAdmin(admin.ModelAdmin):
    list_display = ("id", "metodo", "valor", "finalidade", "status", "criado_em")
    list_filter = ("status", "metodo", "finalidade")
    search_fields = ("descricao", "gateway_id")
    raw_id_fields = ("pagador", "criado_por")
    inlines = [EventoInline]


@admin.register(EventoPagamento)
class EventoPagamentoAdmin(admin.ModelAdmin):
    list_display = ("cobranca", "tipo", "origem", "criado_em")
    list_filter = ("tipo",)

from django.contrib import admin

from .models import Comanda, ItemComanda, Mesa


@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ["nome", "ativa"]


class ItemComandaInline(admin.TabularInline):
    model = ItemComanda
    extra = 0
    readonly_fields = ["produto", "descricao", "natureza", "quantidade", "preco_unitario"]


@admin.register(Comanda)
class ComandaAdmin(admin.ModelAdmin):
    list_display = ["pk", "titulo", "status", "destino", "aberta_em", "criado_por"]
    list_filter = ["status", "destino"]
    inlines = [ItemComandaInline]

    def has_delete_permission(self, request, obj=None):
        return False

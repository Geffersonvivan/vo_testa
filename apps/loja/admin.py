from django.contrib import admin

from .models import ItemVenda, Venda


class ItemVendaInline(admin.TabularInline):
    model = ItemVenda
    extra = 0
    readonly_fields = [
        "produto", "descricao", "natureza", "quantidade", "preco_unitario", "subtotal",
    ]
    can_delete = False


@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = ["pk", "criado_em", "destino", "total", "status", "criado_por"]
    list_filter = ["status", "destino"]
    inlines = [ItemVendaInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

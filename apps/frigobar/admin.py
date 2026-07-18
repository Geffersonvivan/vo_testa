from django.contrib import admin

from .models import Conferencia, ItemComposicao, ItemConferencia


@admin.register(ItemComposicao)
class ItemComposicaoAdmin(admin.ModelAdmin):
    list_display = ("tipo_uh", "produto", "quantidade")
    list_filter = ("tipo_uh",)
    raw_id_fields = ("produto",)


class ItemInline(admin.TabularInline):
    model = ItemConferencia
    extra = 0


@admin.register(Conferencia)
class ConferenciaAdmin(admin.ModelAdmin):
    list_display = ("id", "uh", "momento", "status", "criado_em")
    list_filter = ("status", "momento")
    raw_id_fields = ("uh", "criado_por", "reposto_por")
    inlines = [ItemInline]

from django.contrib import admin

from .models import (
    ItemEnxoval,
    ItemOrdemLavanderia,
    MovimentoEnxoval,
    OrdemLavanderia,
    ServicoLavanderia,
)


@admin.register(ServicoLavanderia)
class ServicoLavanderiaAdmin(admin.ModelAdmin):
    list_display = ("nome", "unidade", "preco", "ativo")
    list_filter = ("ativo", "unidade")
    search_fields = ("nome",)


class ItemInline(admin.TabularInline):
    model = ItemOrdemLavanderia
    extra = 0


@admin.register(OrdemLavanderia)
class OrdemLavanderiaAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "status", "destino", "recebida_em")
    list_filter = ("status", "destino")
    raw_id_fields = ("cliente", "forma_pagamento", "movimento_caixa", "criado_por")
    inlines = [ItemInline]


@admin.register(ItemEnxoval)
class ItemEnxovalAdmin(admin.ModelAdmin):
    list_display = ("nome", "unidade", "minimo", "por_faxina", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome",)


@admin.register(MovimentoEnxoval)
class MovimentoEnxovalAdmin(admin.ModelAdmin):
    list_display = ("item", "estado", "quantidade", "motivo", "uh", "criado_em")
    list_filter = ("estado", "motivo")
    raw_id_fields = ("item", "uh", "criado_por")

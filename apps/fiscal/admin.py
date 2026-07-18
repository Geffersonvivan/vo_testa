from django.contrib import admin

from .models import ConfigFiscalProduto, DocumentoFiscal, EventoFiscal


@admin.register(ConfigFiscalProduto)
class ConfigFiscalProdutoAdmin(admin.ModelAdmin):
    list_display = ("produto", "ncm", "cfop", "cst_csosn", "origem")
    raw_id_fields = ("produto",)


class EventoInline(admin.TabularInline):
    model = EventoFiscal
    extra = 0
    readonly_fields = ("tipo", "detalhe", "criado_em")


@admin.register(DocumentoFiscal)
class DocumentoFiscalAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "natureza", "status", "valor", "numero", "criado_em")
    list_filter = ("tipo", "natureza", "status", "gateway")
    search_fields = ("numero", "chave", "descricao")
    raw_id_fields = ("tomador", "criado_por")
    inlines = [EventoInline]

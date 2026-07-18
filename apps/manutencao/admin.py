from django.contrib import admin

from .models import OrdemServico


@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "alvo", "tipo", "prioridade", "status",
                    "prestador", "aberta_em")
    list_filter = ("status", "tipo", "prioridade")
    search_fields = ("titulo", "descricao", "area", "nota_fiscal")
    raw_id_fields = ("uh", "responsavel", "prestador", "criado_por")

from django.contrib import admin

from .models import ContaContabil, FechamentoMensal, MapeamentoContabil


@admin.register(ContaContabil)
class ContaContabilAdmin(admin.ModelAdmin):
    list_display = ("classificacao", "nome", "grupo", "tipo", "codigo_contador", "ativa")
    list_filter = ("grupo", "tipo", "ativa")
    search_fields = ("classificacao", "nome", "codigo_contador")
    ordering = ("classificacao",)


@admin.register(MapeamentoContabil)
class MapeamentoContabilAdmin(admin.ModelAdmin):
    list_display = (
        "origem_descricao", "conta", "prioridade", "ativo",
    )
    list_filter = ("ativo", "natureza_folio", "centro")
    search_fields = ("origem_sistema", "conta__classificacao", "conta__nome")
    autocomplete_fields = ("conta",)
    raw_id_fields = ("categoria",)


@admin.register(FechamentoMensal)
class FechamentoMensalAdmin(admin.ModelAdmin):
    list_display = ("__str__", "folha", "encargos", "pro_labore", "das", "fechado_em")
    ordering = ("-ano", "-mes")

    def save_model(self, request, obj, form, change):
        if not obj.fechado_por_id:
            obj.fechado_por = request.user
        super().save_model(request, obj, form, change)
        obj.aplicar()  # gera/atualiza os lançamentos do mês

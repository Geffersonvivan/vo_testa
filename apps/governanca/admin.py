from django.contrib import admin

from .models import StatusLimpeza, TarefaGovernanca


@admin.register(StatusLimpeza)
class StatusLimpezaAdmin(admin.ModelAdmin):
    list_display = ["uh", "situacao", "atualizado_em", "atualizado_por"]
    list_filter = ["situacao"]


@admin.register(TarefaGovernanca)
class TarefaGovernancaAdmin(admin.ModelAdmin):
    list_display = ["uh", "tipo", "status", "camareira", "gerada_em", "concluida_em"]
    list_filter = ["status", "tipo"]

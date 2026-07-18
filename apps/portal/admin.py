from django.contrib import admin

from .models import AcessoPortal, SolicitacaoPortal


@admin.register(AcessoPortal)
class AcessoPortalAdmin(admin.ModelAdmin):
    list_display = ("reserva_id", "token", "criado_em")
    search_fields = ("reserva_id",)


@admin.register(SolicitacaoPortal)
class SolicitacaoPortalAdmin(admin.ModelAdmin):
    list_display = ("tipo", "uh_numero", "reserva_id", "detalhe", "criado_em")
    list_filter = ("tipo",)

from django.contrib import admin

from .models import (
    Acompanhante,
    Adiantamento,
    ContaHospedagem,
    LancamentoConta,
    PagamentoConta,
    Reserva,
    Tarifa,
)


@admin.register(Tarifa)
class TarifaAdmin(admin.ModelAdmin):
    """Matriz TipoUH × temporada — parâmetro de negócio, gerido pelo Admin."""

    list_display = ["tipo_uh", "classificacao", "valor"]
    list_filter = ["tipo_uh", "classificacao"]


class AcompanhanteInline(admin.TabularInline):
    model = Acompanhante
    extra = 0


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = [
        "pk", "hospede", "uh", "checkin", "checkout", "status",
        "faturamento", "valor_diaria",
    ]
    list_filter = ["status", "faturamento", "uh"]
    search_fields = ["hospede__nome", "uh__numero", "titular__nome"]
    inlines = [AcompanhanteInline]

    def has_delete_permission(self, request, obj=None):
        # Reserva não some do histórico: cancela-se com motivo.
        return False


@admin.register(ContaHospedagem)
class ContaHospedagemAdmin(admin.ModelAdmin):
    list_display = ["reserva", "status", "aberta_em", "fechada_em"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LancamentoConta)
class LancamentoContaAdmin(admin.ModelAdmin):
    """Lançamentos são imutáveis — consulta apenas."""

    list_display = ["criado_em", "conta", "tipo", "natureza", "descricao", "valor"]
    list_filter = ["tipo", "natureza"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PagamentoConta)
class PagamentoContaAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "conta", "valor", "movimento_caixa"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Adiantamento)
class AdiantamentoAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "reserva", "valor", "movimento_caixa"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin

from .models import (
    Acompanhante,
    Adiantamento,
    ContaHospedagem,
    FichaFNRH,
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


class FichaFNRHInline(admin.TabularInline):
    model = FichaFNRH
    extra = 0
    fields = ["nome", "titular", "documento_numero", "cidade", "motivo_viagem", "origem"]


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = [
        "pk", "hospede", "uh", "checkin", "checkout", "status",
        "faturamento", "valor_diaria",
    ]
    list_filter = ["status", "faturamento", "uh"]
    search_fields = ["hospede__nome", "uh__numero", "titular__nome"]
    inlines = [FichaFNRHInline]

    def has_delete_permission(self, request, obj=None):
        # Reserva não some do histórico: cancela-se com motivo.
        return False


@admin.register(FichaFNRH)
class FichaFNRHAdmin(admin.ModelAdmin):
    list_display = ["nome", "reserva", "titular", "motivo_viagem", "origem", "preenchida_em"]
    list_filter = ["origem", "titular", "motivo_viagem", "meio_transporte"]
    search_fields = ["nome", "documento_numero", "cpf", "reserva__id"]


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

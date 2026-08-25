from django.contrib import admin

from .models import Atribuicao, Ausencia, Feriado, SemanaPublicada, TrocaTurno, Turno


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ("nome", "setor", "inicio", "fim", "min_pessoas", "ativo")
    list_filter = ("setor", "ativo")


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ("data", "nome", "municipal")
    list_filter = ("municipal",)


@admin.register(Atribuicao)
class AtribuicaoAdmin(admin.ModelAdmin):
    list_display = ("data", "turno", "funcionario")
    list_filter = ("turno__setor", "data")
    raw_id_fields = ("funcionario", "turno", "criado_por")


@admin.register(Ausencia)
class AusenciaAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "tipo", "inicio", "fim")
    list_filter = ("tipo",)
    raw_id_fields = ("funcionario", "criado_por")


@admin.register(TrocaTurno)
class TrocaTurnoAdmin(admin.ModelAdmin):
    list_display = ("id", "atribuicao", "solicitante", "substituto", "status")
    list_filter = ("status",)
    raw_id_fields = ("atribuicao", "solicitante", "substituto", "decidido_por")


@admin.register(SemanaPublicada)
class SemanaPublicadaAdmin(admin.ModelAdmin):
    list_display = ("inicio", "setor", "publicado_por", "publicado_em", "forcado")
    list_filter = ("forcado", "setor")

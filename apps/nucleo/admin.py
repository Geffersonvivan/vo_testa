from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ModuloContratado, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Acesso a módulos", {"fields": ("modulos",)}),
    )
    filter_horizontal = UserAdmin.filter_horizontal + ("modulos",)
    list_display = ["username", "first_name", "last_name", "is_active", "is_superuser"]


@admin.register(ModuloContratado)
class ModuloContratadoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "ativo", "ativado_em", "desativado_em"]
    list_filter = ["ativo"]

    def get_readonly_fields(self, request, obj=None):
        # Código não muda depois de criado; troca-se ativo/inativo.
        return ["codigo"] if obj else []

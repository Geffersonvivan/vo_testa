from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    UH,
    Agencia,
    CategoriaFinanceira,
    CategoriaProduto,
    ContaPagarReceber,
    EntradaLogbook,
    FormaPagamento,
    Fornecedor,
    Funcionario,
    Hospede,
    LancamentoFinanceiro,
    LocalEstoque,
    ModuloContratado,
    MovimentoCaixa,
    MovimentoEstoque,
    Pessoa,
    Produto,
    SessaoCaixa,
    Temporada,
    TipoUH,
    TrilhaAuditoria,
    Usuario,
)


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


class HospedeInline(admin.StackedInline):
    model = Hospede
    extra = 0


class FuncionarioInline(admin.StackedInline):
    model = Funcionario
    extra = 0


class FornecedorInline(admin.StackedInline):
    model = Fornecedor
    extra = 0


class AgenciaInline(admin.StackedInline):
    model = Agencia
    extra = 0


@admin.register(Pessoa)
class PessoaAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "documento", "telefone", "email", "ativo"]
    search_fields = ["nome", "documento", "email"]
    list_filter = ["tipo", "ativo"]
    inlines = [HospedeInline, AgenciaInline, FuncionarioInline, FornecedorInline]


@admin.register(TipoUH)
class TipoUHAdmin(admin.ModelAdmin):
    list_display = ["nome", "modalidade", "capacidade", "tarifa_base", "ativo"]
    list_filter = ["modalidade", "ativo"]


@admin.register(UH)
class UHAdmin(admin.ModelAdmin):
    list_display = ["numero", "tipo", "bloco", "status", "pcd"]
    list_filter = ["tipo", "status", "pcd"]


@admin.register(Temporada)
class TemporadaAdmin(admin.ModelAdmin):
    list_display = ["nome", "classificacao", "inicio", "fim"]
    list_filter = ["classificacao"]


@admin.register(FormaPagamento)
class FormaPagamentoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "permite_parcelamento", "ativo"]


@admin.register(CategoriaFinanceira)
class CategoriaFinanceiraAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "ativo"]
    list_filter = ["tipo", "ativo"]


@admin.register(SessaoCaixa)
class SessaoCaixaAdmin(admin.ModelAdmin):
    list_display = ["operador", "modulo", "status", "aberta_em", "fechada_em", "diferenca"]
    list_filter = ["status", "modulo"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MovimentoCaixa)
class MovimentoCaixaAdmin(admin.ModelAdmin):
    """Movimentos são imutáveis: o admin só permite consulta."""

    list_display = ["criado_em", "sessao", "tipo", "forma_pagamento", "valor", "descricao"]
    list_filter = ["tipo", "forma_pagamento"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LancamentoFinanceiro)
class LancamentoFinanceiroAdmin(admin.ModelAdmin):
    list_display = ["data", "tipo", "categoria", "centro", "descricao", "valor"]
    list_filter = ["tipo", "centro", "categoria"]


@admin.register(ContaPagarReceber)
class ContaPagarReceberAdmin(admin.ModelAdmin):
    list_display = ["descricao", "tipo", "pessoa", "valor", "vencimento", "status"]
    list_filter = ["tipo", "status"]


@admin.register(EntradaLogbook)
class EntradaLogbookAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "autor", "importante"]
    list_filter = ["importante"]


@admin.register(TrilhaAuditoria)
class TrilhaAuditoriaAdmin(admin.ModelAdmin):
    """Auditoria é só leitura — registrada pelo próprio sistema."""

    list_display = ["criado_em", "usuario", "acao", "alvo", "alvo_id"]
    list_filter = ["acao"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CategoriaProduto)
class CategoriaProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "ativo"]


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = [
        "nome", "categoria", "unidade", "natureza",
        "custo_medio", "preco_venda", "estoque_minimo", "ativo",
    ]
    list_filter = ["categoria", "natureza", "ativo"]
    search_fields = ["nome", "codigo_barras"]
    readonly_fields = ["custo_medio"]


@admin.register(LocalEstoque)
class LocalEstoqueAdmin(admin.ModelAdmin):
    list_display = ["nome", "modulo", "ativo"]


@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    """Kardex imutável — consulta apenas."""

    list_display = ["criado_em", "produto", "local", "tipo", "quantidade", "custo_unitario"]
    list_filter = ["tipo", "local", "produto"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

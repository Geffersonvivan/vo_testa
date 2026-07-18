"""
Models do núcleo, organizados por domínio:

- usuarios: Usuario, ModuloContratado e consultas de ativação
- cadastros: Pessoa (+ especializações), TipoUH, UH, Temporada
- financeiro: caixa por operador, movimentos imutáveis, contas, auditoria
- logbook: livro de ocorrências entre turnos
"""

from .cadastros import (
    UH,
    Agencia,
    Fornecedor,
    Funcionario,
    Hospede,
    Pessoa,
    Prospecto,
    Temporada,
    TipoUH,
)
from .estoque import (
    CategoriaProduto,
    Inventario,
    ItemInventario,
    LocalEstoque,
    MovimentoEstoque,
    Produto,
    ajustar,
    posicao_estoque,
    produtos_abaixo_minimo,
    registrar_entrada,
    registrar_saida,
    saldo,
    transferir,
)
from .financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    FormaPagamento,
    LancamentoFinanceiro,
    MovimentoCaixa,
    NaturezaFiscal,
    SessaoCaixa,
    TrilhaAuditoria,
    centro_choices,
    estornar_movimento,
    receber_no_caixa,
    registrar_auditoria,
)
from .logbook import EntradaLogbook
from .usuarios import ModuloContratado, Usuario, modulo_ativo, modulos_ativos

__all__ = [
    "UH",
    "Agencia",
    "CategoriaFinanceira",
    "CategoriaProduto",
    "Inventario",
    "ItemInventario",
    "LocalEstoque",
    "MovimentoEstoque",
    "Produto",
    "ajustar",
    "posicao_estoque",
    "produtos_abaixo_minimo",
    "registrar_entrada",
    "registrar_saida",
    "saldo",
    "transferir",
    "ContaPagarReceber",
    "EntradaLogbook",
    "FormaPagamento",
    "Fornecedor",
    "Funcionario",
    "Hospede",
    "LancamentoFinanceiro",
    "ModuloContratado",
    "MovimentoCaixa",
    "NaturezaFiscal",
    "Pessoa",
    "Prospecto",
    "SessaoCaixa",
    "Temporada",
    "TipoUH",
    "TrilhaAuditoria",
    "Usuario",
    "centro_choices",
    "estornar_movimento",
    "receber_no_caixa",
    "modulo_ativo",
    "modulos_ativos",
    "registrar_auditoria",
]

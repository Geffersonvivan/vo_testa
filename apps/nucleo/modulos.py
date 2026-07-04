"""
Catálogo de módulos do sistema.

Este é o coração do modelo "contratado por módulos": todo menu, permissão e
integração consulta este catálogo + a tabela ModuloContratado — nunca hard-code.
"""

from django.db import models


class Modulo(models.TextChoices):
    RESERVAS = "reservas", "Reservas"
    GOVERNANCA = "governanca", "Governança"
    MANUTENCAO = "manutencao", "Manutenção"
    ESCALA = "escala", "Escala"
    ESTOQUE = "estoque", "Estoque"
    LOJA = "loja", "Loja"
    RESTAURANTE = "restaurante", "Restaurante Piscina"
    LAVANDERIA = "lavanderia", "Lavanderia"
    FRIGOBAR = "frigobar", "Frigobar"
    PAGAMENTOS = "pagamentos", "Pagamentos Online"
    APPSITE = "appsite", "APP/Site"
    CRM_HOSPEDE = "crm_hospede", "CRM do Hóspede"
    CANAIS = "canais", "Canais/OTAs"
    FISCAL = "fiscal", "Fiscal"


# Dependências entre módulos (módulo -> módulos exigidos).
# Usado para validar ativação e para degradação graciosa.
DEPENDENCIAS: dict[str, list[str]] = {
    Modulo.GOVERNANCA: [Modulo.RESERVAS],
    Modulo.MANUTENCAO: [Modulo.RESERVAS],
    Modulo.LOJA: [Modulo.ESTOQUE],
    Modulo.RESTAURANTE: [Modulo.ESTOQUE],
    Modulo.LAVANDERIA: [Modulo.ESTOQUE],
    Modulo.FRIGOBAR: [Modulo.RESERVAS, Modulo.ESTOQUE],
    Modulo.APPSITE: [Modulo.RESERVAS, Modulo.PAGAMENTOS],
    Modulo.CRM_HOSPEDE: [Modulo.RESERVAS],
    Modulo.CANAIS: [Modulo.RESERVAS],
}

# Grupo do menu e ordem de exibição. O agrupamento reflete as áreas reais
# de operação da pousada (ver ESPECIFICACAO §3).
APRESENTACAO: dict[str, dict] = {
    Modulo.RESERVAS: {"grupo": "Hospedagem", "ordem": 10},
    Modulo.GOVERNANCA: {"grupo": "Hospedagem", "ordem": 20},
    Modulo.MANUTENCAO: {"grupo": "Hospedagem", "ordem": 30},
    Modulo.ESTOQUE: {"grupo": "Vendas & Estoque", "ordem": 40},
    Modulo.LOJA: {"grupo": "Vendas & Estoque", "ordem": 50},
    Modulo.RESTAURANTE: {"grupo": "Vendas & Estoque", "ordem": 60},
    Modulo.LAVANDERIA: {"grupo": "Vendas & Estoque", "ordem": 70},
    Modulo.FRIGOBAR: {"grupo": "Vendas & Estoque", "ordem": 80},
    Modulo.PAGAMENTOS: {"grupo": "Financeiro", "ordem": 90},
    Modulo.FISCAL: {"grupo": "Financeiro", "ordem": 100},
    Modulo.ESCALA: {"grupo": "Equipe", "ordem": 110},
    Modulo.APPSITE: {"grupo": "Online", "ordem": 120},
    Modulo.CRM_HOSPEDE: {"grupo": "Online", "ordem": 130},
    Modulo.CANAIS: {"grupo": "Online", "ordem": 140},
}

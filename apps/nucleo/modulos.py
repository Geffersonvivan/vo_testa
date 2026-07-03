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

# Ícone (emoji por enquanto) e ordem de exibição no menu lateral.
APRESENTACAO: dict[str, dict] = {
    Modulo.RESERVAS: {"icone": "🛏️", "ordem": 10},
    Modulo.GOVERNANCA: {"icone": "🧹", "ordem": 20},
    Modulo.MANUTENCAO: {"icone": "🔧", "ordem": 30},
    Modulo.ESCALA: {"icone": "📅", "ordem": 40},
    Modulo.ESTOQUE: {"icone": "📦", "ordem": 50},
    Modulo.LOJA: {"icone": "🛒", "ordem": 60},
    Modulo.RESTAURANTE: {"icone": "🍽️", "ordem": 70},
    Modulo.LAVANDERIA: {"icone": "🧺", "ordem": 80},
    Modulo.FRIGOBAR: {"icone": "🧊", "ordem": 90},
    Modulo.PAGAMENTOS: {"icone": "💳", "ordem": 100},
    Modulo.APPSITE: {"icone": "🌐", "ordem": 110},
    Modulo.CRM_HOSPEDE: {"icone": "⭐", "ordem": 120},
    Modulo.CANAIS: {"icone": "🔗", "ordem": 130},
    Modulo.FISCAL: {"icone": "🧾", "ordem": 140},
}

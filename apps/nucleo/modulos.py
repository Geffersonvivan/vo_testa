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
    AUDITORIA = "auditoria", "Auditoria"
    RELATORIOS = "relatorios", "Relatórios"
    COMERCIAL = "comercial", "Comercial"


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

# Grupo do menu, ordem de exibição e descrição curta (cards do dashboard).
# O agrupamento reflete as áreas reais de operação da pousada (ver ESPECIFICACAO §3).
APRESENTACAO: dict[str, dict] = {
    Modulo.RESERVAS: {
        "grupo": "Hospedagem",
        "ordem": 10,
        "descricao": "Disponibilidade, reservas e entrada/saída dos 24 quartos.",
        # Preenchida quando o módulo tem telas: menu e dashboard viram links.
        "url_name": "reservas:mapa",
    },
    Modulo.GOVERNANCA: {
        "grupo": "Hospedagem",
        "ordem": 20,
        "descricao": "Limpeza e arrumação, status quarto a quarto.",
        "url_name": "governanca:painel",
    },
    Modulo.MANUTENCAO: {
        "grupo": "Hospedagem",
        "ordem": 30,
        "descricao": "Chamados e ordens de serviço dos quartos e áreas comuns.",
        "url_name": "manutencao:painel",
    },
    Modulo.ESTOQUE: {
        "grupo": "Vendas & Estoque",
        "ordem": 40,
        "descricao": "Entradas, saídas e saldo de produtos por depósito.",
        "url_name": "estoque:posicao",
    },
    Modulo.LOJA: {
        "grupo": "Vendas & Estoque",
        "ordem": 50,
        "descricao": "Venda balcão e lançamento na conta do quarto.",
        "url_name": "loja:pdv",
    },
    Modulo.RESTAURANTE: {
        "grupo": "Vendas & Estoque",
        "ordem": 60,
        "descricao": "Comandas, consumo de hóspedes e venda avulsa.",
        "url_name": "restaurante:comandas",
    },
    Modulo.LAVANDERIA: {
        "grupo": "Vendas & Estoque",
        "ordem": 70,
        "descricao": "Rouparia interna e lavanderia para hóspedes.",
        "url_name": "lavanderia:painel",
    },
    Modulo.FRIGOBAR: {
        "grupo": "Vendas & Estoque",
        "ordem": 80,
        "descricao": "Consumo do frigobar lançado na conta do quarto.",
        "url_name": "frigobar:painel",
    },
    Modulo.PAGAMENTOS: {
        "grupo": "Financeiro",
        "ordem": 90,
        "descricao": "Cartão, Pix e boleto — cobranças e conciliação.",
        "url_name": "pagamentos:painel",
    },
    Modulo.FISCAL: {
        "grupo": "Financeiro",
        "ordem": 100,
        "descricao": "Emissão de notas — serviço e consumo separados.",
        "url_name": "fiscal:painel",
    },
    Modulo.ESCALA: {
        "grupo": "Equipe",
        "ordem": 110,
        "descricao": "Escala de trabalho e folgas da equipe.",
        "url_name": "escala:grade",
    },
    Modulo.COMERCIAL: {
        "grupo": "Comercial",
        "ordem": 115,
        "descricao": "Funil de vendas — leads, oportunidades e conversão em reserva.",
        "url_name": "comercial:funil",
    },
    Modulo.APPSITE: {
        "grupo": "Online",
        "ordem": 120,
        "descricao": "Motor de reservas e portal do hóspede no site.",
        "url_name": "portal:solicitacoes",
    },
    Modulo.CRM_HOSPEDE: {
        "grupo": "Online",
        "ordem": 130,
        "descricao": (
            "Histórico, preferências e relacionamento com hóspedes. "
            "NPS: proposta em /crm/nps/ e API stub /api/nps/v1/ (docs/Proposta_NPS.md)."
        ),
    },
    Modulo.CANAIS: {
        "grupo": "Online",
        "ordem": 140,
        "descricao": "Integração com Booking, Airbnb e outros canais.",
    },
    Modulo.AUDITORIA: {
        "grupo": "Gestão",
        "ordem": 150,
        "descricao": "Trilha de auditoria e varredura de pendências do CRM.",
        "url_name": "auditoria:painel",
    },
    Modulo.RELATORIOS: {
        "grupo": "Gestão",
        "ordem": 160,
        "descricao": "Relatórios por período — consolidados e por módulo.",
        "url_name": "relatorios:index",
    },
}

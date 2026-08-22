"""
Áreas-core concedíveis por usuário — o que NÃO é módulo contratável, mas ainda
precisa de controle de acesso por usuário (estrutura física, financeiro, etc.).

Espelha o papel do enum `Modulo`, mas para o núcleo. Concedidas em `Usuario.areas`
e checadas por `@requer_area(...)`. Superusuário acessa tudo.
"""
from django.db import models


class Area(models.TextChoices):
    QUARTOS = "quartos", "Quartos & tipos"
    TEMPORADAS = "temporadas", "Temporadas & tarifas"
    # Operar o PRÓPRIO caixa (abrir/receber/fechar a minha sessão) — ação de recepção.
    CAIXA = "caixa", "Caixa próprio (abrir/receber/fechar)"
    # Gestão financeira: contas a pagar/receber, lançamentos, sessões de todos, relatórios.
    FINANCEIRO = "financeiro", "Financeiro (contas/gestão)"
    PESSOAS = "pessoas", "Pessoas"
    LOGBOOK = "logbook", "Recados do turno"
    NPS = "nps", "NPS"
    EQUIPE = "equipe", "Equipe & Acessos"


def areas_catalogo() -> list[tuple[str, str]]:
    """(código, rótulo) de todas as áreas, para montar a tela de acessos."""
    return list(Area.choices)

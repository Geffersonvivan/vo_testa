"""Localização oficial (ala) dos 24 quartos da Pousada Vô Testa — regra fixa por número.

Descrição oficial:
  • Embaixo da Recepção  → quartos 01, 02
  • Corredor Engenhocas  → quartos 03 a 09
  • Corredor Histórias   → quartos 10 a 15
  • Condado dos Hobbits  → quartos 16 a 24

Fonte única da verdade — usada em todo o CRM (dropdown de cotação, mapa, listas…).
"""
import re

# (nome da ala, faixa de números) — na ordem oficial, de cima para baixo.
ALAS = [
    ("Embaixo da Recepção", range(1, 3)),      # 01-02
    ("Corredor Engenhocas", range(3, 10)),     # 03-09
    ("Corredor Histórias", range(10, 16)),     # 10-15
    ("Condado dos Hobbits", range(16, 25)),    # 16-24
]
ORDEM_ALAS = [nome for nome, _ in ALAS]


def _numero_int(numero):
    m = re.search(r"(\d+)", numero or "")
    return int(m.group(1)) if m else None


def ala_do_quarto(numero):
    """Ala oficial a partir do número do quarto ('Quarto 03' → 'Corredor Engenhocas').
    Retorna '' para números fora das 4 faixas. NÃO distingue day use — use por cima o
    `UH.ala`, que ignora day use (os DAY-0N parseariam para 1-8 por engano)."""
    n = _numero_int(numero)
    if n is None:
        return ""
    for nome, faixa in ALAS:
        if n in faixa:
            return nome
    return ""

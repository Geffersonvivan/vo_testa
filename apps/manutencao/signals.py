"""Sinais do módulo Manutenção.

`reparo_concluido` é emitido quando uma OS que bloqueou um quarto é concluída
— a Governança (se ativa) ouve e marca o quarto como "a limpar", sem que a
Manutenção precise conhecer a Governança (mesma inversão usada no check-out).
"""
from django.dispatch import Signal

# kwargs: uh, ordem, usuario
reparo_concluido = Signal()

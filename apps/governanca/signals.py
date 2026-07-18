"""Sinais emitidos pela Governança para outros módulos (ex.: Lavanderia)."""
from django.dispatch import Signal

# kwargs: uh, tarefa, usuario
faxina_concluida = Signal()

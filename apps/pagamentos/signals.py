"""Sinais do módulo Pagamentos — outros módulos escutam sem inverter dependência."""

import django.dispatch

# Emitido quando uma cobrança é confirmada como paga (webhook/simulado).
# kwargs: cobranca, usuario
pagamento_confirmado = django.dispatch.Signal()

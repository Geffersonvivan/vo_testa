"""
Controle de acesso por módulo.

Toda view de módulo usa @requer_modulo(Modulo.X):
- módulo não contratado/inativo → 404 (não existe para este cliente);
- usuário sem o módulo atribuído no Admin → 403.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import modulo_ativo


def eh_gerente(user) -> bool:
    """
    Ações sensíveis (estorno, reabertura de caixa, ajuste) exigem gerência.
    Até os perfis por módulo entrarem (ESPECIFICACAO §4.2), gerência = staff
    ou superusuário.
    """
    return user.is_authenticated and (user.is_superuser or user.is_staff)


def requer_gerencia(view):
    """403 para quem não é gerência. Usar em estorno, reabertura de caixa etc."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not eh_gerente(request.user):
            raise PermissionDenied("Esta ação exige permissão de gerência.")
        return view(request, *args, **kwargs)

    return wrapper


def requer_modulo(codigo: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not modulo_ativo(codigo):
                raise Http404("Módulo não contratado.")
            if not request.user.pode_acessar(codigo):
                raise PermissionDenied("Sem acesso a este módulo.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def requer_area(*codigos: str):
    """403 para quem não tem a área-core concedida (Quartos, Financeiro, Equipe…).
    Aceita várias áreas: passa quem tiver QUALQUER uma delas (ex.: telas de caixa =
    Caixa OU Financeiro). Superusuário passa. Ver apps/nucleo/areas.py e Equipe & Acessos."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not any(request.user.pode_area(c) for c in codigos):
                raise PermissionDenied("Sem acesso a esta área.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator

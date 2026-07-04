from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ModuloContratado
from .modulos import APRESENTACAO


@login_required
def dashboard(request):
    modulos = ModuloContratado.objects.filter(ativo=True)
    if not request.user.is_superuser:
        modulos = modulos.filter(usuarios=request.user)
    modulos = sorted(
        modulos, key=lambda m: APRESENTACAO.get(m.codigo, {}).get("ordem", 999)
    )
    return render(request, "nucleo/dashboard.html", {"modulos": modulos})

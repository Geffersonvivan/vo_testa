from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ModuloContratado


@login_required
def dashboard(request):
    modulos = ModuloContratado.objects.filter(ativo=True)
    return render(request, "nucleo/dashboard.html", {"modulos": modulos})

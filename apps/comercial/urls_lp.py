"""Rotas públicas da LP Fundador (fora do /crm)."""
from django.urls import path

from . import views_lp

app_name = "lp"

urlpatterns = [
    path("fundador/", views_lp.servir_lp_fundador, name="fundador"),
    path("fundador/lead/", views_lp.lp_fundador_lead, name="fundador_lead"),
]

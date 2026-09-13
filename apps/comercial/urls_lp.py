"""Rotas públicas da LP Fundador (fora do /crm)."""
from django.urls import path

from . import views_lp

app_name = "lp"

urlpatterns = [
    path("fundador/", views_lp.servir_lp_fundador, name="fundador"),
    path("fundador/lead/", views_lp.lp_fundador_lead, name="fundador_lead"),
    # Nova campanha (13/09/2026), em paralelo — não altera a LP acima.
    path("fundador-2/", views_lp.servir_lp_fundador_2, name="fundador_2"),
    path("fundador-2/lead/", views_lp.lp_fundador_2_lead, name="fundador_2_lead"),
]

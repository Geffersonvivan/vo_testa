"""Rotas PÚBLICAS de e-mail (fora do /crm/) — descadastro (LGPD).

Montadas na raiz em config/urls.py: /email/descadastrar/<token>/. Sem login.
"""
from django.urls import path

from . import views

app_name = "email_publico"

urlpatterns = [
    path("descadastrar/<uuid:token>/", views.descadastrar_email, name="descadastrar"),
]

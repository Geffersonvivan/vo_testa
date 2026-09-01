"""Rotas PÚBLICAS do Comercial (fora do /crm/) — Páginas de Captação.

Montadas na raiz em `config/urls.py`: /captacao/<slug>/. Sem login: é a página
que o interessado abre ao clicar no link da bio do Instagram.
"""
from django.urls import path

from . import views

app_name = "captacao"

urlpatterns = [
    path("<slug:slug>/", views.captacao_publica, name="publica"),
]

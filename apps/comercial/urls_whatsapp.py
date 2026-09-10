"""Rota pública do webhook do WhatsApp (fora do /crm). Montada em config/urls.py."""
from django.urls import path

from . import views_whatsapp

app_name = "whatsapp"

urlpatterns = [
    path("webhook/", views_whatsapp.webhook, name="webhook"),
]

from django.urls import path

from . import views

app_name = "fiscal"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("webhook/", views.webhook, name="webhook"),
    path("emitir-nfse/", views.emitir_nfse, name="emitir_nfse"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]

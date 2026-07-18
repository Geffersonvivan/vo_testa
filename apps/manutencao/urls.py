from django.urls import path

from . import views

app_name = "manutencao"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("nova/", views.nova, name="nova"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/iniciar/", views.iniciar, name="iniciar"),
    path("<int:pk>/concluir/", views.concluir, name="concluir"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]

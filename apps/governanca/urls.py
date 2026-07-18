from django.urls import path

from . import views

app_name = "governanca"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("faxina/nova/", views.nova_tarefa, name="nova_tarefa"),
    path("tarefa/<int:pk>/", views.tarefa_acao, name="tarefa_acao"),
    path("quarto/<int:pk>/status/", views.status_marcar, name="status_marcar"),
]

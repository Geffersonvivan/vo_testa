from django.urls import path

from . import views

app_name = "comercial"

urlpatterns = [
    path("", views.funil, name="funil"),
    path("instagram/", views.instagram, name="instagram"),
    path("painel/", views.painel, name="painel"),
    path("painel/meta/", views.meta, name="meta"),
    path("tarefas/", views.tarefas, name="tarefas"),
    path("nova/", views.nova, name="nova"),
    path("lead-novo/", views.lead_novo, name="lead_novo"),
    path("<int:pk>/", views.oportunidade, name="oportunidade"),
    path("<int:pk>/mover/", views.mover, name="mover"),
    path("<int:pk>/atividade/", views.atividade, name="atividade"),
    path("<int:pk>/cotar/", views.cotar, name="cotar"),
    path("<int:pk>/converter/", views.converter, name="converter"),
    path("<int:pk>/perder/", views.perder, name="perder"),
    path("tarefa/<int:pk>/concluir/", views.concluir_tarefa, name="concluir_tarefa"),
]

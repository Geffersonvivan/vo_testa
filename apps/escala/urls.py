from django.urls import path

from . import views

app_name = "escala"

urlpatterns = [
    path("", views.escala, name="grade"),
    path("atribuir/", views.atribuir, name="atribuir"),
    path("atribuicao/<int:pk>/remover/", views.remover_atribuicao, name="remover_atribuicao"),
    path("minha/", views.minha_escala, name="minha"),
    path("turnos/", views.turnos, name="turnos"),
    path("ausencias/", views.ausencias, name="ausencias"),
    path("trocas/", views.trocas, name="trocas"),
    path("trocas/<int:pk>/decidir/", views.decidir_troca, name="decidir_troca"),
]

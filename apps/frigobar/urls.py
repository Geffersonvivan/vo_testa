from django.urls import path

from . import views

app_name = "frigobar"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("conferir/", views.conferir, name="conferir"),
    path("composicoes/", views.composicoes, name="composicoes"),
    path("composicoes/<int:pk>/remover/", views.remover_composicao, name="remover_composicao"),
    path("<int:pk>/", views.conferencia, name="conferencia"),
    path("<int:pk>/repor/", views.repor, name="repor"),
]

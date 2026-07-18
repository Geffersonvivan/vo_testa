from django.urls import path

from . import views

app_name = "loja"

urlpatterns = [
    path("", views.pdv, name="pdv"),
    path("finalizar/", views.finalizar, name="finalizar"),
    path("vendas/", views.vendas, name="vendas"),
    path("vendas/<int:pk>/", views.venda, name="venda"),
    path("vendas/<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]

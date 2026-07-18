from django.urls import path

from . import views

app_name = "restaurante"

urlpatterns = [
    path("", views.comandas, name="comandas"),
    path("abrir/", views.abrir, name="abrir"),
    path("historico/", views.historico, name="historico"),
    path("mesas/", views.mesas, name="mesas"),
    path("<int:pk>/", views.comanda, name="comanda"),
    path("<int:pk>/item/", views.add_item, name="add_item"),
    path("<int:pk>/item/<int:item_pk>/remover/", views.remover_item, name="remover_item"),
    path("<int:pk>/fechar/", views.fechar, name="fechar"),
    path("<int:pk>/transferir/", views.transferir, name="transferir"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]

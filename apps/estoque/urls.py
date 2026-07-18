from django.urls import path

from . import views

app_name = "estoque"

urlpatterns = [
    path("", views.posicao, name="posicao"),
    path("produtos/", views.produtos, name="produtos"),
    path("produtos/novo/", views.produto_form, name="produto_novo"),
    path("produtos/<int:pk>/", views.produto_form, name="produto_editar"),
    path("produtos/<int:pk>/kardex/", views.kardex, name="kardex"),
    path("categorias/", views.categorias, name="categorias"),
    path("locais/", views.locais, name="locais"),
    path("entrada/", views.entrada, name="entrada"),
    path("saida/", views.saida, name="saida"),
    path("transferencia/", views.transferencia, name="transferencia"),
    path("ajuste/", views.ajuste, name="ajuste"),
    path("inventarios/", views.inventarios, name="inventarios"),
    path("inventarios/<int:pk>/", views.inventario, name="inventario"),
]

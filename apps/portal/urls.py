from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    # Recepção (staff)
    path("recepcao/<int:reserva_id>/qr/", views.qr, name="qr"),
    path("recepcao/solicitacoes/", views.solicitacoes, name="solicitacoes"),
    # Hóspede (público, por token)
    path("<uuid:token>/", views.home, name="home"),
    path("<uuid:token>/nps/", views.nps, name="nps"),
    path("<uuid:token>/pedir/", views.pedir, name="pedir"),
    path("<uuid:token>/solicitar/", views.solicitar, name="solicitar"),
    path("<uuid:token>/checkout/", views.checkout, name="checkout"),
    path("<uuid:token>/checkout/pagar/", views.pagar_saldo, name="pagar_saldo"),
    path("<uuid:token>/checkout/recepcao/", views.solicitar_checkout_recepcao, name="checkout_recepcao"),
]

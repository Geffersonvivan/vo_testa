from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("", views.mapa, name="mapa"),
    path("quartos/", views.mapa_quartos, name="mapa_quartos"),
    path("lista/", views.lista, name="lista"),
    path("nova/", views.nova, name="nova"),
    path("tarifa-preview/", views.tarifa_preview, name="tarifa_preview"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/confirmar/", views.confirmar, name="confirmar"),
    path("<int:pk>/checkin/", views.fazer_checkin, name="checkin"),
    path("<int:pk>/checkout/", views.fazer_checkout, name="checkout"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
    path("<int:pk>/trocar/", views.trocar_quarto, name="trocar_quarto"),
    path("<int:pk>/no-show/", views.no_show, name="no_show"),
    path("<int:pk>/lancamento/", views.lancamento_novo, name="lancamento_novo"),
    path("<int:pk>/pagamento/", views.pagamento_novo, name="pagamento_novo"),
    path("<int:pk>/adiantamento/", views.adiantamento_novo, name="adiantamento_novo"),
    path("<int:pk>/acompanhante/", views.acompanhante_novo, name="acompanhante_novo"),
]

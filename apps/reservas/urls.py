from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("", views.mapa, name="mapa"),
    path("quartos/", views.mapa_quartos, name="mapa_quartos"),
    path("lista/", views.lista, name="lista"),
    path("nova/", views.nova, name="nova"),
    path("tarifa-preview/", views.tarifa_preview, name="tarifa_preview"),
    # Reserva de grupo (reserva-mãe + filhas por quarto)
    path("grupos/", views.grupos, name="grupos"),
    path("grupos/novo/", views.grupo_novo, name="grupo_novo"),
    path("grupos/<int:pk>/", views.grupo_detalhe, name="grupo_detalhe"),
    path("grupos/<int:pk>/quarto/", views.grupo_adicionar_quarto, name="grupo_adicionar_quarto"),
    path("grupos/<int:pk>/confirmar/", views.grupo_confirmar, name="grupo_confirmar"),
    path("grupos/<int:pk>/checkin/", views.grupo_checkin, name="grupo_checkin"),
    path("grupos/<int:pk>/cancelar/", views.grupo_cancelar, name="grupo_cancelar"),
    path("grupos/<int:pk>/encerrar/", views.grupo_encerrar, name="grupo_encerrar"),
    path("grupos/<int:pk>/folio/", views.grupo_receber_folio, name="grupo_receber_folio"),
    path("grupos/<int:pk>/sinal/", views.grupo_sinal, name="grupo_sinal"),
    path("grupos/<int:pk>/remover/<int:reserva_pk>/", views.grupo_remover_quarto,
         name="grupo_remover_quarto"),
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
    path("<int:pk>/fnrh/", views.fnrh, name="fnrh"),
    path("<int:pk>/fnrh/reenviar/", views.fnrh_reenviar, name="fnrh_reenviar"),
    path("boh/", views.boh, name="boh"),
]

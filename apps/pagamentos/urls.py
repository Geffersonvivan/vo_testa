from django.urls import path

from . import views

app_name = "pagamentos"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("safrapay/", views.safrapay, name="safrapay"),
    path("safrapay/evidencias/", views.safrapay_evidencias, name="safrapay_evidencias"),
    path("criar/", views.criar, name="criar"),
    path("webhook/", views.webhook, name="webhook"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/simular/", views.simular, name="simular"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
    path("<int:pk>/estornar/", views.estornar, name="estornar"),
    # Link público de pagamento
    path("pagar/<uuid:token>/", views.pagar, name="pagar"),
    path("pagar/<uuid:token>/confirmar/", views.pagar_simular, name="pagar_simular"),
]

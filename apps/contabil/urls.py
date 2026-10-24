from django.urls import path

from . import views

app_name = "contabil"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("fechar/", views.fechar, name="fechar"),
    path("export/<slug:tipo>/", views.export, name="export"),
    path("cron/capturar/", views.cron_capturar, name="cron_capturar"),
]

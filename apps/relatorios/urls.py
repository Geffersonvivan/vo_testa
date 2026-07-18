from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:chave>/", views.relatorio, name="relatorio"),
]

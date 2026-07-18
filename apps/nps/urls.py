from django.urls import path

from . import views

app_name = "nps"

urlpatterns = [
    path("", views.painel, name="painel"),
]

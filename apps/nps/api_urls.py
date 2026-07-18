from django.urls import path

from . import views

app_name = "nps_api"

urlpatterns = [
    path("v1/respostas/", views.api_criar_resposta, name="criar_resposta"),
    path("v1/respostas/<int:reserva_id>/", views.api_resposta_reserva, name="resposta"),
    path("v1/resumo/", views.api_resumo, name="resumo"),
]

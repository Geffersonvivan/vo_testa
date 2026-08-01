from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('pedir-proposta/', views.pedir_proposta, name='pedir_proposta'),

    # Reservas — fluxo em passos
    path('reservar/', views.reservar, name='reservar'),                       # 1 datas / 2 quartos
    path('reservar/info/', views.info_datas, name='info_datas'),              # HTMX resumo de datas
    path('reservar/quarto/<int:quarto_id>/', views.selecionar_quarto, name='selecionar_quarto'),  # 3 dados
    path('reservar/resumo/', views.resumo_reserva, name='resumo_reserva'),    # 4 resumo
    path('reservar/finalizar/', views.finalizar_reserva, name='finalizar_reserva'),
    path('reserva/<uuid:token>/', views.reserva_confirmada, name='reserva_confirmada'),  # 5 confirmação
    path('minha-reserva/', views.minha_reserva, name='minha_reserva'),  # acesso do hóspede (sobrenome + código)
    path('minha-reserva/<uuid:token>/', views.minha_reserva_detalhe, name='minha_reserva_detalhe'),  # área do hóspede (dark)

    # Laboratório de inovação (oculto / não listado no menu)
    path('lab/', views.lab, name='lab'),
]

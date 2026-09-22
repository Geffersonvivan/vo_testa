from django.urls import path

from . import views

app_name = "conciliacao"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("importar-ofx/", views.importar_ofx, name="importar_ofx"),
    path("importar-cartao/", views.importar_cartao, name="importar_cartao"),
    path("conciliar/", views.conciliar, name="conciliar"),
    # conciliação manual
    path("manual/", views.manual, name="manual"),
    path("manual/casar-extrato/", views.casar_extrato, name="casar_extrato"),
    path("manual/ignorar-extrato/", views.ignorar_extrato, name="ignorar_extrato"),
    path("manual/desfazer-extrato/", views.desfazer_extrato, name="desfazer_extrato"),
    path("manual/casar-cartao/", views.casar_cartao, name="casar_cartao"),
    path("manual/sem-venda-cartao/", views.sem_venda_cartao, name="sem_venda_cartao"),
    path("manual/desfazer-cartao/", views.desfazer_cartao, name="desfazer_cartao"),
    # relatório de fechamento
    path("fechamento/", views.fechamento, name="fechamento"),
]

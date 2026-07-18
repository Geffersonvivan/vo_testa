from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("busca/", views.busca_global, name="busca_global"),
    path("configuracoes/modulos/", views.modulos_central, name="modulos_central"),
    # Cadastros
    path("pessoas/", views.pessoas, name="pessoas"),
    path("pessoas/nova/", views.pessoa_form, name="pessoa_nova"),
    path("pessoas/nova-rapida/", views.pessoa_nova_rapida, name="pessoa_nova_rapida"),
    path("pessoas/<int:pk>/", views.pessoa_form, name="pessoa_editar"),
    path("estrutura/", views.estrutura, name="estrutura"),
    path("estrutura/tipos/novo/", views.tipo_uh_form, name="tipo_uh_novo"),
    path("estrutura/tipos/<int:pk>/", views.tipo_uh_form, name="tipo_uh_editar"),
    path("estrutura/uhs/nova/", views.uh_form, name="uh_nova"),
    path("estrutura/uhs/<int:pk>/", views.uh_form, name="uh_editar"),
    path("temporadas/", views.temporadas, name="temporadas"),
    path("temporadas/nova/", views.temporada_form, name="temporada_nova"),
    path("temporadas/<int:pk>/", views.temporada_form, name="temporada_editar"),
    # Caixa
    path("caixa/", views.caixa, name="caixa"),
    path("caixa/abrir/", views.caixa_abrir, name="caixa_abrir"),
    path("caixa/movimento/", views.caixa_movimento, name="caixa_movimento"),
    path("caixa/fechar/", views.caixa_fechar, name="caixa_fechar"),
    path("caixa/sessoes/", views.caixa_sessoes, name="caixa_sessoes"),
    path("caixa/sessoes/<int:pk>/", views.caixa_sessao, name="caixa_sessao"),
    path("caixa/sessoes/<int:pk>/reabrir/", views.caixa_reabrir, name="caixa_reabrir"),
    path("caixa/movimentos/<int:movimento_pk>/estorno/", views.estorno, name="estorno"),
    # Financeiro
    path("financeiro/lancamentos/", views.lancamentos, name="lancamentos"),
    path("financeiro/lancamentos/novo/", views.lancamento_form, name="lancamento_novo"),
    path("financeiro/contas/", views.contas, name="contas"),
    path("financeiro/contas/nova/", views.conta_form, name="conta_nova"),
    path("financeiro/contas/<int:pk>/baixar/", views.conta_baixar, name="conta_baixar"),
    # Logbook
    path("logbook/", views.logbook, name="logbook"),
]

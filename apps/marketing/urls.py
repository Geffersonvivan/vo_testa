from django.urls import path

from . import views

app_name = "marketing"

urlpatterns = [
    path("", views.quadro, name="quadro"),
    path("verba/teto/", views.editar_teto, name="editar_teto"),
    path("campanha/nova/", views.nova_campanha, name="nova_campanha"),
    path("campanha/<int:pk>/", views.detalhe, name="detalhe"),
    path("campanha/<int:pk>/ficha/", views.ficha, name="ficha"),
    path("campanha/<int:pk>/fase/", views.mover_fase, name="mover_fase"),
    path("campanha/<int:pk>/avancar/", views.avancar_fase, name="avancar_fase"),
    path("campanha/<int:pk>/salvar/", views.salvar_campanha, name="salvar_campanha"),
    path("campanha/<int:pk>/check/<slug:chave>/", views.marcar_check, name="marcar_check"),
    path("campanha/<int:pk>/dispensar/<slug:chave>/", views.dispensar_check, name="dispensar_check"),
    path("campanha/<int:pk>/anexar/<slug:chave>/", views.anexar_item, name="anexar_item"),
    # Ficha (gaveta): etapas, envolvidos, canais e conversa
    path("campanha/<int:pk>/etapa/", views.adicionar_etapa, name="adicionar_etapa"),
    path("etapa/<int:pk>/alternar/", views.alternar_etapa, name="alternar_etapa"),
    path("etapa/<int:pk>/remover/", views.remover_etapa, name="remover_etapa"),
    path("campanha/<int:pk>/papel/", views.atribuir_papel, name="atribuir_papel"),
    path("campanha/<int:pk>/canal/", views.alternar_canal, name="alternar_canal"),
    path("campanha/<int:pk>/comentar/", views.comentar, name="comentar"),
    # Passo 5 — calendário + peças
    path("calendario/", views.calendario, name="calendario"),
    path("campanha/<int:pk>/peca/", views.adicionar_peca, name="adicionar_peca"),
    path("peca/<int:pk>/status/", views.marcar_peca, name="marcar_peca"),
    path("peca/<int:pk>/remover/", views.remover_peca, name="remover_peca"),
    # Passo 6 — relatório + gastos
    path("relatorio/", views.relatorio, name="relatorio"),
    path("campanha/<int:pk>/gasto/", views.lancar_gasto, name="lancar_gasto"),
    # Passo 9 — ocupação × campanha
    path("ocupacao/", views.ocupacao, name="ocupacao"),
    # Passo 10 — duplicar
    path("campanha/<int:pk>/duplicar/", views.duplicar, name="duplicar"),
]

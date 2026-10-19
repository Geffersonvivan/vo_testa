"""Seed da PaginaCaptacao da LP Inauguração (31/10/2026).

Idempotente e defensivo: cria a página só se o slug ainda não existir
(get_or_create). Não altera nenhum registro existente. Reverse é no-op — nunca
apaga conteúdo. Sem usuário para `criado_por` (FK obrigatória) → não cria (o
deploy segue). A LP em si é servida por views_lp; esta página só dá tracking de
visitas + link em Comercial → Páginas de Captação.
"""
from django.db import migrations
from django.utils import timezone

_SLUG = "inauguracao_31_10_2026"


def criar_pagina(apps, schema_editor):
    PaginaCaptacao = apps.get_model("comercial", "PaginaCaptacao")
    Usuario = apps.get_model("nucleo", "Usuario")

    if PaginaCaptacao.objects.filter(slug=_SLUG).exists():
        return  # já existe (ex.: criada na UI) — nada a fazer

    autor = (Usuario.objects.filter(is_superuser=True).first()
             or Usuario.objects.filter(is_staff=True).first()
             or Usuario.objects.first())
    if autor is None:
        return  # sem usuário para `criado_por` — não cria (deploy segue)

    PaginaCaptacao.objects.get_or_create(
        slug=_SLUG,
        defaults=dict(
            nome="Inauguração 31/10 (LP)",
            tema="fundador",
            status="publicada",
            criado_por=autor,
            selo_texto="Inauguração · 31 de Outubro",
            hero_titulo="A casa do Vô abre as portas — sábado, 31 de outubro.",
            hero_subtitulo="À beira do Lago de Itá, Santa Catarina. "
                           "Confirme sua presença na inauguração da Pousada Vô Testa.",
            publicada_em=timezone.now(),
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0029_mensagemwhatsapp_erro_detalhe"),
    ]

    operations = [
        migrations.RunPython(criar_pagina, migrations.RunPython.noop),
    ]

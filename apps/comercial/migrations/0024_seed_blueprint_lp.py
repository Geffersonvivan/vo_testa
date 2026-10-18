"""Seed da LP "Blueprint — A casa do Vô" em produção.

Idempotente e defensivo: cria a PaginaCaptacao só se o slug ainda não existir
(get_or_create). Não altera nenhum registro existente. Reverse é no-op — nunca
apaga conteúdo. Se não houver usuário para `criado_por` (FK obrigatória), apenas
não cria (não quebra o deploy).
"""
from django.db import migrations
from django.utils import timezone


def criar_pagina(apps, schema_editor):
    PaginaCaptacao = apps.get_model("comercial", "PaginaCaptacao")
    Usuario = apps.get_model("nucleo", "Usuario")

    if PaginaCaptacao.objects.filter(slug="a-casa-do-vo").exists():
        return  # já existe (ex.: criada na UI) — nada a fazer

    autor = (Usuario.objects.filter(is_superuser=True).first()
             or Usuario.objects.filter(is_staff=True).first()
             or Usuario.objects.first())
    if autor is None:
        return  # sem usuário para `criado_por` — não cria (deploy segue)

    PaginaCaptacao.objects.get_or_create(
        slug="a-casa-do-vo",
        defaults=dict(
            nome="A casa do Vô (Blueprint)",
            tema="blueprint",
            status="publicada",
            criado_por=autor,
            hero_titulo="A casa do Vô",
            hero_subtitulo="Nem resort, nem pousada. É a casa do Vô — em Itá, Santa Catarina.",
            publicada_em=timezone.now(),
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0023_alter_paginacaptacao_tema"),
    ]

    operations = [
        migrations.RunPython(criar_pagina, migrations.RunPython.noop),
    ]

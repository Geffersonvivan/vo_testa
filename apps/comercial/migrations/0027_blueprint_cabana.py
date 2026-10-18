"""Troca 'pousada' por 'cabana' no subtítulo (meta description) das LPs tema blueprint.
Defensivo: só altera páginas blueprint que ainda contêm o texto antigo; não toca em
outras páginas nem em leads. Reverse no-op.
"""
from django.db import migrations


def trocar(apps, schema_editor):
    PaginaCaptacao = apps.get_model("comercial", "PaginaCaptacao")
    for p in PaginaCaptacao.objects.filter(
            tema="blueprint", hero_subtitulo__icontains="pousada"):
        novo = p.hero_subtitulo.replace("nem pousada", "nem cabana").replace(
            "Nem pousada", "Nem cabana")
        if novo != p.hero_subtitulo:
            p.hero_subtitulo = novo
            p.save(update_fields=["hero_subtitulo"])


class Migration(migrations.Migration):

    dependencies = [
        ("comercial", "0026_cotacao_uh"),
    ]

    operations = [
        migrations.RunPython(trocar, migrations.RunPython.noop),
    ]

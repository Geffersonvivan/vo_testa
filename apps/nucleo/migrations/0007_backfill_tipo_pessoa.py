"""Preenche Pessoa.tipo nos cadastros já existentes: CNPJ ou fornecedor → PJ."""

import re

from django.db import migrations


def backfill_tipo(apps, schema_editor):
    Pessoa = apps.get_model("nucleo", "Pessoa")
    for pessoa in Pessoa.objects.all():
        digitos = re.sub(r"\D", "", pessoa.documento or "")
        eh_pj = (
            len(digitos) > 11  # CNPJ tem 14 dígitos
            or "/" in (pessoa.documento or "")
            or hasattr(pessoa, "fornecedor")
        )
        novo = "juridica" if eh_pj else "fisica"
        if pessoa.tipo != novo:
            pessoa.tipo = novo
            pessoa.save(update_fields=["tipo"])


class Migration(migrations.Migration):
    dependencies = [
        ("nucleo", "0006_pessoa_tipo_agencia"),
    ]

    operations = [
        migrations.RunPython(backfill_tipo, migrations.RunPython.noop),
    ]

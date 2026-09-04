"""Opt-in/descadastro de e-mail marketing na Pessoa (LGPD).

unsub_token é único → 3 passos: adiciona anulável, popula por linha, torna único.
"""
import uuid

from django.db import migrations, models


def _popular_tokens(apps, schema_editor):
    Pessoa = apps.get_model("nucleo", "Pessoa")
    for pk in Pessoa.objects.values_list("pk", flat=True).iterator():
        Pessoa.objects.filter(pk=pk).update(unsub_token=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0031_conceder_remuneracao_gerentes"),
    ]

    operations = [
        migrations.AddField(
            model_name="pessoa",
            name="aceita_email",
            field=models.BooleanField(default=True, verbose_name="aceita e-mails"),
        ),
        migrations.AddField(
            model_name="pessoa",
            name="email_optin_em",
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name="opt-in de e-mail em"),
        ),
        migrations.AddField(
            model_name="pessoa",
            name="email_descadastro_em",
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name="descadastro em"),
        ),
        # 1) anulável
        migrations.AddField(
            model_name="pessoa",
            name="unsub_token",
            field=models.UUIDField(null=True, editable=False,
                                   verbose_name="token de descadastro"),
        ),
        # 2) popula por linha
        migrations.RunPython(_popular_tokens, migrations.RunPython.noop),
        # 3) único + default
        migrations.AlterField(
            model_name="pessoa",
            name="unsub_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True,
                                   db_index=True, verbose_name="token de descadastro"),
        ),
    ]

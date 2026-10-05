from django.db import migrations, models


class Migration(migrations.Migration):
    """Campos de MFA (TOTP) no Usuario — Fase 4 de segurança.

    Depende de 0036 (último commitado). Convive em paralelo com a migração local
    de UH (Descritivo de Quartos, ainda WIP); quando esta subir, será rebaseada
    sobre esta (0038) e o merge local pode ser descartado.
    """

    dependencies = [
        ("nucleo", "0036_remover_modulo_frigobar"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="mfa_secret",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="segredo TOTP"),
        ),
        migrations.AddField(
            model_name="usuario",
            name="mfa_ativo",
            field=models.BooleanField(default=False, verbose_name="MFA ativo"),
        ),
        migrations.AddField(
            model_name="usuario",
            name="mfa_backup_codes",
            field=models.JSONField(blank=True, default=list, verbose_name="códigos de backup (hash)"),
        ),
    ]

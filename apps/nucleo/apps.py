from django.apps import AppConfig


class NucleoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.nucleo"
    label = "nucleo"
    verbose_name = "Núcleo"

    def ready(self):
        # Auditoria automática: liga os signals de escrita dos models de negócio.
        from .audit import conectar_auditoria_automatica

        conectar_auditoria_automatica()

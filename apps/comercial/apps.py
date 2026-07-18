from django.apps import AppConfig


class ComercialConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.comercial"
    label = "comercial"
    verbose_name = "Comercial"

    def ready(self):
        from . import receivers  # noqa: F401

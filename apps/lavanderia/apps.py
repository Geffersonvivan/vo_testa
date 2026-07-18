from django.apps import AppConfig


class LavanderiaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lavanderia"
    label = "lavanderia"
    verbose_name = "Lavanderia"

    def ready(self):
        from . import receivers  # noqa: F401  (ouve a faxina da Governança)

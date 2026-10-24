from django.apps import AppConfig


class ContabilConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contabil"
    verbose_name = "Contábil / Gerencial"

    def ready(self):
        from . import receivers  # noqa: F401  (carimbo de conta + de-para automático)

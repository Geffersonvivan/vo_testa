from django.apps import AppConfig


class GovernancaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.governanca"
    label = "governanca"
    verbose_name = "Governança"

    def ready(self):
        from . import receivers  # noqa: F401  (conecta os sinais de Reservas)

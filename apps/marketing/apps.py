from django.apps import AppConfig


class MarketingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.marketing"
    verbose_name = "Marketing (campanhas)"

    def ready(self):
        # Passo 7: atribui a campanha vigente ao lead recém-criado (ouve o comercial).
        from django.db.models.signals import post_save

        from apps.comercial.models import Oportunidade

        from .signals import atribuir_campanha_vigente
        post_save.connect(
            atribuir_campanha_vigente, sender=Oportunidade,
            dispatch_uid="marketing_atribuir_campanha_vigente")

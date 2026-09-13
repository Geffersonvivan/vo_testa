"""Organiza a nova campanha 'Fundador II' no CRM (idempotente).

Cria as três peças do Comercial para a LP nova (servida em /lp/fundador-2/):
  1. PaginaCaptacao slug='fundador-2'  — a LP (rastreia visitas/leads/conversão);
  2. o link público                    — /captacao/fundador-2/ → /lp/fundador-2/;
  3. Campanha codigo='fundador-2'       — impulsionamento (utm_campaign=fundador-2).

Uso: manage.py popular_campanha_fundador_2
Roda em paralelo à campanha 'fundador' original — não altera a LP no ar.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comercial.models import Campanha, Oportunidade, PaginaCaptacao

Usuario = get_user_model()

SLUG = "fundador-2"


class Command(BaseCommand):
    help = "Organiza a campanha 'Fundador II' no CRM (LP + link + campanha)."

    def handle(self, *args, **options):
        autor = (Usuario.objects.filter(is_superuser=True).order_by("id").first()
                 or Usuario.objects.filter(is_staff=True).order_by("id").first()
                 or Usuario.objects.order_by("id").first())
        if autor is None:
            self.stderr.write("Nenhum usuário no sistema — crie um antes de rodar.")
            return

        pagina = PaginaCaptacao.objects.filter(slug=SLUG).first()
        if pagina is None:
            pagina = PaginaCaptacao.objects.create(
                nome="Fundador II — 13/09/2026",
                slug=SLUG,
                status=PaginaCaptacao.Status.PUBLICADA,
                tema=PaginaCaptacao.Tema.FUNDADOR,
                tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM,
                hero_titulo="O Vô Testa está prestes a abrir as portas do fantástico mundo.",
                hero_subtitulo=(
                    "Antes de abrir ao público, um grupo pequeno de fundadores conhece "
                    "tudo primeiro — e garante a condição de inauguração."
                ),
                cta_texto="Quero minha condição de fundador",
                meta_leads=400,
                endereco="Pousada Vô Testa — Itá, Santa Catarina.",
                publicada_em=timezone.now(),
                criado_por=autor,
            )
            self.stdout.write(self.style.SUCCESS(
                f"LP '{SLUG}' criada e publicada (link: /captacao/{SLUG}/ → /lp/{SLUG}/)."))
        else:
            self.stdout.write(f"LP '{SLUG}' já existe — mantida.")

        camp = Campanha.objects.filter(codigo=SLUG).first()
        if camp is None:
            Campanha.objects.create(
                nome="Fundador II — 13/09/2026",
                codigo=SLUG,                          # casa com o utm_campaign do anúncio
                provedor=Campanha.Provedor.OUTRO,     # provedor a definir no CRM
                pagina_captacao=pagina,
                ativa=True,
                criado_por=autor,
            )
            self.stdout.write(self.style.SUCCESS(
                f"Campanha '{SLUG}' criada (utm_campaign=fundador-2, destino → a LP)."))
        else:
            self.stdout.write(f"Campanha '{SLUG}' já existe — mantida.")

        self.stdout.write(self.style.SUCCESS(
            "Pronto. LP servida em /lp/fundador-2/ — use ?utm_campaign=fundador-2 nos anúncios."))

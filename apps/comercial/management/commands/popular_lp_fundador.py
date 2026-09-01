"""Cria a Página de Captação 'Fundador' da inauguração (idempotente).

Uso: manage.py popular_lp_fundador
Cria se não existir (slug='fundador'), já publicada, com os textos aprovados.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comercial.models import Oportunidade, PaginaCaptacao

Usuario = get_user_model()

HISTORIA = (
    "O Vô Testa era um inventor. Numa época sem energia elétrica, com as próprias "
    "mãos construiu uma roda d'água para gerar a própria luz. Fazia engenhocas — e "
    "apreciava um bom vinho.\n\n"
    "Por isso a engrenagem no logo, a roda d'água em frente à recepção e a tela dele, "
    "no laboratório, no Corredor Vô Testa. Cada quarto carrega essa essência inventiva.\n\n"
    "O Dr. Flávio, o neto, ergueu esta pousada para trazer a você o jeito do avô de "
    "receber: engenhosidade, acolhimento e bom viver. Aqui, todo hóspede vira família."
)

FAQ = (
    "P: Está incluso café da manhã?\n"
    "R: Sim, café da manhã especial para todos os hóspedes.\n\n"
    "P: Vocês têm day use (dia na pousada)?\n"
    "R: Sim, com piscina e estrutura de lazer. Fale com a gente para valores.\n\n"
    "P: Onde fica a pousada?\n"
    "R: Em Itá, Santa Catarina. Veja no mapa como chegar.\n\n"
    "P: Como funciona o cancelamento no lançamento?\n"
    "R: Política flexível de inauguração — você reserva com tranquilidade."
)


class Command(BaseCommand):
    help = "Cria a Página de Captação 'Fundador' da inauguração (idempotente)."

    def handle(self, *args, **options):
        if PaginaCaptacao.objects.filter(slug="fundador").exists():
            self.stdout.write("Página 'fundador' já existe — nada a fazer.")
            return

        autor = (Usuario.objects.filter(is_superuser=True).order_by("id").first()
                 or Usuario.objects.filter(is_staff=True).order_by("id").first()
                 or Usuario.objects.order_by("id").first())
        if autor is None:
            self.stderr.write("Nenhum usuário no sistema — crie um antes de rodar.")
            return

        PaginaCaptacao.objects.create(
            nome="Inauguração — Fundador",
            slug="fundador",
            status=PaginaCaptacao.Status.PUBLICADA,
            tema=PaginaCaptacao.Tema.FUNDADOR,
            tipo_interesse=Oportunidade.TipoInteresse.HOSPEDAGEM,
            selo_texto="Inauguração · 31 de Outubro",
            tagline="a invenção que virou história.",
            hero_titulo="O Vô Testa recebia todo mundo. Agora o neto abre as portas para você.",
            hero_subtitulo=(
                "Uma pousada fora do tempo, em Itá, Santa Catarina, erguida para honrar "
                "o inventor que transformou engenhosidade em acolhimento. Seja um dos fundadores."
            ),
            historia_titulo="O Inventor que Moveu as Águas",
            historia_texto=HISTORIA,
            oferta_titulo="Tarifa de Fundador",
            oferta_texto=(
                "Ser fundador é dormir aqui antes de todo mundo — e pagar menos por isso. "
                "A tarifa sobe a cada faixa esgotada."
            ),
            cta_texto="Quero minha tarifa de fundador",
            vagas_restantes=6,
            data_evento=timezone.make_aware(timezone.datetime(2026, 10, 31, 18, 0)),
            meta_leads=400,
            whatsapp_destino="5549999990000",  # trocar pelo número real
            faq_texto=FAQ,
            endereco="Pousada Vô Testa — Itá, Santa Catarina.",
            publicada_em=timezone.now(),
            criado_por=autor,
        )
        self.stdout.write(self.style.SUCCESS(
            "Página 'fundador' criada e publicada em /captacao/fundador/"))

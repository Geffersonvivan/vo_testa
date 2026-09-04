"""Zera o funil comercial para começar a captação do zero.

Apaga oportunidades e toda a trilha (atividades, cotações, permanências, análises,
conversas de WhatsApp, envios de e-mail, conversões). PRESERVA a configuração:
etapas, motivos, páginas de captação, campanhas, templates, respostas rápidas, metas.
NÃO apaga Pessoas (contatos permanecem no cadastro).

Uso: manage.py zerar_funil --sim
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.comercial.models import (
    AnaliseLead,
    AtividadeComercial,
    ConversaoEnviada,
    ConversaWhatsApp,
    Cotacao,
    EnvioEmail,
    MensagemWhatsApp,
    Oportunidade,
    PermanenciaEtapa,
)


class Command(BaseCommand):
    help = "Apaga oportunidades e a trilha do funil (preserva config e Pessoas)."

    def add_arguments(self, parser):
        parser.add_argument("--sim", action="store_true",
                            help="Confirma a exclusão (sem isto, só mostra o que faria).")

    @transaction.atomic
    def handle(self, *args, **options):
        alvos = [
            ("mensagens de WhatsApp", MensagemWhatsApp.objects.all()),
            ("conversas de WhatsApp", ConversaWhatsApp.objects.all()),
            ("envios de e-mail", EnvioEmail.objects.all()),
            ("conversões enviadas", ConversaoEnviada.objects.all()),
            ("cotações", Cotacao.objects.all()),
            ("atividades", AtividadeComercial.objects.all()),
            ("permanências de etapa", PermanenciaEtapa.objects.all()),
            ("análises de lead", AnaliseLead.objects.all()),
            ("oportunidades", Oportunidade.objects.all()),
        ]
        self.stdout.write("Funil a zerar (config e Pessoas preservadas):")
        for rotulo, qs in alvos:
            self.stdout.write(f"  {qs.count():>5}  {rotulo}")

        if not options["sim"]:
            self.stdout.write(self.style.WARNING(
                "\nSimulação — nada foi apagado. Rode com --sim para confirmar."))
            return

        for rotulo, qs in alvos:
            n, _ = qs.delete()
            self.stdout.write(f"  apagado: {rotulo}")
        self.stdout.write(self.style.SUCCESS("\nFunil zerado. Pronto para captação."))

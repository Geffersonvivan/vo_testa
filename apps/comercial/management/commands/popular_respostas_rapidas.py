"""Cria respostas rápidas padrão (idempotente). Uso: manage.py popular_respostas_rapidas"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.comercial.models import RespostaRapida

Usuario = get_user_model()

PADRAO = [
    ("Confirmar disponibilidade",
     "Oi, {nome}! Para {checkin}→{checkout} ({noites} noite(s)), temos disponibilidade "
     "sim 🙌 Quer que eu segure um quarto para você?"),
    ("Enviar proposta + pagamento",
     "{nome}, o valor fica {valor}. Posso te mandar a proposta com o botão de pagar o "
     "sinal e já travar a data 😉"),
    ("Late checkout",
     "Conseguimos late checkout até as 14h, sujeito à disponibilidade no dia. Fechamos?"),
    ("Café da manhã",
     "Sim, o café da manhã está incluso para todos os hóspedes ☕"),
    ("Fechamento",
     "{nome}, para garantir a tarifa de fundador é só confirmar o sinal por aqui. "
     "Quer que eu envie o link de pagamento?"),
]


class Command(BaseCommand):
    help = "Cria respostas rápidas padrão (idempotente)."

    def handle(self, *args, **options):
        autor = (Usuario.objects.filter(is_superuser=True).order_by("id").first()
                 or Usuario.objects.order_by("id").first())
        if autor is None:
            self.stderr.write("Nenhum usuário no sistema.")
            return
        criadas = 0
        for i, (titulo, texto) in enumerate(PADRAO):
            _, novo = RespostaRapida.objects.get_or_create(
                titulo=titulo, defaults={"texto": texto, "ordem": i, "criado_por": autor})
            criadas += int(novo)
        self.stdout.write(self.style.SUCCESS(f"Respostas criadas: {criadas} (já existentes ignoradas)."))

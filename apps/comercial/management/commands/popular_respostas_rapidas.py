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
     "{nome}, para garantir a data é só confirmar o sinal por aqui. "
     "Quer que eu envie o link de pagamento?"),
    # ── respostas por objeção ─────────────────────────────────────────────
    ("Objeção: tá caro",
     "Entendo, {nome}! Dá pra deixar mais leve: à vista no Pix tem desconto, e no cartão "
     "a gente parcela. O valor já inclui o café da manhã pra todo mundo ☕ Quer que eu "
     "monte as duas opções pra você comparar?"),
    ("Objeção: posso parcelar?",
     "Pode sim! Parcelamos no cartão de crédito. À vista no Pix ainda sai com desconto. "
     "Quer que eu te mande o link já com as opções?"),
    ("Objeção: tem desconto?",
     "No Pix à vista já aplicamos um desconto 😉 Fora isso o valor de {valor} inclui café "
     "da manhã. Posso travar a data com o sinal e garantir essa condição?"),
    ("Objeção: aceita pet?",
     "Temos quartos que aceitam pet 🐾 (alguns não) — me conta o porte do seu que eu "
     "confirmo qual quarto é ideal e já reservo."),
    ("Política de cancelamento",
     "Pode reservar tranquilo, {nome}: até 7 dias após a confirmação você pode cancelar e "
     "a gente devolve 90% (retém só 10%). E, se precisar, antes dá pra remarcar a data "
     "sem custo 🙂"),
    ("Berço / cama extra",
     "Temos berço disponível (grátis) mediante reserva, e cama extra para alguns quartos. "
     "Me diz quantos adultos e crianças (e as idades) que eu confirmo a melhor montagem."),
    ("Horário de check-in/out",
     "Check-in a partir das 14h e check-out até as 12h. Chegando antes, guardamos sua "
     "bagagem numa boa 👜"),
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

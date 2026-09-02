"""Cria templates de e-mail padrão (idempotente). Uso: manage.py popular_templates_email"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.comercial.models import TemplateEmail

Usuario = get_user_model()

PADRAO = [
    (
        "Proposta (padrão)",
        "Sua estadia na Pousada Vô Testa — {quarto}",
        "Oi, {primeiro_nome}! Como combinamos, deixei tudo por escrito abaixo.\n\n"
        "Qualquer ajuste de datas ou de quarto, é só responder este e-mail — "
        "vai ser um prazer receber você.",
    ),
    (
        "Follow-up — ainda dá tempo",
        "Ainda dá tempo de garantir {quarto} ({checkin}→{checkout})",
        "Oi, {primeiro_nome}! Passando pra saber se você ainda tem interesse na "
        "{quarto} para {checkin}→{checkout}.\n\n"
        "A tarifa e a disponibilidade seguem de pé por enquanto — se quiser, eu já "
        "seguro a data pra você. É só responder por aqui.",
    ),
    (
        "Pós-cotação — resumo e sinal",
        "Sua proposta — {quarto} ({total})",
        "Oi, {primeiro_nome}! Segue o resumo da nossa conversa com os valores "
        "combinados para {noites} noite(s), {pessoas} pessoa(s).\n\n"
        "Para garantir a data, é só pagar o sinal no botão abaixo — o restante você "
        "acerta na chegada. Qualquer dúvida, me chama.",
    ),
]


class Command(BaseCommand):
    help = "Cria templates de e-mail padrão (idempotente)."

    def handle(self, *args, **options):
        autor = (Usuario.objects.filter(is_superuser=True).order_by("id").first()
                 or Usuario.objects.order_by("id").first())
        if autor is None:
            self.stderr.write("Nenhum usuário no sistema — crie um antes de rodar.")
            return
        criados = 0
        for nome, assunto, corpo in PADRAO:
            _, novo = TemplateEmail.objects.get_or_create(
                nome=nome, defaults={"assunto": assunto, "corpo": corpo,
                                     "criado_por": autor})
            criados += int(novo)
        self.stdout.write(self.style.SUCCESS(
            f"Templates de e-mail: {criados} criado(s), "
            f"{TemplateEmail.objects.count()} no total."))

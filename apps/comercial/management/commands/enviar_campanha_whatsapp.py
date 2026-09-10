"""Dispara um template de WhatsApp para uma lista de leads (best-effort, com pausa).

Exemplos:
  # todos os leads abertos com opt-in, template de boas-vindas
  manage.py enviar_campanha_whatsapp --template boas_vindas_fundador

  # só os leads de uma página de captação, limitando a 50 e 2s entre envios
  manage.py enviar_campanha_whatsapp --template boas_vindas_fundador \
      --slug fundador --limite 50 --pausa 2

Respeita opt-in (pessoa.aceita_email) e pula quem não tem telefone. No modo
WHATSAPP_GATEWAY=simulado nada é enviado de verdade (só registra a mensagem).
"""
import time

from django.core.management.base import BaseCommand

from apps.comercial import services
from apps.comercial.models import Oportunidade


class Command(BaseCommand):
    help = "Dispara um template de WhatsApp para uma lista de leads."

    def add_arguments(self, parser):
        parser.add_argument("--template", required=True, help="Nome do template aprovado.")
        parser.add_argument("--idioma", default="pt_BR")
        parser.add_argument("--slug", default="", help="Filtra por slug da página de captação.")
        parser.add_argument("--limite", type=int, default=0, help="Máximo de envios (0 = sem limite).")
        parser.add_argument("--pausa", type=float, default=1.0, help="Segundos entre envios.")
        parser.add_argument("--dry-run", action="store_true", help="Só conta, não envia.")

    def handle(self, *args, **opts):
        qs = Oportunidade.objects.filter(
            status=Oportunidade.Status.ABERTA).select_related("pessoa")
        if opts["slug"]:
            qs = qs.filter(pagina_captacao__slug=opts["slug"])

        elegiveis = [o for o in qs if (o.pessoa.telefone or "").strip() and o.pessoa.aceita_whatsapp]
        self.stdout.write(f"Leads elegíveis (telefone + opt-in): {len(elegiveis)}")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("dry-run: nada enviado."))
            return

        enviados = erros = 0
        limite = opts["limite"] or None
        for op in elegiveis:
            variaveis = [(op.pessoa.nome or "").split()[0]]
            msg = services.enviar_template_whatsapp(
                oportunidade=op, template=opts["template"],
                idioma=opts["idioma"], variaveis=variaveis)
            if msg.status == "enviada":
                enviados += 1
            else:
                erros += 1
                self.stdout.write(self.style.ERROR(f"  erro → {op.pessoa.nome}"))
            if limite and enviados >= limite:
                break
            if opts["pausa"]:
                time.sleep(opts["pausa"])

        self.stdout.write(self.style.SUCCESS(
            f"Concluído: {enviados} enviados, {erros} erros."))

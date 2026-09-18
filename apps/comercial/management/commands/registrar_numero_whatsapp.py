"""Registra o número na WhatsApp Cloud API (endpoint /register), definindo o PIN.

Lê WHATSAPP_CLOUD_TOKEN + WHATSAPP_CLOUD_PHONE_ID + WHATSAPP_API_VERSION das settings
(variáveis do ambiente) — o token NUNCA precisa ser digitado na linha de comando. Tira o
número do estado "Pendente" para "Conectado", habilitando envio/recebimento.

Uso (em produção, via Railway):
    railway ssh "python manage.py registrar_numero_whatsapp --pin 123456"

O PIN é a verificação em duas etapas (6 dígitos) do número. Guarde-o — é pedido de novo
em re-registros/migrações. Idempotente: se já registrado com o mesmo PIN, a Meta responde ok.
"""
import json
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Registra o número na WhatsApp Cloud API (/register) definindo o PIN de 6 dígitos."

    def add_arguments(self, parser):
        parser.add_argument("--pin", required=True,
                            help="PIN de 6 dígitos (verificação em duas etapas do número).")

    def handle(self, *args, **options):
        pin = (options["pin"] or "").strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise CommandError("O PIN deve ter exatamente 6 dígitos.")

        token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
        phone_id = getattr(settings, "WHATSAPP_CLOUD_PHONE_ID", "")
        versao = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
        if not (token and phone_id):
            raise CommandError(
                "Configure WHATSAPP_CLOUD_TOKEN e WHATSAPP_CLOUD_PHONE_ID no ambiente antes.")

        url = f"https://graph.facebook.com/{versao}/{phone_id}/register"
        data = json.dumps({"messaging_product": "whatsapp", "pin": pin}).encode("utf-8")
        req = urlrequest.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"})
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                corpo = json.loads(resp.read().decode("utf-8", "replace"))
            if corpo.get("success"):
                self.stdout.write(self.style.SUCCESS(
                    f"Número {phone_id} registrado com sucesso (PIN definido)."))
            else:
                self.stdout.write(self.style.WARNING(f"Resposta inesperada: {corpo}"))
        except urlerror.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:500]
            raise CommandError(f"Falha no registro — HTTP {e.code}: {corpo}")
        except Exception as e:  # noqa: BLE001
            raise CommandError(f"Erro ao chamar a API: {e}")

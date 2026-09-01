"""Reprocessa conversões de mídia pendentes (Fase B) — cron/backstop.

Uso: manage.py enviar_conversoes_pendentes
Para cada lead COM identificador de clique (fbclid/gclid) que ainda não teve a
conversão enviada com sucesso, tenta enviar de novo (best-effort, idempotente):
- Compra: leads ganhos (com reserva) sem conversão 'compra' enviada.
- Lead: leads com clique rastreado sem conversão 'lead' enviada.
"""
from django.core.management.base import BaseCommand

from apps.comercial import services
from apps.comercial.models import ConversaoEnviada, Oportunidade


class Command(BaseCommand):
    help = "Reenvia conversões de mídia pendentes (leads/compras com clique rastreado)."

    def handle(self, *args, **options):
        enviadas = 0
        base = Oportunidade.objects.exclude(origem_rastreio={})
        for op in base.iterator():
            rastreio = op.origem_rastreio or {}
            if not (rastreio.get("fbclid") or rastreio.get("gclid")):
                continue
            if op.status == Oportunidade.Status.GANHA:
                evento, valor = "compra", op.valor_estimado
            else:
                evento, valor = "lead", None
            ja = ConversaoEnviada.objects.filter(
                oportunidade=op, evento=evento,
                status=ConversaoEnviada.Status.ENVIADA).exists()
            if ja:
                continue
            ce = services.enviar_conversao(op, evento, valor=valor)
            if ce and ce.status == ConversaoEnviada.Status.ENVIADA:
                enviadas += 1
        self.stdout.write(self.style.SUCCESS(f"Conversões enviadas: {enviadas}"))

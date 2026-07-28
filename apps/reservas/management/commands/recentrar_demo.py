"""
Recentra as reservas de demonstração em torno de HOJE.

Os seeds (`popular_demo`, `popular_lotacao`) criam datas relativas a `hoje`.
Quando o relógio avança, essas datas vencem: o hóspede fica "hospedada" com
check-out no passado, aparece no mapa de quartos (por status) mas some do mapa
de reservas (por data). Este comando desloca cada reserva de demo pelo mesmo
número de dias que passou desde que ela foi criada — não apaga nada, preserva
conta/consumo/caixa e respeita o antioverbooking (salva uma a uma).

Uso:  .venv/bin/python manage.py recentrar_demo
      .venv/bin/python manage.py recentrar_demo --todas   # inclui não-ativas
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.reservas.models import Reserva

TAGS = Q(observacoes__icontains="[demo]") | Q(observacoes__icontains="[lotacao]")


class Command(BaseCommand):
    help = "Recentra as reservas de demonstração em torno de hoje (corrige datas vencidas do seed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--todas", action="store_true",
            help="Recentra também reservas não-ativas (checkout, cancelada, no-show, orçamento).",
        )

    def handle(self, *args, **opts):
        hoje = timezone.localdate()
        qs = Reserva.objects.filter(TAGS).select_related("uh")
        if not opts["todas"]:
            qs = qs.filter(status__in=Reserva.STATUS_ATIVOS)

        movidas = puladas = iguais = 0
        # Da mais nova para a mais antiga: reduz a chance de colisão transitória
        # com o antioverbooking ao empurrar as datas para frente.
        for r in qs.order_by("-checkin", "-pk"):
            delta = hoje - timezone.localtime(r.criado_em).date()
            if delta.days == 0:
                iguais += 1
                continue
            try:
                with transaction.atomic():
                    r.checkin = r.checkin + delta
                    r.checkout = r.checkout + delta
                    campos = ["checkin", "checkout"]
                    if r.expira_em:
                        r.expira_em = r.expira_em + delta
                        campos.append("expira_em")
                    r.save(update_fields=campos)
                movidas += 1
            except Exception as e:  # conflito de antioverbooking, etc.
                puladas += 1
                self.stderr.write(f"  pulou {r.uh} #{r.pk}: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Recentradas {movidas} reserva(s) em torno de {hoje:%d/%m/%Y}. "
            f"Já em dia: {iguais}. Puladas (conflito): {puladas}."
        ))

"""
Popula a Escala: turnos por setor, escala da semana atual para os funcionários,
uma ausência e uma solicitação de troca. Uso: manage.py popular_escala [--limpar]
"""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.escala import services
from apps.escala.models import Atribuicao, Ausencia, TrocaTurno, Turno
from apps.nucleo.models import Funcionario

Usuario = get_user_model()

TURNOS = [
    ("Manhã", "recepcao", time(7, 0), time(15, 0)),
    ("Tarde", "recepcao", time(15, 0), time(23, 0)),
    ("Diária", "governanca", time(8, 0), time(16, 0)),
    ("Cozinha", "cozinha", time(10, 0), time(22, 0)),
]


class Command(BaseCommand):
    help = "Cria dados de exemplo para a Escala."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true")

    def handle(self, *args, **opts):
        op = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        funcs = list(Funcionario.objects.select_related("pessoa"))
        if not funcs:
            self.stderr.write("Sem funcionários cadastrados — rode o seed de pessoas.")
            return

        if opts["limpar"]:
            Atribuicao.objects.all().delete()
            Ausencia.objects.all().delete()
            TrocaTurno.objects.all().delete()

        turnos = []
        for nome, setor, ini, fim in TURNOS:
            t, _ = Turno.objects.get_or_create(
                nome=nome, setor=setor, defaults={"inicio": ini, "fim": fim}
            )
            turnos.append(t)

        inicio = services.inicio_da_semana()
        # Escala de seg a sex, revezando funcionários pelos turnos.
        n = 0
        for d in range(5):
            data = inicio + timedelta(days=d)
            for i, t in enumerate(turnos):
                func = funcs[(d + i) % len(funcs)]
                if not services.ausencia_no_dia(func, data):
                    try:
                        services.atribuir(t, func, data, op)
                        n += 1
                    except Exception:
                        pass

        # Uma ausência (folga) e uma troca pendente de exemplo.
        if len(funcs) >= 2:
            services.registrar_ausencia(
                funcs[0], "folga", inicio + timedelta(days=6),
                inicio + timedelta(days=6), op, "Folga combinada",
            )
            atrib = Atribuicao.objects.filter(funcionario=funcs[1]).first()
            if atrib:
                try:
                    services.solicitar_troca(atrib, funcs[2 % len(funcs)], "Consulta médica")
                except Exception:
                    pass

        self.stdout.write(self.style.SUCCESS(
            f"Escala: {Turno.objects.count()} turnos, {n} atribuições na semana, "
            f"{Ausencia.objects.count()} ausência(s), {TrocaTurno.objects.count()} troca(s)."
        ))

"""
Popula a Escala e demonstra o gerador automático: turnos com cobertura mínima,
funcionários por setor/sexo, e a semana gerada pelas regras (domingo por sexo,
interjornada 11h, DSR). Uso: manage.py popular_escala [--limpar]
"""
from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.escala import services
from apps.escala.models import Atribuicao, Ausencia, TrocaTurno, Turno
from apps.nucleo.models import Funcionario

Usuario = get_user_model()

# (nome, setor, início, fim, cobertura mínima)
TURNOS = [
    ("Manhã", "recepcao", time(7, 0), time(15, 0), 1),
    ("Tarde", "recepcao", time(14, 30), time(22, 0), 1),
    ("Diurno", "governanca", time(7, 30), time(15, 30), 2),
]


class Command(BaseCommand):
    help = "Cria dados de exemplo para a Escala e roda o gerador automático."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true")

    def handle(self, *args, **opts):
        op = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        funcs = list(Funcionario.objects.select_related("pessoa").order_by("pk"))
        if len(funcs) < 6:
            self.stderr.write("Precisa de ≥6 funcionários (3 recepção + 3 camareiras).")
            return

        if opts["limpar"]:
            Atribuicao.objects.all().delete()
            Ausencia.objects.all().delete()
            TrocaTurno.objects.all().delete()
            Turno.objects.all().delete()   # recria só os turnos do plano abaixo

        # Turnos com cobertura mínima (atualiza horários se já existirem).
        for nome, setor, ini, fim, minp in TURNOS:
            Turno.objects.update_or_create(
                nome=nome, setor=setor,
                defaults={"inicio": ini, "fim": fim, "min_pessoas": minp, "ativo": True},
            )

        # 3 recepcionistas (mix de sexo) + 3 camareiras (♀) — setor/sexo para o
        # gerador casar e aplicar a regra de domingo.
        for f, sx in zip(funcs[:3], ["F", "M", "F"]):
            f.setor, f.sexo = "Recepção", sx
            f.save(update_fields=["setor", "sexo"])
        for f in funcs[3:6]:
            f.setor, f.sexo = "Governança", "F"
            f.save(update_fields=["setor", "sexo"])

        inicio = services.inicio_da_semana()
        n = services.gerar_semana(inicio, op)

        # Uma troca pendente de exemplo.
        atrib = Atribuicao.objects.filter(funcionario=funcs[1]).first()
        if atrib:
            try:
                services.solicitar_troca(atrib, funcs[0], "Consulta médica")
            except Exception:
                pass

        alertas = services.validar_semana(inicio)
        self.stdout.write(self.style.SUCCESS(
            f"Escala: {Turno.objects.count()} turnos, {n} atribuições geradas, "
            f"{len(alertas)} item(ns) de validação."
        ))

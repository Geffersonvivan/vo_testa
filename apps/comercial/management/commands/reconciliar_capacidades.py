"""Reconcilia a capacidade das UHs com o descritivo (decisões do dono, 30/09/2026).

Ajusta os colchões extras de `ConfiguracaoUH` para bater com o descritivo:
- 01, 02 (Intermediário 2 quartos): 0 colchão extra → máx 5 adultos («não cabe»)
- 22, 23, 24 (Cabana Hobbit): 1 colchão extra → máx 6 adultos
- 03-08, 10-14 (Padrão): 0 colchão extra → máx 2 adultos (o «a conferir» do descritivo)

TRAVA: nunca reduz abaixo de uma reserva ativa. Se alguma reserva do quarto tem
mais gente que o novo teto, aquele quarto é PULADO e avisado — nada de invalidar
reserva existente. Idempotente.
"""
from django.core.management.base import BaseCommand

from apps.nucleo import estrutura
from apps.nucleo.models import UH

# número da UH → colchões extras alvo
ALVO = {}
for n in ["01", "02"]:
    ALVO[f"Quarto {n}"] = 0
for n in ["22", "23", "24"]:
    ALVO[f"Quarto {n}"] = 1
for n in ["03", "04", "05", "06", "07", "08", "10", "11", "12", "13", "14"]:
    ALVO[f"Quarto {n}"] = 0

ATIVOS = ["pre_reserva", "confirmada", "hospedada"]


def _cap_com_extras(uh, extras):
    """maxima/maxima_criancas que o quarto teria com N colchões extras."""
    cfg = getattr(uh, "config", None)
    fixa = uh.posicoes_cama.count() * 2
    sofa_a = cfg.sofa_adultos if (cfg and cfg.tem_sofa_cama) else 0
    sofa_c = cfg.sofa_criancas if (cfg and cfg.tem_sofa_cama) else 0
    return fixa + sofa_a + extras, fixa + max(sofa_a, sofa_c) + extras


class Command(BaseCommand):
    help = "Ajusta colchões extras das UHs conforme o descritivo (com trava de reservas)."

    def add_arguments(self, parser):
        parser.add_argument("--forcar", action="store_true",
                            help="Aplica mesmo se houver reserva acima do novo teto (NÃO recomendado).")

    def handle(self, *args, **opts):
        from apps.reservas.models import Reserva

        aplicados = pulados = 0
        for numero, extras_alvo in sorted(ALVO.items()):
            uh = UH.objects.filter(numero=numero).select_related("config").first()
            if not uh:
                self.stdout.write(self.style.NOTICE(f"  · {numero}: UH não existe — pulado"))
                continue
            cfg = getattr(uh, "config", None)
            if not cfg:
                self.stdout.write(self.style.NOTICE(f"  · {numero}: sem ConfiguracaoUH — pulado"))
                continue

            novo_maxa, novo_maxc = _cap_com_extras(uh, extras_alvo)
            # trava: nenhuma reserva ativa pode ficar acima do novo teto
            conflitos = []
            for r in Reserva.objects.filter(uh=uh, status__in=ATIVOS):
                a = r.adultos or 0
                c = r.criancas or 0
                if a > novo_maxa or (a + c) > novo_maxc:
                    conflitos.append(f"#{r.pk}({a}ad+{c}cr)")
            if conflitos and not opts["forcar"]:
                pulados += 1
                self.stdout.write(self.style.ERROR(
                    f"  ✗ {numero}: PULADO — reserva(s) acima do novo teto "
                    f"(maxA {novo_maxa}): {', '.join(conflitos)}"))
                continue

            if cfg.max_colchoes_extras == extras_alvo:
                self.stdout.write(f"  = {numero}: já está com {extras_alvo} colchão(ões).")
                continue
            antigo = cfg.max_colchoes_extras
            cfg.max_colchoes_extras = extras_alvo
            cfg.save(update_fields=["max_colchoes_extras"])
            aplicados += 1
            cap = estrutura.capacidade(uh)
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {numero}: colchões {antigo}→{extras_alvo} · "
                f"máx {cap['maxima']} ad / {cap['maxima_criancas']} c/crianças"))

        self.stdout.write(self.style.SUCCESS(
            f"\nReconciliação: {aplicados} ajustados, {pulados} pulados por trava."))

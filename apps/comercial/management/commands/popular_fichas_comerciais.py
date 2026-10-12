"""Popular as fichas comerciais dos quartos a partir do descritivo (29/09/2026).

Seeda SÓ o que o descritivo afirma: resumo de venda, indicado para e os pontos
de atenção declarados (colchão apertado no 01/02, sem fogão no 03-15). Vista,
metragem, banheiro, acessibilidade e área externa continuam "a levantar" — não
entram em `confirmados` até serem conferidos de verdade.

Idempotente: rerodar atualiza (não duplica). `--limpar` zera antes.
"""
from django.core.management.base import BaseCommand

from apps.comercial.models import FichaComercial
from apps.nucleo.models import UH

RESUMO_PADRAO = "Quarto de casal aconchegante, com cozinha (sem fogão)."
RESUMO_INTER_1 = "Ambiente único com cama de casal e sofá-cama, com cozinha (sem fogão)."
RESUMO_INTER_2 = "Dois quartos de casal e cozinha — espaço para dois casais ou família."
RESUMO_CABANA = "Cabana com dois quartos de casal e cozinha completa."
RESUMO_HOBBIT = "Cabana estilo hobbit com dois quartos de casal e cozinha completa."

# número da UH → (resumo, indicado_para, [pontos_atencao])
FICHAS = {}
# "Sem fogão" fica no RESUMO (spec do quarto), não como ponto de atenção — senão
# inundaria a caixa do topo (13 quartos). Atenção = só o que evita reclamação.
for n in ["03", "04", "05", "06", "07", "08", "10", "11", "12", "13", "14"]:
    FICHAS[f"Quarto {n}"] = (RESUMO_PADRAO, "Casal", [])
for n in ["09", "15"]:
    FICHAS[f"Quarto {n}"] = (
        RESUMO_INTER_1, "Casal com filhos, ou pequeno grupo de amigos", [])
for n in ["01", "02"]:
    # Colchão/arranjo agora é calculado pelo modelo de colchões (pool por noite) e
    # aparece no painel do lead — não é mais um ponto de atenção manual.
    FICHAS[f"Quarto {n}"] = (
        RESUMO_INTER_2, "Dois casais, ou família com crianças", [])
for n in ["16", "17", "18", "19", "20", "21"]:
    FICHAS[f"Quarto {n}"] = (
        RESUMO_CABANA, "Famílias, grupos de amigos, dois ou três casais", [])
for n in ["22", "23", "24"]:
    FICHAS[f"Quarto {n}"] = (
        RESUMO_HOBBIT, "Famílias, grupos de amigos, dois casais", [])


class Command(BaseCommand):
    help = "Popula FichaComercial dos quartos a partir do descritivo."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true",
                            help="Apaga as fichas comerciais antes de recriar.")

    def handle(self, *args, **opts):
        if opts["limpar"]:
            n = FichaComercial.objects.count()
            FichaComercial.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"{n} fichas apagadas."))

        criadas = atualizadas = ignoradas = 0
        for numero, (resumo, indicado, pontos) in FICHAS.items():
            uh = UH.objects.filter(numero=numero).first()
            if not uh:
                ignoradas += 1
                self.stdout.write(self.style.NOTICE(f"  · {numero}: UH não existe — pulado"))
                continue
            _, criado = FichaComercial.objects.update_or_create(
                uh=uh,
                defaults={
                    "resumo": resumo,
                    "indicado_para": indicado,
                    "pontos_atencao": pontos,
                    # confirmados fica vazio de propósito: os detalhes ainda são
                    # "a levantar" no descritivo.
                    "confirmados": [],
                },
            )
            criadas += criado
            atualizadas += (not criado)

        self.stdout.write(self.style.SUCCESS(
            f"OK — {criadas} criadas, {atualizadas} atualizadas, {ignoradas} sem UH."))

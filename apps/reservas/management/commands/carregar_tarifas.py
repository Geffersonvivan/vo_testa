"""Carrega a tabela de tarifas aprovada (ago/2026) nos 24 quartos.

Escada de temporada: Baixa (base) → Média (+25%) → Alta (+45%) → Feriado (+80%),
arredondada à dezena. Justificativa e pesquisa em `docs/Precificação/`.
Idempotente: pode rodar quantas vezes precisar (update_or_create).

Preço por QUARTO (não só por categoria), porque há diferenciais dentro da categoria:
- Intermediário 01/02 (dois ambientes, sofá-cama, lavabo) > 09/15.
- Cabana 16/17/18 (varanda, pé-direito alto) > 19/20/21.
Ver a matriz de diferenciais no estudo.

Detalhe do motor: quartos "duplos" (mais de uma posição de cama) recebem o fator
`ACRESCIMO_TARIFA_DUPLO` (×1,6) quando não têm preço próprio. Como as categorias já
embutem o tamanho, fixamos o preço por quarto nesses duplos — `tarifa_override` cobre
a baixa (fora de temporada) e `TarifaUnidade` cobre média/alta/feriado.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.nucleo.estrutura import eh_duplo
from apps.nucleo.models import TipoUH
from apps.reservas.models import Tarifa, TarifaUnidade

# perfis de preço (reais): baixa, média (+25%), alta (+45%), feriado (+80%)
PERFIS = {
    "padrao": {"baixa": 250, "media": 310, "alta": 360, "feriado": 450},
    "interm": {"baixa": 350, "media": 440, "alta": 510, "feriado": 630},
    "interm_plus": {"baixa": 400, "media": 500, "alta": 580, "feriado": 720},
    "cabana": {"baixa": 490, "media": 610, "alta": 710, "feriado": 880},
    "cabana_plus": {"baixa": 540, "media": 680, "alta": 780, "feriado": 970},
    "hobbit": {"baixa": 650, "media": 810, "alta": 940, "feriado": 1170},
    "day_use": {"baixa": 180, "media": 210, "alta": 240, "feriado": 270},
}

# perfil-padrão de cada tipo — vale para os quartos sem exceção própria
TIPO_PADRAO = {
    "Padrão": "padrao",
    "Intermediário": "interm",
    "Cabana Intermediária": "cabana",
    "Cabana Hobbit": "hobbit",
    "Dia na Pousada": "day_use",
}

# exceção por quarto (número → perfil). Cobre TODOS os quartos duplos (também para
# neutralizar o ×1,6), inclusive os que ficam no preço-base da própria categoria.
QUARTO_PERFIL = {
    "Quarto 01": "interm_plus",
    "Quarto 02": "interm_plus",
    "Quarto 16": "cabana_plus",
    "Quarto 17": "cabana_plus",
    "Quarto 18": "cabana_plus",
    "Quarto 19": "cabana",
    "Quarto 20": "cabana",
    "Quarto 21": "cabana",
    "Quarto 22": "hobbit",
    "Quarto 23": "hobbit",
    "Quarto 24": "hobbit",
}

SEASONS = ("media", "alta", "feriado")  # baixa = tarifa_base do tipo/quarto


def _d(reais: int) -> Decimal:
    return Decimal(reais).quantize(Decimal("0.01"))


class Command(BaseCommand):
    help = "Carrega a tabela de tarifas aprovada (base/média/alta/feriado) nos quartos."

    @transaction.atomic
    def handle(self, *args, **options):
        faltando = [n for n in TIPO_PADRAO if not TipoUH.objects.filter(nome=n).exists()]
        if faltando:
            self.stderr.write(self.style.ERROR("Tipos não encontrados: " + ", ".join(faltando)))
            return

        # perfil-padrão por tipo (atende os quartos sem exceção própria)
        for nome, perfil_key in TIPO_PADRAO.items():
            tipo = TipoUH.objects.get(nome=nome)
            p = PERFIS[perfil_key]
            baixa = _d(p["baixa"])
            if tipo.tarifa_base != baixa:
                tipo.tarifa_base = baixa
                tipo.save(update_fields=["tarifa_base"])
            for classif in SEASONS:
                Tarifa.objects.update_or_create(
                    tipo_uh=tipo, classificacao=classif, defaults={"valor": _d(p[classif])}
                )
            self.stdout.write(f"  {nome}: base {baixa} (perfil {perfil_key})")

        # preço por quarto (exceções + neutralização do ×1,6 dos duplos)
        for numero, perfil_key in QUARTO_PERFIL.items():
            tipo = None
            uh = None
            for t in TipoUH.objects.all():
                uh = t.uhs.filter(numero=numero).first()
                if uh:
                    tipo = t
                    break
            if not uh:
                self.stderr.write(self.style.WARNING(f"  quarto não encontrado: {numero}"))
                continue
            p = PERFIS[perfil_key]
            baixa = _d(p["baixa"])
            if uh.tarifa_override != baixa:
                uh.tarifa_override = baixa
                uh.save(update_fields=["tarifa_override"])
            for classif in SEASONS:
                TarifaUnidade.objects.update_or_create(
                    uh=uh, classificacao=classif, defaults={"valor": _d(p[classif])}
                )
            self.stdout.write(f"    {numero} ({tipo.nome}): base {baixa} (perfil {perfil_key})")

        # guarda: nenhum quarto duplo pode ficar sem preço próprio (senão pega ×1,6)
        descobertos = []
        for t in TipoUH.objects.filter(modalidade=TipoUH.Modalidade.HOSPEDAGEM):
            for uh in t.uhs.all():
                if eh_duplo(uh) and uh.numero not in QUARTO_PERFIL:
                    descobertos.append(uh.numero)
        if descobertos:
            self.stderr.write(self.style.WARNING(
                "Quartos duplos SEM preço próprio (pegam ×1,6): " + ", ".join(descobertos)
            ))

        self.stdout.write(self.style.SUCCESS("Tarifas carregadas."))

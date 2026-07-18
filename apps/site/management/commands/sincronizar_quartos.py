"""
Sincroniza a vitrine do site com os tipos de quarto do CRM (venda por tipo):
garante um card de quarto por TipoUH, vinculado (disponibilidade e preço vêm do
CRM). Reaproveita fotos existentes. Os quartos antigos (sem tipo) são ocultados.

Uso: manage.py sincronizar_quartos
"""
from django.core.management.base import BaseCommand

from apps.nucleo.models import TipoUH
from apps.site.models import CategoriaQuarto, Quarto


class Command(BaseCommand):
    help = "Cria/atualiza um card de quarto no site para cada TipoUH do CRM."

    def handle(self, *args, **opts):
        cat_hosp, _ = CategoriaQuarto.objects.get_or_create(
            nome="Acomodações", defaults={"descricao": "Tipos de quarto da pousada."}
        )
        cat_day, _ = CategoriaQuarto.objects.get_or_create(
            nome="Dia na Pousada",
            defaults={"descricao": "Day use — estrutura sem pernoite."},
        )
        fotos = [
            q.foto_principal for q in Quarto.objects.exclude(foto_principal="")
            if q.foto_principal
        ]

        criados = atualizados = 0
        for i, tipo in enumerate(TipoUH.objects.filter(ativo=True).order_by("tarifa_base")):
            day = tipo.modalidade == TipoUH.Modalidade.DAY_USE
            categoria = cat_day if day else cat_hosp
            if day:
                defaults = {
                    "nome": "Dia na Pousada",
                    "categoria": categoria,
                    "descricao": (
                        "Piscina, mirantes e passeio pela estrutura Vô Testa — "
                        "sem pernoite. Inclui acesso às áreas comuns; consumo à parte "
                        "(restaurante, loja etc.) na conta do dia."
                    ),
                    "descricao_curta": (
                        "Day use: piscina, mirantes e estrutura — sem hospedagem."
                    ),
                    "capacidade": tipo.capacidade or 10,
                    "metragem": 0,
                    "preco_base": tipo.tarifa_base,
                    "status": "disponivel",
                    "destaque": True,
                    "ordem": 100 + i,
                    "foto_principal": fotos[i % len(fotos)] if fotos else "",
                }
            else:
                cap = 4 if "cabana" in tipo.nome.lower() else 2
                defaults = {
                    "nome": tipo.nome,
                    "categoria": categoria,
                    "descricao": f"Acomodação {tipo.nome} da Pousada Vô Testa.",
                    "descricao_curta": f"Quarto {tipo.nome} — conforto e charme.",
                    "capacidade": cap,
                    "metragem": 25,
                    "preco_base": tipo.tarifa_base,
                    "status": "disponivel",
                    "destaque": True,
                    "ordem": i,
                    "foto_principal": fotos[i % len(fotos)] if fotos else "",
                }
            quarto, novo = Quarto.objects.get_or_create(tipo_uh=tipo, defaults=defaults)
            if not novo:
                quarto.preco_base = tipo.tarifa_base
                quarto.categoria = categoria
                if day:
                    quarto.nome = "Dia na Pousada"
                    quarto.descricao_curta = defaults["descricao_curta"]
                    quarto.capacidade = tipo.capacidade or 10
                quarto.save()
                atualizados += 1
            else:
                criados += 1

        ocultos = Quarto.objects.filter(tipo_uh__isnull=True).update(
            destaque=False, status="inativo"
        )
        self.stdout.write(self.style.SUCCESS(
            f"Vitrine sincronizada: {criados} criados, {atualizados} atualizados, "
            f"{ocultos} card(s) antigo(s) ocultado(s)."
        ))

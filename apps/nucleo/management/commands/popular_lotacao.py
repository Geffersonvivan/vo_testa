"""
Popula ~80% de lotação exercitando todos os módulos prontos:
Reservas (check-in, conta, faturamento), Estoque, Loja (venda no caixa e na
conta do quarto), Caixa e Governança (faxinas/limpeza).

Uso:  .venv/bin/python manage.py popular_lotacao
Aditivo e seguro: só ocupa quartos livres; pode rodar de novo.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.governanca import services as gov
from apps.loja import services as loja
from apps.nucleo.models import (
    UH,
    FormaPagamento,
    Hospede,
    LocalEstoque,
    Pessoa,
    Produto,
    SessaoCaixa,
    saldo,
    transferir,
)
from apps.reservas import services as rs
from apps.reservas.models import Reserva

NOMES = [
    "Rafael Menezes", "Beatriz Lima", "Thiago Souza", "Camila Rocha", "Bruno Alves",
    "Larissa Nunes", "Diego Castro", "Priscila Fontes", "Gustavo Reis", "Aline Barros",
    "Rodrigo Pires", "Fernanda Melo", "Marcelo Dias", "Juliana Prado", "Vinícius Cardoso",
    "Patrícia Gomes", "Leonardo Vieira", "Tatiane Moraes", "André Bittencourt", "Sabrina Luz",
    "Otávio Neves", "Renata Camargo", "Felipe Zanotto", "Isabela Kraus", "Henrique Moser",
    "Bianca Hoffmann", "Eduardo Bertoldi", "Manuela Griebeler",
]


class Command(BaseCommand):
    help = "Popula ~80% de lotação usando todos os módulos implementados."

    def handle(self, *args, **options):
        random.seed(7)
        self.hoje = timezone.localdate()
        self.user = self._usuario()
        self.stdout.write("Preparando estoque da Loja e caixa…")
        self._estoque_loja()
        self._abrir_caixa()
        self.stdout.write("Ocupando quartos (~80%)…")
        n = self._lotacao()
        self.stdout.write("Vendas balcão na Loja…")
        self._loja_balcao()
        self.stdout.write("Governança (faxinas e limpeza)…")
        self._governanca()
        self.stdout.write(self.style.SUCCESS(
            f"Pronto! {n} quartos ocupados agora. Módulos exercitados."
        ))

    # ------------------------------------------------------------------

    def _usuario(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return (User.objects.filter(username="gvivan").first()
                or User.objects.filter(is_superuser=True).first())

    def _estoque_loja(self):
        self.loja_local = LocalEstoque.objects.filter(modulo="loja").first()
        alm = LocalEstoque.objects.filter(modulo="nucleo").first()
        if self.loja_local and alm:
            for p in Produto.objects.filter(ativo=True):
                if saldo(p, self.loja_local) < 6 and saldo(p, alm) >= 12:
                    try:
                        transferir(p, alm, self.loja_local, Decimal("12"), self.user)
                    except Exception:
                        pass
        self.produtos_loja = [
            p for p in Produto.objects.filter(ativo=True)
            if self.loja_local and saldo(p, self.loja_local) > 0
        ]

    def _abrir_caixa(self):
        SessaoCaixa.objects.get_or_create(
            operador=self.user, modulo="nucleo", status="aberta",
            defaults={"fundo_troco": Decimal("300.00")},
        )
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.pix = FormaPagamento.objects.get(tipo="pix")

    def _hospedes(self):
        pool = list(Pessoa.objects.filter(hospede__isnull=False))
        for nome in NOMES:
            if len(pool) >= 26:
                break
            p, criado = Pessoa.objects.get_or_create(nome=nome)
            if criado:
                Hospede.objects.get_or_create(pessoa=p)
            pool.append(p)
        random.shuffle(pool)
        return pool

    def _quarto_ocupado_hoje(self, uh):
        return Reserva.objects.filter(
            uh=uh, status=Reserva.Status.HOSPEDADA,
            checkin__lte=self.hoje, checkout__gt=self.hoje,
        ).exists()

    def _lotacao(self):
        hospedes = self._hospedes()
        gi = 0
        quartos = list(UH.objects.filter(status=UH.Status.ATIVA).order_by("numero"))
        ja = sum(1 for uh in quartos if self._quarto_ocupado_hoje(uh))
        alvo = round(len(quartos) * 0.80)

        # Reserva 3 quartos para variar (chegada / limpeza / bloqueio).
        livres = [uh for uh in quartos if not self._quarto_ocupado_hoje(uh)]
        reservados_variar = livres[-3:] if len(livres) > alvo - ja + 3 else []

        for uh in livres:
            if uh in reservados_variar:
                continue
            if ja >= alvo:
                break
            ci = self.hoje - timedelta(days=random.randint(0, 3))
            co = self.hoje + timedelta(days=random.randint(2, 6))
            if not rs.uh_disponivel(uh, ci, co):
                continue
            hospede = hospedes[gi % len(hospedes)]
            gi += 1
            diaria = rs.diaria_media(uh.tipo, ci, co)
            r = Reserva.objects.create(
                uh=uh, hospede=hospede, checkin=ci, checkout=co,
                status=Reserva.Status.CONFIRMADA, valor_diaria=diaria,
                criado_por=self.user, observacoes="[lotacao]",
            )
            # Guard de Governança: entrada só em quarto limpo/inspecionado.
            try:
                from apps.governanca.models import StatusLimpeza
                gov.definir_status(uh, StatusLimpeza.Situacao.LIMPA, self.user)
            except Exception:
                pass
            conta = r.fazer_checkin(self.user)
            # Metade consome na Loja lançando na conta do quarto.
            if self.produtos_loja and random.random() < 0.55:
                p = random.choice(self.produtos_loja)
                if saldo(p, self.loja_local) >= 2:
                    try:
                        loja.finalizar_venda(
                            self.user, self.loja_local,
                            [{"produto_id": p.pk, "quantidade": random.randint(1, 2)}],
                            "conta", conta_id=conta.pk,
                        )
                    except Exception:
                        pass
            ja += 1

        # Chegada de hoje (confirmada, sem check-in) num quarto reservado a variar.
        for uh in reservados_variar[:1]:
            co = self.hoje + timedelta(days=3)
            if rs.uh_disponivel(uh, self.hoje, co):
                Reserva.objects.create(
                    uh=uh, hospede=hospedes[gi % len(hospedes)], checkin=self.hoje,
                    checkout=co, status=Reserva.Status.CONFIRMADA,
                    valor_diaria=rs.diaria_media(uh.tipo, self.hoje, co),
                    criado_por=self.user, observacoes="[lotacao]",
                )
                gi += 1
        return ja

    def _loja_balcao(self):
        if not self.produtos_loja:
            return
        for _ in range(3):
            p = random.choice(self.produtos_loja)
            if saldo(p, self.loja_local) >= 2:
                try:
                    loja.finalizar_venda(
                        self.user, self.loja_local,
                        [{"produto_id": p.pk, "quantidade": random.randint(1, 2)}],
                        "caixa", forma=random.choice([self.dinheiro, self.pix]),
                    )
                except Exception:
                    pass

    def _governanca(self):
        # Deixa alguns quartos livres em situações de limpeza + 1 bloqueio.
        livres = [
            uh for uh in UH.objects.filter(status=UH.Status.ATIVA).order_by("numero")
            if not self._quarto_ocupado_hoje(uh)
        ]
        if len(livres) >= 2:
            gov.abrir_faxina(livres[0], usuario=self.user, origem="demo")  # suja
            t = gov.abrir_faxina(livres[1], usuario=self.user, origem="demo")
            gov.iniciar_tarefa(t, self.user)  # em limpeza
        if len(livres) >= 3:
            livres[2].status = UH.Status.BLOQUEADA
            livres[2].save(update_fields=["status"])

"""
Popula a Lavanderia para teste: tabela de preços, itens de enxoval com estoque
inicial distribuído, algumas ordens de hóspede em vários status e uma coleta de
enxoval sujo. Uso: manage.py popular_lavanderia [--limpar]
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.lavanderia import services
from apps.lavanderia.models import (
    ItemEnxoval,
    MovimentoEnxoval,
    OrdemLavanderia,
    ServicoLavanderia,
)
from apps.nucleo.models import Pessoa

Usuario = get_user_model()

SERVICOS = [
    ("Camisa social", "peca", "8.00"),
    ("Calça", "peca", "10.00"),
    ("Vestido", "peca", "15.00"),
    ("Roupa por quilo", "kg", "22.00"),
    ("Passar (peça)", "peca", "5.00"),
]
ENXOVAL = [
    # nome, minimo, por_faxina, estoque_inicial_limpa
    ("Lençol casal", 20, 1, 60),
    ("Fronha", 40, 2, 120),
    ("Toalha de banho", 30, 2, 90),
    ("Toalha de rosto", 20, 1, 60),
]


class Command(BaseCommand):
    help = "Cria dados de exemplo para a Lavanderia (serviços, enxoval e ordens)."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true")

    def handle(self, *args, **opts):
        op = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if not op:
            self.stderr.write("Crie um superusuário antes.")
            return

        if opts["limpar"]:
            OrdemLavanderia.objects.all().delete()
            MovimentoEnxoval.objects.all().delete()
            self.stdout.write("Ordens e movimentos de enxoval removidos.")

        # Tabela de preços
        servicos = {}
        for nome, unidade, preco in SERVICOS:
            s, _ = ServicoLavanderia.objects.get_or_create(
                nome=nome, defaults={"unidade": unidade, "preco": Decimal(preco)}
            )
            servicos[nome] = s

        # Enxoval + estoque inicial (limpa → parte distribuída para em uso)
        for nome, minimo, por_faxina, inicial in ENXOVAL:
            item, criado = ItemEnxoval.objects.get_or_create(
                nome=nome, defaults={"minimo": minimo, "por_faxina": por_faxina}
            )
            if not item.movimentos.exists():
                services.adquirir(item, inicial, op)
                services.distribuir(item, inicial // 2, op)  # metade em uso

        # Ordens de hóspede em vários status
        hospede = Pessoa.objects.filter(hospede__isnull=False).first() or Pessoa.objects.first()
        hoje = timezone.localdate()

        # 1) Recebida (aberta), sem entregar
        o1 = services.abrir_ordem(op, cliente=hospede, prazo=hoje + timedelta(days=1))
        services.adicionar_item(o1, servicos["Camisa social"], 3, op)
        services.adicionar_item(o1, servicos["Calça"], 2, op)

        # 2) Lavando
        o2 = services.abrir_ordem(op, rotulo="Quarto 12", prazo=hoje + timedelta(days=1))
        services.adicionar_item(o2, servicos["Vestido"], 1, op)
        services.avancar_status(o2)  # lavando

        # 3) Entregue e cobrada no caixa (precisa de caixa aberto → tenta, senão pula)
        from apps.nucleo.models import FormaPagamento, SessaoCaixa
        sessao = SessaoCaixa.objects.filter(operador=op, status=SessaoCaixa.Status.ABERTA).first()
        if not sessao:
            SessaoCaixa.objects.create(operador=op, modulo="nucleo", fundo_troco=Decimal("0"))
        o3 = services.abrir_ordem(op, rotulo="Balcão avulso")
        services.adicionar_item(o3, servicos["Passar (peça)"], 5, op)
        forma = FormaPagamento.objects.filter(tipo="dinheiro").first() or FormaPagamento.objects.first()
        services.entregar(o3, op, "caixa", forma=forma)

        self.stdout.write(self.style.SUCCESS(
            f"Lavanderia populada: {ServicoLavanderia.objects.count()} serviços, "
            f"{ItemEnxoval.objects.count()} itens de enxoval, "
            f"{OrdemLavanderia.objects.count()} ordens."
        ))

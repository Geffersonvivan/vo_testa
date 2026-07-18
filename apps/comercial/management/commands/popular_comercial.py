"""Popula o funil comercial com oportunidades de demonstração."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comercial.models import AtividadeComercial, EtapaFunil, Oportunidade
from apps.nucleo.models import Pessoa

Usuario = get_user_model()

LEADS = [
    ("Família Andrade", "particular", "site", "Feriadão — 2 quartos", "Novo lead", "80000.00"),
    ("Agência Serra Azul", "agencia", "agencia", "Bloqueio 5 quartos — julho", "Cotação enviada", "150000.00"),
    ("Construtora Oeste", "empresa", "telefone", "Hospedagem equipe de obra", "Negociação", "220000.00"),
    ("João e Marta", "particular", "whatsapp", "Lua de mel — suíte", "Contato feito", "60000.00"),
    ("Grupo Terceira Idade", "agencia", "indicacao", "Excursão 8 quartos", "Novo lead", "180000.00"),
]


class Command(BaseCommand):
    help = "Popula o módulo Comercial com oportunidades de teste."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true",
                            help="Apaga oportunidades e atividades antes de semear.")

    def handle(self, *args, **opts):
        if opts["limpar"]:
            AtividadeComercial.objects.all().delete()
            Oportunidade.objects.all().delete()
            self.stdout.write("Oportunidades anteriores removidas.")

        operador = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if not operador:
            self.stderr.write("Crie um usuário antes de rodar o seed.")
            return
        agora = timezone.now()

        for nome, fat, origem, titulo, etapa_nome, valor in LEADS:
            pessoa, _ = Pessoa.objects.get_or_create(nome=nome, defaults={"ativo": True})
            etapa = EtapaFunil.objects.filter(nome=etapa_nome).first() or EtapaFunil.objects.first()
            op = Oportunidade.objects.create(
                pessoa=pessoa, titulo=titulo, etapa=etapa, faturamento=fat, origem=origem,
                valor_estimado=Decimal(valor), quartos=2, hospedes=4,
                responsavel=operador, criado_por=operador,
                checkin_previsto=(agora + timedelta(days=20)).date(),
                checkout_previsto=(agora + timedelta(days=23)).date(),
            )
            AtividadeComercial.objects.create(
                oportunidade=op, tipo="ligacao", descricao="Primeiro contato feito.",
                quando=agora - timedelta(days=2), concluida=True,
                responsavel=operador, criado_por=operador,
            )
            AtividadeComercial.objects.create(
                oportunidade=op, tipo="tarefa", descricao="Fazer follow-up da proposta.",
                quando=agora + timedelta(days=1), concluida=False,
                responsavel=operador, criado_por=operador,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Funil populado: {Oportunidade.objects.count()} oportunidades."
        ))

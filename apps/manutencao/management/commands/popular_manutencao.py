"""
Popula o módulo Manutenção com um mix realista de ordens de serviço para teste:
corretivas e preventivas, abertas/em andamento/concluídas/canceladas, algumas
bloqueando o quarto (escolhendo só quartos livres) e outras em áreas comuns.

Uso: manage.py popular_manutencao [--limpar]
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.manutencao import services
from apps.manutencao.models import OrdemServico
from apps.reservas import services as reservas_services

Usuario = get_user_model()


class Command(BaseCommand):
    help = "Cria ordens de serviço de exemplo para o módulo Manutenção."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true",
                            help="Apaga as OSs existentes antes de popular.")

    def handle(self, *args, **opts):
        op = Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        if not op:
            self.stderr.write("Nenhum usuário encontrado — crie um superusuário antes.")
            return

        if opts["limpar"]:
            # Solta bloqueios pendentes antes de apagar, para não deixar quarto preso.
            for os in OrdemServico.objects.filter(bloqueia_uh=True):
                if os.aberta_ou_andamento and os.uh_id:
                    services.cancelar_os(os, op, "reset do seed")
            n = OrdemServico.objects.count()
            OrdemServico.objects.all().delete()
            self.stdout.write(f"{n} OS removidas.")

        hoje = timezone.localdate()
        from django.db.models import Q

        from apps.nucleo.models import UH, Pessoa

        # Um prestador externo (fornecedor/empresa) para as OSs terceirizadas.
        prestador = Pessoa.objects.filter(ativo=True).filter(
            Q(fornecedor__isnull=False) | Q(agencia__isnull=False)
        ).first()

        livres = list(reservas_services.uhs_disponiveis(hoje, hoje + timedelta(days=1)))
        if len(livres) < 2:
            self.stderr.write("Preciso de ao menos 2 quartos livres para bloquear.")
            return
        # Quartos ativos para as OSs sem bloqueio (ocupado pode ter chamado também).
        ativos = list(UH.objects.filter(status=UH.Status.ATIVA).order_by("numero"))

        P = OrdemServico.Prioridade
        T = OrdemServico.Tipo
        criadas = 0

        # 1) Corretiva urgente bloqueando um quarto livre — fica ABERTA.
        services.abrir_os(op, uh=livres[0], titulo="Vazamento sob a pia",
                          descricao="Água acumulando no armário do banheiro.",
                          prioridade=P.URGENTE, bloquear=True)
        criadas += 1

        # 2) Corretiva alta bloqueando outro livre, terceirizada — EM ANDAMENTO.
        os2 = services.abrir_os(op, uh=livres[1], titulo="Ar-condicionado sem gelar",
                                prioridade=P.ALTA, bloquear=True,
                                prestador=prestador,
                                previsto_para=hoje + timedelta(days=2))
        services.iniciar_os(os2, op)
        criadas += 1

        # 3) Corretiva média sem bloqueio (chamado de hóspede em casa) — ABERTA.
        services.abrir_os(op, uh=ativos[0], titulo="Tomada da cabeceira solta",
                          prioridade=P.MEDIA)
        criadas += 1

        # 4) Área comum — piscina, EM ANDAMENTO.
        os4 = services.abrir_os(op, area="Piscina", titulo="Bomba de recirculação com ruído",
                                prioridade=P.ALTA)
        services.iniciar_os(os4, op)
        criadas += 1

        # 5) Área comum — recepção, ABERTA.
        services.abrir_os(op, area="Recepção", titulo="Trocar lâmpadas queimadas",
                          prioridade=P.BAIXA)
        criadas += 1

        # 6) Preventiva com recorrência — CONCLUÍDA (agenda a próxima automaticamente).
        os6 = services.abrir_os(op, uh=ativos[1], titulo="Revisão do ar-condicionado",
                                tipo=T.PREVENTIVA, prioridade=P.MEDIA,
                                recorrencia_meses=6, agendada_para=hoje)
        prox = services.concluir_os(os6, op, resolucao="Filtros limpos, gás ok.",
                                    custo_maodeobra="120")
        criadas += 1

        # 7) Corretiva já CONCLUÍDA (histórico) com custos.
        os7 = services.abrir_os(op, uh=ativos[2], titulo="Fechadura emperrada",
                                prioridade=P.MEDIA)
        services.concluir_os(os7, op, resolucao="Troca do miolo.",
                             custo_maodeobra="80", custo_pecas="45")
        criadas += 1

        # 8) Corretiva CANCELADA.
        os8 = services.abrir_os(op, area="Corredor bloco B",
                                titulo="Piso solto (chamado duplicado)", prioridade=P.BAIXA)
        services.cancelar_os(os8, op, "Duplicado da OS do zelador.")
        criadas += 1

        # 9) Ciclo completo: bloqueia um livre e CONCLUI — libera o quarto e a
        #    Governança (se ativa) abre a faxina pós-reparo.
        if len(livres) >= 3:
            os9 = services.abrir_os(op, uh=livres[2], titulo="Troca da resistência do chuveiro",
                                    prioridade=P.ALTA, bloquear=True, prestador=prestador)
            services.concluir_os(os9, op, resolucao="Resistência trocada e testada.",
                                 custo_maodeobra="60", custo_pecas="35",
                                 nota_fiscal="NF 8842",
                                 garantia_ate=hoje + timedelta(days=180))
            criadas += 1

        self.stdout.write(self.style.SUCCESS(
            f"{criadas} OSs criadas. Quartos bloqueados agora: "
            f"{[u.numero for u in [livres[0], livres[1]]]}. "
            f"Próxima preventiva agendada: {prox.agendada_para if prox else '—'}."
        ))

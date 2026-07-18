"""
Limpa pendências operacionais envelhecidas do banco local de demo e
reabre espaço para uma lotação fresca.

- Encerra hospedagens [lotacao]/[demo] com check-out vencido (paga saldo,
  conferência frigobar zerada, check-out).
- Cancela pré-reservas/confirmadas [lotacao] vencidas.
- Fecha caixas abertos de dias anteriores (conferência = esperado).
- Desbloqueia UHs que ficaram BLOQUEADA pelo seed de lotação.
- Marca quartos livres como limpos (Governança).

Uso:  .venv/bin/python manage.py sanear_demo
       .venv/bin/python manage.py sanear_demo --relotar
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import timezone

from apps.nucleo.models import UH, FormaPagamento, SessaoCaixa
from apps.reservas.models import Reserva


class Command(BaseCommand):
    help = "Sanea dados demo envelhecidos (check-outs, caixas, UHs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--relotar",
            action="store_true",
            help="Após sanear, roda popular_lotacao de novo.",
        )

    def handle(self, *args, **options):
        self.hoje = timezone.localdate()
        self.user = self._usuario()
        if not self.user:
            self.stderr.write("Nenhum usuário encontrado.")
            return

        n_co = self._encerrar_hospedagens_vencidas()
        n_canc = self._cancelar_reservas_vencidas()
        n_cx = self._fechar_caixas_antigos()
        n_uh = self._desbloquear_uhs_demo()
        n_limp = self._limpar_quartos_livres()

        self.stdout.write(self.style.SUCCESS(
            f"Saneado: {n_co} check-outs, {n_canc} canceladas, "
            f"{n_cx} caixas, {n_uh} UHs desbloqueadas, {n_limp} limpas."
        ))
        if options["relotar"]:
            self.stdout.write("Relotando…")
            call_command("popular_lotacao")

    def _usuario(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return (
            User.objects.filter(username="gvivan").first()
            or User.objects.filter(is_superuser=True).first()
        )

    def _encerrar_hospedagens_vencidas(self):
        qs = Reserva.objects.filter(
            status=Reserva.Status.HOSPEDADA,
            checkout__lte=self.hoje,
            observacoes__iregex=r"\[(lotacao|demo)\]",
        ).select_related("uh")
        n = 0
        dinheiro = FormaPagamento.objects.filter(tipo="dinheiro").first()
        SessaoCaixa.objects.get_or_create(
            operador=self.user, modulo="nucleo", status=SessaoCaixa.Status.ABERTA,
            defaults={"fundo_troco": Decimal("100.00")},
        )
        for r in qs:
            try:
                conta = r.conta
                saldo = conta.saldo()
                if saldo > 0 and dinheiro:
                    from apps.reservas import services as rs

                    rs.receber_pagamento(conta, self.user, dinheiro, saldo)
                from apps.frigobar.services import (
                    conferencia_checkout_feita,
                    registrar_conferencia,
                )

                if not conferencia_checkout_feita(conta=conta):
                    registrar_conferencia(self.user, conta, "checkout", [])
                r.fazer_checkout(self.user)
                n += 1
            except Exception as erro:
                self.stderr.write(f"  Reserva #{r.pk}: {erro}")
        return n

    def _cancelar_reservas_vencidas(self):
        qs = Reserva.objects.filter(
            status__in=[Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA],
            checkout__lte=self.hoje,
            observacoes__iregex=r"\[(lotacao|demo)\]",
        )
        n = 0
        for r in qs:
            try:
                r.cancelar(self.user, "Saneamento demo — período vencido")
                n += 1
            except Exception as erro:
                self.stderr.write(f"  Cancelar #{r.pk}: {erro}")
        return n

    def _fechar_caixas_antigos(self):
        qs = SessaoCaixa.objects.filter(
            status=SessaoCaixa.Status.ABERTA,
            aberta_em__date__lt=self.hoje,
        )
        n = 0
        for s in qs:
            try:
                s.fechar(s.esperado_em_dinheiro(), self.user, observacoes="Saneamento demo")
                n += 1
            except Exception as erro:
                self.stderr.write(f"  Caixa #{s.pk}: {erro}")
        return n

    def _desbloquear_uhs_demo(self):
        # Lotação marca 1 UH como BLOQUEADA sem OS — libera as sem OS aberta.
        from apps.manutencao.models import OrdemServico

        bloqueadas = UH.objects.filter(status=UH.Status.BLOQUEADA)
        n = 0
        for uh in bloqueadas:
            tem_os = OrdemServico.objects.filter(
                uh=uh, status__in=["aberta", "em_andamento"]
            ).exists()
            if not tem_os:
                uh.status = UH.Status.ATIVA
                uh.save(update_fields=["status"])
                n += 1
        return n

    def _limpar_quartos_livres(self):
        try:
            from apps.governanca.models import StatusLimpeza
            from apps.governanca import services as gov
        except Exception:
            return 0
        ocupadas = set(
            Reserva.objects.filter(status=Reserva.Status.HOSPEDADA)
            .values_list("uh_id", flat=True)
        )
        n = 0
        for uh in UH.objects.filter(status=UH.Status.ATIVA).exclude(pk__in=ocupadas):
            gov.definir_status(uh, StatusLimpeza.Situacao.LIMPA, self.user)
            n += 1
        return n

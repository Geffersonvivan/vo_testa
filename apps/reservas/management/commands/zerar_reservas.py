"""Zera TODOS os dados de reservas (uso: reset de ambiente de teste) e reinicia o
contador para a próxima reserva ser a #1.

Apaga: reservas e dependentes (conta/folio, adiantamentos, fichas FNRH, acompanhantes,
grupos), as cobranças do módulo Pagamentos ligadas a reservas, os recibos do site
(core_reserva), os acessos/solicitações do portal e os movimentos de caixa de reservas
(adiantamento/folio + estornos). **Leads: apenas desvincula** (zera
`comercial_oportunidade.reserva_id`) — não apaga nem altera mais nada do lead/Pessoa.

Dry-run por padrão (só conta). Use --sim para executar de verdade. Tudo numa transação:
se faltar tratar algum dependente, o FK quebra e dá rollback (não apaga pela metade).

    python manage.py zerar_reservas          # mostra o que seria apagado
    python manage.py zerar_reservas --sim     # executa
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

# Tabelas de reservas a esvaziar, na ORDEM segura (dependentes PROTECT antes da Reserva).
_TABELAS_RESERVAS = [
    "reservas_pagamentoconta",
    "reservas_lancamentoconta",
    "reservas_adiantamento",
    "reservas_contahospedagem",
    "reservas_acompanhante",
    "reservas_fichafnrh",
    "reservas_reserva",
    "reservas_gruporeserva",
]
# (tabela, coluna) cujo id deve voltar a começar em 1.
_SEQUENCIAS = [
    ("reservas_reserva", "id"),
    ("reservas_adiantamento", "id"),
    ("reservas_contahospedagem", "id"),
    ("reservas_acompanhante", "id"),
    ("reservas_fichafnrh", "id"),
    ("reservas_lancamentoconta", "id"),
    ("reservas_pagamentoconta", "id"),
    ("reservas_gruporeserva", "id"),
    ("core_reserva", "id"),
    ("portal_acessoportal", "id"),
    ("portal_solicitacaoportal", "id"),
]


class Command(BaseCommand):
    help = "Zera todos os dados de reservas e reinicia o contador (começa na #1)."

    def add_arguments(self, parser):
        parser.add_argument("--sim", action="store_true",
                            help="Executa de verdade (sem isto, só mostra o que faria).")

    def _conta(self, cur, sql):
        cur.execute(sql)
        return cur.fetchone()[0]

    def handle(self, *args, **opts):
        executar = opts["sim"]
        with connection.cursor() as cur:
            # Prévia (contagens).
            n_reservas = self._conta(cur, "SELECT COUNT(*) FROM reservas_reserva")
            n_cobr = self._conta(
                cur, "SELECT COUNT(*) FROM pagamentos_cobranca WHERE reserva_id IS NOT NULL")
            n_site = self._conta(cur, "SELECT COUNT(*) FROM core_reserva")
            n_leads = self._conta(
                cur, "SELECT COUNT(*) FROM comercial_oportunidade WHERE reserva_id IS NOT NULL")
            # Movimentos de caixa de reservas (adiantamento + folio).
            cur.execute(
                "SELECT movimento_caixa_id FROM reservas_adiantamento "
                "WHERE movimento_caixa_id IS NOT NULL "
                "UNION SELECT movimento_caixa_id FROM reservas_pagamentoconta "
                "WHERE movimento_caixa_id IS NOT NULL")
            mov_ids = [r[0] for r in cur.fetchall()]

            self.stdout.write(self.style.WARNING("== ZERAR RESERVAS =="))
            self.stdout.write(f"  Reservas: {n_reservas}")
            self.stdout.write(f"  Cobranças (Pagamentos) ligadas a reservas: {n_cobr}  (apagar)")
            self.stdout.write(f"  Recibos do site (core_reserva): {n_site}  (apagar)")
            self.stdout.write(f"  Movimentos de caixa de reservas: {len(mov_ids)}  (apagar)")
            self.stdout.write(f"  Leads com reserva vinculada: {n_leads}  (SÓ desvincular)")

            if not executar:
                self.stdout.write(self.style.NOTICE(
                    "\nDry-run. Nada foi alterado. Rode com --sim para executar."))
                return

            with transaction.atomic():
                # 1) Leads: SÓ desvincular (não toca em mais nada do lead).
                cur.execute("UPDATE comercial_oportunidade SET reserva_id = NULL "
                            "WHERE reserva_id IS NOT NULL")
                # 2) Pagamentos: eventos + cobranças ligadas a reservas.
                cur.execute("DELETE FROM pagamentos_eventopagamento WHERE cobranca_id IN "
                            "(SELECT id FROM pagamentos_cobranca WHERE reserva_id IS NOT NULL)")
                cur.execute("DELETE FROM pagamentos_cobranca WHERE reserva_id IS NOT NULL")
                # 3) Recibos do site e portal (dados de teste).
                cur.execute("DELETE FROM core_reserva")
                cur.execute("DELETE FROM portal_solicitacaoportal")
                cur.execute("DELETE FROM portal_acessoportal")
                # 4) Reservas e dependentes (ordem PROTECT→Reserva).
                for tabela in _TABELAS_RESERVAS:
                    cur.execute(f"DELETE FROM {tabela}")
                # 5) Movimentos de caixa de reservas: estornos primeiro, depois os originais.
                if mov_ids:
                    cur.execute("DELETE FROM nucleo_movimentocaixa "
                                "WHERE movimento_origem_id = ANY(%s)", [mov_ids])
                    cur.execute("DELETE FROM nucleo_movimentocaixa WHERE id = ANY(%s)", [mov_ids])
                # 6) Reiniciar os contadores (próxima reserva = #1).
                for tabela, coluna in _SEQUENCIAS:
                    cur.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, %s), 1, false)",
                        [tabela, coluna])

            self.stdout.write(self.style.SUCCESS(
                "\nFeito. Reservas zeradas; próxima reserva será a #1. "
                "Leads apenas desvinculados (intactos)."))

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import LancamentoConta, Reserva, Tarifa

Usuario = get_user_model()

HOJE = timezone.localdate()


class ReservasTestsBase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_superuser(
            username="recepcao", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(
            nome="Cabana Teste", tarifa_base=Decimal("300.00")
        )
        self.uh = UH.objects.create(numero="T1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Maria Teste")
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def reserva(self, status=Reserva.Status.CONFIRMADA, dias=2, uh=None, offset=0):
        checkin = HOJE + timedelta(days=offset)
        return Reserva.objects.create(
            uh=uh or self.uh,
            hospede=self.hospede,
            checkin=checkin,
            checkout=checkin + timedelta(days=dias),
            status=status,
            valor_diaria=Decimal("300.00"),
            criado_por=self.usuario,
        )

    def abrir_caixa(self):
        return SessaoCaixa.objects.create(
            operador=self.usuario, modulo="nucleo", fundo_troco=Decimal("0.00")
        )


class OverbookingTests(ReservasTestsBase):
    def test_constraint_impede_periodos_sobrepostos(self):
        self.reserva(dias=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.reserva(dias=2, offset=1)  # entra no meio da primeira

    def test_checkout_libera_a_noite_para_proxima_entrada(self):
        self.reserva(dias=2)  # ocupa [hoje, hoje+2)
        # Próxima reserva entra exatamente no dia do check-out: permitido.
        proxima = self.reserva(dias=2, offset=2)
        self.assertIsNotNone(proxima.pk)

    def test_cancelada_nao_segura_uh(self):
        r = self.reserva(dias=3)
        r.cancelar(self.usuario, "Hóspede desistiu")
        # Mesmo período, agora livre.
        nova = self.reserva(dias=3)
        self.assertIsNotNone(nova.pk)

    def test_orcamento_nao_segura_uh(self):
        self.reserva(status=Reserva.Status.ORCAMENTO, dias=3)
        nova = self.reserva(dias=3)
        self.assertIsNotNone(nova.pk)

    def test_disponibilidade_via_service(self):
        self.assertTrue(services.uh_disponivel(self.uh, HOJE, HOJE + timedelta(days=2)))
        self.reserva(dias=2)
        self.assertFalse(
            services.uh_disponivel(self.uh, HOJE, HOJE + timedelta(days=2))
        )
        self.assertNotIn(
            self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2))
        )


class RetencaoExpiracaoTests(ReservasTestsBase):
    def _pre(self, expira_em):
        r = self.reserva(status=Reserva.Status.PRE_RESERVA)
        r.expira_em = expira_em
        r.save(update_fields=["expira_em"])
        return r

    def test_prereserva_vencida_nao_bloqueia(self):
        self._pre(timezone.now() - timedelta(minutes=1))
        # o quarto já aparece livre, mesmo antes do job rodar
        self.assertIn(self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2)))

    def test_prereserva_valida_bloqueia(self):
        self._pre(timezone.now() + timedelta(minutes=20))
        self.assertNotIn(self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2)))

    def test_expirar_vencidas_cancela(self):
        r = self._pre(timezone.now() - timedelta(minutes=1))
        n = services.expirar_vencidas()
        r.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(r.status, Reserva.Status.CANCELADA)

    def test_confirmar_limpa_expira_em(self):
        r = self._pre(timezone.now() - timedelta(minutes=1))
        r.confirmar(self.usuario)
        r.refresh_from_db()
        self.assertIsNone(r.expira_em)
        self.assertEqual(services.expirar_vencidas(), 0)  # confirmada não expira

    def test_criar_reserva_site_grava_prazo(self):
        r = services.criar_reserva_site(
            tipo_uh=self.tipo, checkin=HOJE + timedelta(days=1),
            checkout=HOJE + timedelta(days=3), hospede=self.hospede,
            usuario=self.usuario,
        )
        self.assertIsNotNone(r.expira_em)
        self.assertGreater(r.expira_em, timezone.now())


class TarifaTests(ReservasTestsBase):
    def test_tarifa_por_temporada_com_precedencia(self):
        Temporada.objects.create(
            nome="Alta verão", classificacao="alta",
            inicio=HOJE, fim=HOJE + timedelta(days=30),
        )
        Temporada.objects.create(
            nome="Feriadão", classificacao="feriado",
            inicio=HOJE, fim=HOJE + timedelta(days=2),
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="alta", valor=Decimal("400.00")
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="feriado", valor=Decimal("500.00")
        )
        # Feriado tem precedência sobre alta
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE), Decimal("500.00")
        )
        # Depois do feriado, vale a alta
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE + timedelta(days=5)),
            Decimal("400.00"),
        )

    def test_sem_temporada_usa_tarifa_base(self):
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE), Decimal("300.00")
        )

    def test_diaria_media_do_periodo(self):
        Temporada.objects.create(
            nome="Feriadão", classificacao="feriado",
            inicio=HOJE, fim=HOJE,  # só a primeira noite
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="feriado", valor=Decimal("500.00")
        )
        # 1 noite a 500 + 1 noite a 300 = média 400
        media = services.diaria_media(self.tipo, HOJE, HOJE + timedelta(days=2))
        self.assertEqual(media, Decimal("400.00"))


class CicloDeEstadosTests(ReservasTestsBase):
    def test_checkin_abre_conta_e_lanca_diarias_como_servico(self):
        r = self.reserva(dias=3)
        conta = r.fazer_checkin(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)
        self.assertEqual(conta.lancamentos.count(), 3)
        self.assertTrue(
            all(
                lanc.natureza == "servico" and lanc.tipo == "diaria"
                for lanc in conta.lancamentos.all()
            )
        )
        self.assertEqual(conta.total_lancamentos(), Decimal("900.00"))

    def test_checkout_exige_saldo_zero(self):
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        with self.assertRaises(ValidationError):
            r.fazer_checkout(self.usuario)  # 300 em aberto
        self.abrir_caixa()
        services.receber_pagamento(
            r.conta, self.usuario, self.dinheiro, Decimal("300.00")
        )
        # Frigobar ativo (seed): conferência de check-out antes da saída.
        from apps.frigobar.services import registrar_conferencia

        registrar_conferencia(self.usuario, r.conta, "checkout", [])
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)
        self.assertFalse(r.conta.aberta)

    def test_checkin_bloqueado_se_quarto_sujo(self):
        from apps.governanca.models import StatusLimpeza
        from apps.governanca.services import definir_status

        definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.usuario)
        r = self.reserva(dias=1)
        with self.assertRaises(ValidationError) as ctx:
            r.fazer_checkin(self.usuario)
        self.assertIn("limpo", str(ctx.exception).lower())
        definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.usuario)
        conta = r.fazer_checkin(self.usuario)
        self.assertIsNotNone(conta)

    def test_checkin_sem_governanca_nao_bloqueia(self):
        from apps.governanca.models import StatusLimpeza
        from apps.governanca.services import definir_status

        definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.usuario)
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        r = self.reserva(dias=1)
        self.assertIsNotNone(r.fazer_checkin(self.usuario))

    def test_checkout_bloqueado_sem_conferencia_frigobar(self):
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        self.abrir_caixa()
        services.receber_pagamento(
            r.conta, self.usuario, self.dinheiro, r.conta.saldo()
        )
        with self.assertRaises(ValidationError) as ctx:
            r.fazer_checkout(self.usuario)
        self.assertIn("frigobar", str(ctx.exception).lower())

    def test_checkout_sem_frigobar_nao_exige_conferencia(self):
        ModuloContratado.objects.filter(codigo=Modulo.FRIGOBAR).update(ativo=False)
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        self.abrir_caixa()
        services.receber_pagamento(
            r.conta, self.usuario, self.dinheiro, r.conta.saldo()
        )
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)

    def test_cancelamento_exige_motivo_e_audita(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            r.cancelar(self.usuario, "   ")
        r.cancelar(self.usuario, "Imprevisto do hóspede")
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="cancelamento_reserva").exists()
        )

    def test_hospedada_nao_pode_ser_cancelada(self):
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        with self.assertRaises(ValidationError):
            r.cancelar(self.usuario, "Tarde demais")

    def test_no_show_so_de_confirmada(self):
        r = self.reserva(status=Reserva.Status.PRE_RESERVA)
        with self.assertRaises(ValidationError):
            r.marcar_no_show(self.usuario)
        r.confirmar(self.usuario)
        r.marcar_no_show(self.usuario)
        self.assertEqual(r.status, Reserva.Status.NO_SHOW)


class ContaHospedagemTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        self.r = self.reserva(dias=2)
        self.conta = self.r.fazer_checkin(self.usuario)  # 600 em diárias (serviço)

    def test_lancamento_exige_natureza(self):
        with self.assertRaises(ValidationError):
            LancamentoConta(
                conta=self.conta, tipo="consumo", natureza="",
                descricao="Sem natureza", valor=Decimal("10.00"),
                criado_por=self.usuario,
            ).save()

    def test_subtotais_por_natureza(self):
        services.lancar_na_conta(
            self.conta, "consumo", "consumo", "Frigobar", Decimal("50.00"), self.usuario
        )
        services.lancar_na_conta(
            self.conta, "servico", "servico", "Lavanderia", Decimal("40.00"), self.usuario
        )
        services.lancar_na_conta(
            self.conta, "desconto", "servico", "Cortesia diária", Decimal("100.00"),
            self.usuario,
        )
        totais = self.conta.total_por_natureza()
        self.assertEqual(totais["Serviço"], Decimal("540.00"))  # 600+40−100
        self.assertEqual(totais["Consumo"], Decimal("50.00"))
        self.assertEqual(self.conta.total_lancamentos(), Decimal("590.00"))

    def test_lancamento_imutavel(self):
        lanc = self.conta.lancamentos.first()
        lanc.valor = Decimal("1.00")
        with self.assertRaises(ValidationError):
            lanc.save()
        with self.assertRaises(ValidationError):
            lanc.delete()

    def test_pagamento_passa_pelo_caixa_do_operador(self):
        # Sem caixa aberto: recusa.
        with self.assertRaises(ValidationError):
            services.receber_pagamento(
                self.conta, self.usuario, self.dinheiro, Decimal("100.00")
            )
        sessao = self.abrir_caixa()
        pagamento = services.receber_pagamento(
            self.conta, self.usuario, self.dinheiro, Decimal("100.00")
        )
        self.assertEqual(pagamento.movimento_caixa.sessao, sessao)
        self.assertEqual(sessao.esperado_em_dinheiro(), Decimal("100.00"))
        self.assertEqual(self.conta.saldo(), Decimal("500.00"))

    def test_adiantamento_vira_credito_na_conta(self):
        r2 = self.reserva(dias=2, offset=10)
        self.abrir_caixa()
        services.receber_adiantamento(
            r2, self.usuario, self.dinheiro, Decimal("200.00")
        )
        conta = r2.fazer_checkin(self.usuario)  # 600 de diárias
        self.assertEqual(conta.saldo(), Decimal("400.00"))

    def test_adiantamento_so_antes_do_checkin(self):
        self.abrir_caixa()
        with self.assertRaises(ValidationError):
            services.receber_adiantamento(
                self.r, self.usuario, self.dinheiro, Decimal("50.00")
            )


class PermissaoModuloTests(ReservasTestsBase):
    def test_view_exige_modulo_atribuido(self):
        Usuario.objects.create_user(username="sem-acesso", password="senha-forte-123")
        self.client.login(username="sem-acesso", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa"))
        self.assertEqual(resposta.status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa"))
        self.assertEqual(resposta.status_code, 404)

    def test_mapa_e_lista_carregam(self):
        self.reserva(dias=2)
        self.client.login(username="recepcao", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("reservas:mapa")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reservas:lista")).status_code, 200)

    def test_diaria_manual_exige_gerencia(self):
        operadora = Usuario.objects.create_user(
            username="operadora", password="senha-forte-123"
        )
        operadora.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        self.client.login(username="operadora", password="senha-forte-123")
        resposta = self.client.post(
            reverse("reservas:nova"),
            {
                "hospede": self.hospede.pk,
                "uh": self.uh.pk,
                "checkin": HOJE.isoformat(),
                "checkout": (HOJE + timedelta(days=2)).isoformat(),
                "adultos": 2,
                "criancas": 0,
                "canal": "balcao",
                "faturamento": "particular",
                "valor_diaria": "100.00",  # abaixo da tarifa vigente (300)
                "observacoes": "",
            },
        )
        self.assertContains(resposta, "exige gerência")
        self.assertEqual(Reserva.objects.count(), 0)


class FaturamentoTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        from apps.nucleo.models import Agencia
        self.agencia_pessoa = Pessoa.objects.create(
            nome="Agência CVC", tipo=Pessoa.Tipo.JURIDICA
        )
        Agencia.objects.create(pessoa=self.agencia_pessoa)

    def test_particular_pagador_e_o_hospede(self):
        r = self.reserva()
        self.assertEqual(r.faturamento, Reserva.Faturamento.PARTICULAR)
        self.assertEqual(r.pagador, self.hospede)

    def test_faturamento_agencia_exige_titular(self):
        r = Reserva(
            uh=self.uh, hospede=self.hospede,
            checkin=HOJE, checkout=HOJE + timedelta(days=2),
            faturamento=Reserva.Faturamento.AGENCIA,
            valor_diaria=Decimal("300.00"), criado_por=self.usuario,
        )
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_faturamento_agencia_pagador_e_o_titular(self):
        r = self.reserva()
        r.faturamento = Reserva.Faturamento.AGENCIA
        r.titular = self.agencia_pessoa
        r.full_clean()
        r.save()
        self.assertEqual(r.pagador, self.agencia_pessoa)

    def test_particular_zera_titular(self):
        r = self.reserva()
        r.titular = self.agencia_pessoa
        r.faturamento = Reserva.Faturamento.PARTICULAR
        r.full_clean()  # clean() deve limpar o titular
        self.assertIsNone(r.titular)


class MapaQuartosTests(ReservasTestsBase):
    def test_situacoes_no_mapa(self):
        # ocupada (hospedada), bloqueada e livre
        r = self.reserva(dias=2)
        r.fazer_checkin(self.usuario)
        UH.objects.create(numero="B1", tipo=self.tipo, status=UH.Status.BLOQUEADA)
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa_quartos"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Ocupada")
        self.assertContains(resposta, "Bloqueada")
        self.assertContains(resposta, self.hospede.nome[:18])

    def test_exige_modulo(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("reservas:mapa_quartos")).status_code, 403
        )


class TrocaQuartoTests(ReservasTestsBase):
    def test_troca_leva_a_conta(self):
        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)  # 600 em diárias
        outro = UH.objects.create(numero="T2", tipo=self.tipo)
        services.trocar_quarto(r, outro, self.usuario, "pedido do hóspede")
        r.refresh_from_db()
        self.assertEqual(r.uh, outro)
        self.assertEqual(r.conta.pk, conta.pk)  # mesma conta
        self.assertEqual(r.conta.total_lancamentos(), Decimal("600.00"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="troca_quarto").exists())

    def test_troca_bloqueada_por_overbooking(self):
        r = self.reserva(dias=3)
        outro = UH.objects.create(numero="T2", tipo=self.tipo)
        Reserva.objects.create(
            uh=outro, hospede=self.hospede, checkin=HOJE,
            checkout=HOJE + timedelta(days=3), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("300"), criado_por=self.usuario,
        )
        with self.assertRaises(ValidationError):
            services.trocar_quarto(r, outro, self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.uh, self.uh)

    def test_troca_exige_quarto_diferente(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            services.trocar_quarto(r, self.uh, self.usuario)


class RateioPagamentoTests(ReservasTestsBase):
    def test_dois_pagamentos_parciais_com_pagadores(self):
        # Rateio: a conta aceita vários pagamentos parciais até o saldo zerar.
        self.abrir_caixa()
        forma = FormaPagamento.objects.get(tipo="dinheiro")
        r = self.reserva(status=Reserva.Status.CONFIRMADA)  # 2 diárias × 300 = 600
        conta = r.fazer_checkin(self.usuario)
        services.receber_pagamento(conta, self.usuario, forma, Decimal("300"), observacao="Casal A")
        services.receber_pagamento(conta, self.usuario, forma, Decimal("300"), observacao="Casal B")
        self.assertEqual(conta.pagamentos.count(), 2)
        self.assertEqual(conta.saldo(), Decimal("0.00"))
        self.assertEqual(
            set(conta.pagamentos.values_list("observacao", flat=True)),
            {"Casal A", "Casal B"},
        )

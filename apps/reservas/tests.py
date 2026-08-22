from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
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


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
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
            operador=self.usuario, modulo="reservas", fundo_troco=Decimal("0.00")
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


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class SaidasVencidasTests(ReservasTestsBase):
    """Saídas atrasadas alimentam o painel; fechar é sempre do atendente."""

    def _hospedar_vencida(self, dias=2, offset=-5, uh=None):
        r = self.reserva(status=Reserva.Status.CONFIRMADA, dias=dias, offset=offset, uh=uh)
        r.fazer_checkin(self.usuario)
        return r

    def test_com_saldo_entra_em_com_saldo(self):
        r = self._hospedar_vencida()  # diárias em aberto
        res = services.saidas_vencidas()
        self.assertIn(r, res["com_saldo"])
        self.assertNotIn(r, res["quitadas"])
        self.assertEqual(res["total_aberto"], r.conta.saldo())

    def test_quitada_entra_em_quitadas(self):
        self.abrir_caixa()
        r = self._hospedar_vencida()
        services.receber_pagamento(r.conta, self.usuario, self.dinheiro, r.conta.saldo())
        res = services.saidas_vencidas()
        self.assertIn(r, res["quitadas"])
        self.assertNotIn(r, res["com_saldo"])

    def test_dentro_do_prazo_nao_aparece(self):
        r = self.reserva(status=Reserva.Status.CONFIRMADA, dias=3, offset=-1)
        r.fazer_checkin(self.usuario)  # saída amanhã, ainda não venceu
        res = services.saidas_vencidas()
        self.assertNotIn(r, res["com_saldo"])
        self.assertNotIn(r, res["quitadas"])

    def test_helper_nao_altera_status(self):
        r = self._hospedar_vencida()
        services.saidas_vencidas()
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)


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


class TarifaUnidadeTests(ReservasTestsBase):
    """Tarifa por unidade (Passo 3): duplo cobra mais, override vence, mínimo real."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import PosicaoCama
        # self.uh (T1) é simples; cria um duplo do mesmo tipo (base 300 → 480).
        self.duplo = UH.objects.create(numero="T-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)

    def test_simples_fica_na_base_do_tipo(self):
        self.assertEqual(services.tarifa_da_unidade(self.uh, HOJE), Decimal("300.00"))

    def test_duplo_recebe_acrescimo_arredondado(self):
        # 300 × 1.6 = 480, arredondado à dezena.
        self.assertEqual(services.tarifa_da_unidade(self.duplo, HOJE), Decimal("480"))

    def test_override_vence_o_calculo(self):
        self.duplo.tarifa_override = Decimal("399.00")
        self.duplo.save()
        self.assertEqual(services.tarifa_da_unidade(self.duplo, HOJE), Decimal("399.00"))

    def test_tarifa_minima_do_tipo_e_o_menor_real(self):
        # Tipo tem o simples (300) e o duplo (480) → mínimo real = 300.
        self.assertEqual(services.tarifa_minima_do_tipo(self.tipo), Decimal("300.00"))

    def test_tarifa_minima_nunca_abaixo_de_qualquer_unidade(self):
        # Se todas as unidades são duplas, o "a partir de" não pode ser a base 300.
        self.uh.delete()  # sobra só o duplo
        self.assertEqual(services.tarifa_minima_do_tipo(self.tipo), Decimal("480"))


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
        # Saldo zerado é o único requisito de saída (sem trava de frigobar).
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

    def test_checkout_so_depende_do_saldo(self):
        # Não há consumo de frigobar: com a conta zerada, a saída é liberada.
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


class ColchaoExtraTests(ReservasTestsBase):
    """Colchão extra: quantidade, cotação itemizada e lançamento na conta (Passo 4)."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ConfiguracaoUH, PosicaoCama
        # Duplo com sofá e 2 colchões: incluído = 4 (fixa) + 1 (sofá) = 5.
        self.duplo = UH.objects.create(numero="T-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(
            uh=self.duplo, tem_sofa_cama=True, max_colchoes_extras=2,
            tarifa_colchao_extra=Decimal("80.00"),
        )

    def test_extras_para_dentro_da_capacidade_e_zero(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 5), 0)  # cabe nas camas incluídas

    def test_extras_para_limitado_ao_maximo(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 7), 2)   # 7-5=2
        self.assertEqual(extras_para(self.duplo, 12), 2)  # nunca acima do máximo

    def test_extras_para_nunca_negativo(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 1), 0)

    def test_cotacao_itemiza_colchao_separado_das_diarias(self):
        cot = services.cotacao_unidade(
            self.duplo, HOJE, HOJE + timedelta(days=2), pessoas=7
        )
        # duplo base 300 → diária 480; 2 noites = 960 de diárias.
        self.assertEqual(cot["total_diarias"], Decimal("960"))
        # 2 colchões × 80 × 2 noites = 320, em linha própria.
        self.assertEqual(cot["colchoes_qtd"], 2)
        self.assertEqual(cot["colchoes_total"], Decimal("320.00"))
        self.assertEqual(cot["bruto"], Decimal("1280.00"))

    def test_cotacao_cruzando_duas_temporadas(self):
        from apps.nucleo.models import Temporada
        Temporada.objects.create(
            nome="Feriadão", classificacao="feriado", inicio=HOJE, fim=HOJE,
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="feriado", valor=Decimal("500.00")
        )
        # Noite 1: feriado 500 → duplo 800; noite 2: base 300 → duplo 480. = 1280.
        cot = services.cotacao_unidade(
            self.duplo, HOJE, HOJE + timedelta(days=2), pessoas=5
        )
        self.assertEqual(cot["total_diarias"], Decimal("1280"))
        self.assertEqual(cot["colchoes_qtd"], 0)
        self.assertEqual(cot["bruto"], Decimal("1280"))

    def test_checkin_lanca_colchao_na_conta(self):
        r = self.reserva(uh=self.duplo, dias=2)
        r.adultos, r.criancas = 6, 1  # 7 pessoas → 2 colchões
        r.save()
        conta = r.fazer_checkin(self.usuario)
        linha = conta.lancamentos.filter(descricao__startswith="Colchão extra").first()
        self.assertIsNotNone(linha)
        self.assertEqual(linha.descricao, "Colchão extra · 2 unidades · 2 noites")
        self.assertEqual(linha.valor, Decimal("320.00"))
        self.assertEqual(linha.tipo, LancamentoConta.Tipo.SERVICO)

    def test_checkin_sem_excesso_nao_lanca_colchao(self):
        r = self.reserva(uh=self.duplo, dias=2)
        r.adultos, r.criancas = 4, 0  # cabe → sem colchão
        r.save()
        conta = r.fazer_checkin(self.usuario)
        self.assertFalse(
            conta.lancamentos.filter(descricao__startswith="Colchão extra").exists()
        )

    def test_colchoes_extras_service_para_governanca(self):
        r = self.reserva(uh=self.duplo, dias=1)
        r.adultos, r.criancas = 5, 2  # 7 → 2
        r.save()
        self.assertEqual(services.colchoes_extras(r), 2)


class GrupoReservaTests(ReservasTestsBase):
    """Reserva-mãe com filhas por quarto e folio híbrido (Passo 5)."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ConfiguracaoUH, PosicaoCama
        # Frigobar não é o foco aqui; desliga o bloqueio de check-out por conferência.
        ModuloContratado.objects.filter(codigo=Modulo.FRIGOBAR).update(ativo=False)
        self.qa = UH.objects.create(numero="G-A", tipo=self.tipo)
        self.qb = UH.objects.create(numero="G-B", tipo=self.tipo)
        # Duplo com sofá + 2 colchões para testar o colchão no folio-mãe.
        self.duplo = UH.objects.create(numero="G-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(
            uh=self.duplo, tem_sofa_cama=True, max_colchoes_extras=2,
            tarifa_colchao_extra=Decimal("80.00"),
        )
        self.h2 = Pessoa.objects.create(nome="João Bloco")
        self.h3 = Pessoa.objects.create(nome="Ana Bloco")

    def _grupo(self, dias=2):
        return services.criar_grupo(
            rotulo="Grupo Teste", titular=self.hospede,
            checkin=HOJE, checkout=HOJE + timedelta(days=dias), usuario=self.usuario,
        )

    def test_criar_grupo_abre_folio(self):
        grupo = self._grupo()
        self.assertTrue(hasattr(grupo, "folio"))
        self.assertIsNone(grupo.folio.reserva_id)

    def test_contas_abertas_ignora_folio_de_grupo(self):
        """O folio-mãe é conta aberta SEM reserva; não pode aparecer em
        contas_abertas() — senão os PDVs quebram em c.reserva.uh (crash 500)."""
        grupo = self._grupo()
        pks = [c.pk for c in services.contas_abertas()]
        self.assertNotIn(grupo.folio.pk, pks)
        for c in services.contas_abertas():
            self.assertIsNotNone(c.reserva)  # c.reserva.uh nunca estoura

    def test_adicionar_quartos_e_antioverbooking(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        self.assertEqual(grupo.filhas.count(), 2)
        self.assertEqual(f1.grupo_id, grupo.pk)
        # O mesmo quarto no mesmo período é recusado.
        with self.assertRaises(ValidationError):
            services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h3, usuario=self.usuario)

    def test_diaria_no_folio_consumo_no_quarto(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        grupo.refresh_from_db()
        # 2 noites × 300 no folio-mãe; conta do quarto começa zerada.
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("600.00"))
        self.assertEqual(f1.conta.total_lancamentos(), Decimal("0.00"))
        # Consumo vai para a conta do quarto, não para o folio.
        from apps.nucleo.models import NaturezaFiscal
        services.lancar_na_conta(
            f1.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Frigobar", Decimal("50.00"), self.usuario,
        )
        self.assertEqual(f1.conta.total_lancamentos(), Decimal("50.00"))
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("600.00"))

    def test_colchao_extra_vai_ao_folio_mae(self):
        grupo = self._grupo()
        f = services.adicionar_quarto(
            grupo, uh=self.duplo, hospede=self.h2, usuario=self.usuario,
            adultos=6, criancas=1,  # 7 pessoas → 2 colchões
        )
        services.confirmar_grupo(grupo.pk, self.usuario)
        f.refresh_from_db()
        f.fazer_checkin(self.usuario)
        # duplo: diária 480 × 2 = 960; colchão 2×80×2 = 320 → folio 1280.
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("1280.00"))
        self.assertTrue(
            grupo.folio.lancamentos.filter(descricao__startswith="Colchão extra").exists()
        )
        self.assertEqual(f.conta.total_lancamentos(), Decimal("0.00"))

    def test_checkout_quarto_com_folio_aberto(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        from apps.nucleo.models import NaturezaFiscal
        services.lancar_na_conta(
            f1.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Frigobar", Decimal("50.00"), self.usuario,
        )
        self.abrir_caixa()
        services.receber_pagamento(f1.conta, self.usuario, self.dinheiro, Decimal("50.00"))
        # Check-out do quarto passa mesmo com o folio-mãe (diárias) aberto.
        f1.fazer_checkout(self.usuario)
        f1.refresh_from_db()
        self.assertEqual(f1.status, Reserva.Status.CHECKOUT)
        self.assertTrue(grupo.folio.aberta)

    def test_confirmar_grupo_confirma_todas(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CONFIRMADA).count(), 2
        )
        grupo.refresh_from_db()
        self.assertIsNone(grupo.expira_em)

    def test_cancelar_grupo_cascata(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.cancelar_grupo(grupo, self.usuario, "Cliente desistiu")
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CANCELADA).count(), 2
        )

    def test_remover_do_grupo_encolhe(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.remover_do_grupo(f1, self.usuario, "Um quarto a menos")
        f1.refresh_from_db()
        self.assertEqual(f1.status, Reserva.Status.CANCELADA)
        self.assertEqual(grupo.filhas_ativas.count(), 1)

    def test_encerrar_grupo_exige_folio_zerado(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        f1.fazer_checkout(self.usuario)  # sem consumo, conta do quarto zerada
        # Folio tem as diárias em aberto → encerrar recusa.
        with self.assertRaises(ValidationError):
            services.encerrar_grupo(grupo, self.usuario)
        # Recebe o folio e encerra.
        self.abrir_caixa()
        services.receber_folio_grupo(
            grupo, self.usuario, self.dinheiro, grupo.folio.saldo()
        )
        services.encerrar_grupo(grupo, self.usuario)
        grupo.refresh_from_db()
        self.assertIsNotNone(grupo.encerrado_em)
        self.assertFalse(grupo.folio.aberta)

    def test_expirar_grupos_vencidos(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        grupo.expira_em = timezone.now() - timedelta(minutes=1)
        grupo.save()
        self.assertEqual(services.expirar_grupos_vencidos(), 1)
        self.assertEqual(grupo.filhas_ativas.count(), 0)

    @override_settings(PAGAMENTOS_GATEWAY="simulado")
    def test_sinal_unico_confirma_grupo_via_pagamentos(self):
        from apps.pagamentos.models import Cobranca
        from apps.pagamentos.services import confirmar_pagamento, criar_cobranca
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        cobranca = criar_cobranca(
            self.usuario, valor=Decimal("500.00"), metodo=Cobranca.Metodo.PIX,
            descricao="Sinal do grupo", finalidade=Cobranca.Finalidade.SINAL,
            pagador=self.hospede, grupo_id=grupo.pk,
        )
        confirmar_pagamento(cobranca, self.usuario, origem="teste")
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CONFIRMADA).count(), 2
        )


@override_settings(FNRH_BLOQUEAR_CHECKIN=True)
class FNRHTests(ReservasTestsBase):
    """Ficha Nacional de Registro de Hóspedes: preparo, prefill e trava de check-in."""

    def setUp(self):
        super().setUp()
        self.hospede.documento = "111.222.333-44"
        self.hospede.cidade = "Itá"
        self.hospede.uf = "SC"
        self.hospede.save()

    def _preencher_todas(self, r):
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Acompanhante"
            f.nascimento = HOJE - timedelta(days=365 * 30)
            f.documento_numero = "123456"
            f.cidade = "Itá"
            f.motivo_viagem = "LAZER_FERIAS"
            f.save()

    def test_garantir_cria_titular_pre_preenchido_e_slots(self):
        r = self.reserva()  # adultos=2 → total_hospedes=2
        services.garantir_fichas_fnrh(r)
        self.assertEqual(r.fichas_fnrh.count(), 2)
        titular = r.fichas_fnrh.get(titular=True)
        self.assertEqual(titular.nome, self.hospede.nome)
        self.assertEqual(titular.cidade, "Itá")  # veio do cadastro
        # Idempotente: chamar de novo não duplica.
        services.garantir_fichas_fnrh(r)
        self.assertEqual(r.fichas_fnrh.count(), 2)

    def test_checkin_bloqueado_sem_fnrh(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            r.fazer_checkin(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CONFIRMADA)

    def test_checkin_liberado_com_fnrh_completa(self):
        r = self.reserva()
        self._preencher_todas(r)
        self.assertTrue(r.fnrh_pronta)
        conta = r.fazer_checkin(self.usuario)
        self.assertIsNotNone(conta)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)

    def test_falta_ficha_de_acompanhante_ainda_bloqueia(self):
        r = self.reserva()  # 2 hóspedes
        services.garantir_fichas_fnrh(r)
        # Preenche só o titular; acompanhante fica pendente.
        titular = r.fichas_fnrh.get(titular=True)
        titular.nascimento = HOJE - timedelta(days=365 * 30)
        titular.documento_numero = "999"
        titular.motivo_viagem = "LAZER_FERIAS"
        titular.save()
        self.assertFalse(r.fnrh_pronta)
        with self.assertRaises(ValidationError):
            r.fazer_checkin(self.usuario)

    def test_um_unico_titular_por_reserva(self):
        from apps.reservas.models import FichaFNRH
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FichaFNRH.objects.create(reserva=r, titular=True, nome="Duplo")


class BOHTests(ReservasTestsBase):
    """Boletim de Ocupação Hoteleira — agregação da FNRH + ocupação e export CSV."""

    def _hospeda_com_fnrh(self, uf="SC", motivo="LAZER_FERIAS", transporte="AUTOMOVEL"):
        r = self.reserva()  # checkin=HOJE, adultos=2
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Y"
            f.nascimento = HOJE - timedelta(days=365 * 25)
            f.documento_numero = "555"
            f.cidade = "Itá"
            f.uf = uf
            f.pais = "Brasil"
            f.motivo_viagem = motivo
            f.meio_transporte = transporte
            f.save()
        r.fazer_checkin(self.usuario)  # base tem a trava desligada
        return r

    def test_agrega_procedencia_motivo_transporte(self):
        self._hospeda_com_fnrh()
        boh = services.boh_mensal(HOJE.year, HOJE.month)
        self.assertEqual(boh["total_hospedes"], 2)
        self.assertEqual(boh["total_chegadas"], 1)
        self.assertIn(("SC", 2), boh["nacional"])
        self.assertEqual(dict(boh["motivo"]).get("Turismo / lazer / férias"), 2)
        self.assertEqual(dict(boh["transporte"]).get("Automóvel"), 2)
        self.assertGreater(boh["uh_noites_ocupadas"], 0)

    def test_estrangeiro_vai_para_internacional(self):
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome, f.nascimento = "Tourist", HOJE - timedelta(days=365 * 40)
            f.documento_numero, f.cidade = "P123", "Buenos Aires"
            f.pais, f.motivo_viagem = "Argentina", "LAZER_FERIAS"
            f.save()
        r.fazer_checkin(self.usuario)
        boh = services.boh_mensal(HOJE.year, HOJE.month)
        self.assertIn(("Argentina", 2), boh["internacional"])

    def test_export_csv(self):
        self._hospeda_com_fnrh()
        self.client.login(username="recepcao", password="senha-forte-123")
        resp = self.client.get(
            reverse("reservas:boh") + f"?ano={HOJE.year}&mes={HOJE.month}&formato=csv"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        corpo = resp.content.decode("utf-8")
        self.assertIn("Boletim de Ocupação Hoteleira", corpo)
        self.assertIn("Motivo da viagem", corpo)


class EnvioFNRHTests(ReservasTestsBase):
    """Push à FNRH Digital via gateway simulado (estratégia B)."""

    def _hospeda_completa(self):
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Z"
            f.nascimento = HOJE - timedelta(days=365 * 28)
            f.documento_numero = "321"
            f.cidade, f.uf, f.pais = "Itá", "SC", "Brasil"
            f.motivo_viagem, f.meio_transporte = "LAZER_FERIAS", "AUTOMOVEL"
            f.save()
        r.fazer_checkin(self.usuario)
        return r

    def test_checkin_marca_pendente(self):
        r = self._hospeda_completa()
        self.assertEqual(r.fnrh_status, Reserva.SincFNRH.PENDENTE)

    def test_envio_simulado_marca_enviada_com_ids(self):
        r = self._hospeda_completa()
        self.assertTrue(services.enviar_fnrh(r))
        r.refresh_from_db()
        self.assertEqual(r.fnrh_status, Reserva.SincFNRH.ENVIADA)
        self.assertIsNotNone(r.fnrh_reserva_id)
        for f in r.fichas_fnrh.all():
            self.assertIsNotNone(f.fnrh_pessoa_id)
            self.assertIsNotNone(f.fnrh_hospede_id)

    def test_envio_idempotente(self):
        r = self._hospeda_completa()
        services.enviar_fnrh(r)
        r.refresh_from_db()
        rid = r.fnrh_reserva_id
        self.assertTrue(services.enviar_fnrh(r))  # 2ª vez não refaz
        r.refresh_from_db()
        self.assertEqual(r.fnrh_reserva_id, rid)

    def test_pendentes_qs_e_reenvio(self):
        r = self._hospeda_completa()
        self.assertIn(r, services.fnrh_pendentes_qs())
        services.enviar_fnrh(r)
        self.assertNotIn(r, services.fnrh_pendentes_qs())

    def test_depara_dominios(self):
        from apps.reservas import fnrh_gateway
        r = self._hospeda_completa()
        ficha = r.fichas_fnrh.first()
        p = fnrh_gateway.payload_hospede(ficha, pessoa_id="x")
        self.assertEqual(p["fnrh"]["motivo_viagem_id"], "LAZER_FERIAS")
        self.assertEqual(p["fnrh"]["meio_transporte_id"], "AUTOMOVEL")
        self.assertEqual(fnrh_gateway.payload_reserva(r)["origem_reserva_id"], "MEIOHOSPEDAGEM")

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, ModuloContratado, Pessoa, TipoUH, TrilhaAuditoria
from apps.nucleo.modulos import Modulo

from . import services
from .models import Cobranca, EventoPagamento

Usuario = get_user_model()


@override_settings(PAGAMENTOS_GATEWAY="simulado")
class PagamentosBase(TestCase):
    """Base fixa no sandbox — a suíte não pode depender do .env do dev nem bater
    na API real do Safrapay. Testes de provider trocam o gateway com override
    inline (criam a cobrança no simulado e só então apontam p/ safrapay)."""

    def setUp(self):
        # Rate limit usa cache (LocMemCache persiste no processo) — zera para os
        # testes não contaminarem uns aos outros.
        from django.core.cache import cache
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="cx", password="senha-forte-123")

    def cobranca(self, **kw):
        base = dict(valor=Decimal("100.00"), metodo="pix", descricao="Teste")
        base.update(kw)
        return services.criar_cobranca(self.op, **base)


class CobrancaTests(PagamentosBase):
    def test_criar_gera_dados_do_gateway(self):
        c = self.cobranca(metodo="pix")
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)
        self.assertTrue(c.gateway_id)
        self.assertTrue(c.pix_copia_cola)
        self.assertTrue(EventoPagamento.objects.filter(cobranca=c, tipo="criada").exists())

    def test_valor_invalido(self):
        with self.assertRaises(ValidationError):
            services.criar_cobranca(self.op, valor=0, metodo="pix", descricao="x")

    def test_confirmar_idempotente(self):
        c = self.cobranca()
        services.confirmar_pagamento(c, self.op)
        services.confirmar_pagamento(c, self.op)  # 2ª vez não duplica
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)
        self.assertEqual(EventoPagamento.objects.filter(cobranca=c, tipo="paga").count(), 1)

    def test_estorno_exige_pago_e_audita(self):
        c = self.cobranca()
        with self.assertRaises(ValidationError):
            services.estornar(c, self.op)  # ainda pendente
        services.confirmar_pagamento(c, self.op)
        services.estornar(c, self.op)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.ESTORNADO)
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="estorno_pagamento").exists())


class ConciliacaoTests(PagamentosBase):
    def test_liquidar_exige_pago_e_calcula_taxa(self):
        c = self.cobranca(valor=Decimal("100.00"))
        with self.assertRaises(ValidationError):
            services.registrar_liquidacao(c, valor_liquido=Decimal("98"))  # pendente
        services.confirmar_pagamento(c, self.op)
        services.registrar_liquidacao(c, valor_liquido=Decimal("98.00"),
                                      data_liquidacao=timezone.localdate(), id_liquidacao="DEP-1")
        c.refresh_from_db()
        self.assertTrue(c.liquidado)
        self.assertEqual(c.valor_liquido, Decimal("98.00"))
        self.assertEqual(c.taxa, Decimal("2.00"))  # bruto − líquido
        self.assertEqual(c.id_liquidacao, "DEP-1")
        self.assertEqual(
            EventoPagamento.objects.filter(cobranca=c, tipo="liquidada").count(), 1)

    def test_liquidar_idempotente(self):
        c = self.cobranca()
        services.confirmar_pagamento(c, self.op)
        services.registrar_liquidacao(c, valor_liquido=Decimal("95"))
        services.registrar_liquidacao(c, valor_liquido=Decimal("95"))  # 2ª vez
        self.assertEqual(
            EventoPagamento.objects.filter(cobranca=c, tipo="liquidada").count(), 1)

    def test_webhook_captura_liquidacao(self):
        import json
        c = self.cobranca()
        services.confirmar_pagamento(c, self.op)  # já paga
        r = self.client.post(
            reverse("pagamentos:webhook"),
            data=json.dumps({"charge": {
                "id": c.gateway_id, "chargeStatus": "Paid",
                "netAmount": 9550, "feeAmount": 450,  # centavos → 95,50 / 4,50
                "settlementDate": "2026-08-01", "settlementId": "LOTE-9",
            }}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertTrue(c.liquidado)
        self.assertEqual(c.valor_liquido, Decimal("95.50"))
        self.assertEqual(c.taxa, Decimal("4.50"))
        self.assertEqual(c.id_liquidacao, "LOTE-9")

    def test_recebimentos_totais(self):
        c1 = self.cobranca(valor=Decimal("100"))
        services.confirmar_pagamento(c1, self.op)
        services.registrar_liquidacao(c1, valor_liquido=Decimal("97"))
        c2 = self.cobranca(valor=Decimal("50"))
        services.confirmar_pagamento(c2, self.op)  # pago, não liquidado
        _lista, totais = services.recebimentos(status=Cobranca.Status.PAGO)
        self.assertEqual(totais["recebido"], Decimal("150"))
        self.assertEqual(totais["liquidado_qtd"], 1)
        self.assertEqual(totais["a_liquidar_qtd"], 1)

    def test_tela_conciliacao_abre(self):
        self.client.login(username="cx", password="senha-forte-123")
        r = self.client.get(reverse("pagamentos:conciliacao"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conciliação")


class IntegracaoReservaTests(PagamentosBase):
    def test_sinal_pago_confirma_reserva(self):
        from apps.reservas.models import Reserva
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Quarto 01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje + timedelta(days=3),
            checkout=hoje + timedelta(days=5), status=Reserva.Status.PRE_RESERVA,
            valor_diaria=Decimal("200"), criado_por=self.op,
        )
        c = self.cobranca(finalidade="sinal_reserva", reserva_id=r.pk)
        services.confirmar_pagamento(c, self.op)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CONFIRMADA)


class WebhookTests(PagamentosBase):
    def test_webhook_confirma_pela_gateway_id(self):
        c = self.cobranca()
        r = self.client.post(reverse("pagamentos:webhook"), {"gateway_id": c.gateway_id})
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def test_webhook_id_desconhecido(self):
        r = self.client.post(reverse("pagamentos:webhook"), {"gateway_id": "NAO-EXISTE"})
        self.assertEqual(r.status_code, 404)

    def test_pagina_publica_e_botao_ja_paguei(self):
        c = self.cobranca()
        # página pública abre sem login
        r = self.client.get(reverse("pagamentos:pagar", args=[c.token]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "voltar ao site")
        self.client.post(reverse("pagamentos:pagar_simular", args=[c.token]))
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)
        r = self.client.get(reverse("pagamentos:pagar", args=[c.token]))
        self.assertContains(r, "Pagamento confirmado")
        self.assertContains(r, "Voltar ao site")

    def test_ja_paguei_sinal_site_redireciona_recibo(self):
        from apps.reservas.models import Reserva
        from apps.site.models import CategoriaQuarto, Hospede, Quarto
        from apps.site.models import Reserva as SiteReserva
        tipo = TipoUH.objects.create(nome="Pay", tarifa_base=Decimal("100"))
        uh = UH.objects.create(numero="P1", tipo=tipo)
        pessoa = Pessoa.objects.create(nome="Pagador")
        hoje = timezone.localdate()
        crm = Reserva.objects.create(
            uh=uh, hospede=pessoa, checkin=hoje + timedelta(days=2),
            checkout=hoje + timedelta(days=3), status=Reserva.Status.PRE_RESERVA,
            valor_diaria=Decimal("100"), criado_por=self.op,
        )
        cat = CategoriaQuarto.objects.create(nome="C")
        quarto = Quarto.objects.create(
            nome="Q", categoria=cat, descricao="x", descricao_curta="x",
            capacidade=2, metragem=10, preco_base=Decimal("100"),
            status="disponivel", tipo_uh=tipo,
        )
        h = Hospede.objects.create(nome="H", email="pay@ex.com", telefone="49991112233", cpf="11144477735")
        site = SiteReserva.objects.create(
            hospede=h, quarto=quarto, data_checkin=crm.checkin, data_checkout=crm.checkout,
            num_hospedes=1, preco_noite=Decimal("100"), status="aguardando",
            crm_reserva_id=crm.pk,
        )
        c = self.cobranca(finalidade="sinal_reserva", reserva_id=crm.pk)
        site.pagamento_id = str(c.token)
        site.save(update_fields=["pagamento_id"])
        r = self.client.post(reverse("pagamentos:pagar_simular", args=[c.token]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(str(site.token), r["Location"])


class PermissaoTests(PagamentosBase):
    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.PAGAMENTOS).update(ativo=False)
        self.client.login(username="cx", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("pagamentos:painel")).status_code, 404)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("pagamentos:painel")).status_code, 403)


class SafrapayGatewayTests(PagamentosBase):
    def test_sem_token_recusa_criar(self):
        from django.test import override_settings

        from .gateways import GatewaySafrapay
        c = self.cobranca()  # criada no simulado
        with override_settings(
            PAGAMENTOS_GATEWAY="safrapay",
            SAFRAPAY_TOKEN="",
            SAFRAPAY_GATEWAY_URL="https://payment-hml.safrapay.com.br",
        ):
            with self.assertRaises(ValidationError) as ctx:
                GatewaySafrapay().criar_cobranca(c)
            self.assertIn("Token ausente", str(ctx.exception))

    def test_checklist_e_tela(self):
        from .gateways import status_credenciais
        st = status_credenciais()
        self.assertIn("token_ok", st)
        self.client.login(username="cx", password="senha-forte-123")
        r = self.client.get(reverse("pagamentos:safrapay"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SAFRAPAY_TOKEN")

    def test_webhook_json_safrapay(self):
        import json
        c = self.cobranca()
        r = self.client.post(
            reverse("pagamentos:webhook"),
            data=json.dumps({"charge": {"id": c.gateway_id, "status": "Captured"}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def test_webhook_paid_8_confirma(self):
        import json
        c = self.cobranca()
        r = self.client.post(
            reverse("pagamentos:webhook"),
            data=json.dumps({"charge": {"id": c.gateway_id, "status": 8}}),  # 8 = Paid
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def test_webhook_negado_nao_confirma(self):
        import json
        c = self.cobranca()
        r = self.client.post(
            reverse("pagamentos:webhook"),
            data=json.dumps({"charge": {"id": c.gateway_id, "status": 3}}),  # 3 = Denied
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)  # fail-safe: NÃO confirma

    def test_ja_paguei_gateway_real_nao_confirma_se_pendente(self):
        """No gateway real, 'Já paguei' consulta o status verdadeiro; se ainda
        pendente (ex.: Pix não pago), NÃO confirma — sem confirmar no escuro."""
        from unittest.mock import patch
        c = self.cobranca()  # criada no simulado
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"), patch(
            "apps.pagamentos.gateways.GatewaySafrapay.consultar_status",
            return_value={"status_raw": "PreAuthorized"},
        ):
            self.client.post(reverse("pagamentos:pagar_simular", args=[c.token]))
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)

    def test_ja_paguei_gateway_real_confirma_se_pago(self):
        """No gateway real, 'Já paguei' confirma quando o status verdadeiro é pago."""
        from unittest.mock import patch
        c = self.cobranca()
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"), patch(
            "apps.pagamentos.gateways.GatewaySafrapay.consultar_status",
            return_value={"status_raw": "Captured"},
        ):
            self.client.post(reverse("pagamentos:pagar_simular", args=[c.token]))
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def test_webhook_safrapay_preautorizado_nao_confirma(self):
        """Shape REAL do Safrapay: chargeStatus=PreAuthorized + transactionStatus=
        PendingPayment (Pix criado, ainda não pago) NÃO pode confirmar a cobrança."""
        import json

        from django.test import override_settings
        c = self.cobranca()
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"):
            r = self.client.post(
                reverse("pagamentos:webhook"),
                data=json.dumps({"charge": {
                    "id": c.gateway_id,
                    "chargeStatus": "PreAuthorized",
                    "transactions": [{"transactionStatus": "PendingPayment"}],
                }}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)  # fail-safe

    def test_webhook_safrapay_sem_status_fora_do_sandbox_nao_confirma(self):
        """Webhook real (gateway=safrapay) sem status reconhecível não confirma no escuro."""
        import json

        from django.test import override_settings
        c = self.cobranca()
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"):
            r = self.client.post(
                reverse("pagamentos:webhook"),
                data=json.dumps({"charge": {"id": c.gateway_id}}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)

    def test_webhook_safrapay_chargestatus_captured_confirma(self):
        """chargeStatus de pago (Captured) confirma via o campo real do Safrapay."""
        import json
        c = self.cobranca()
        r = self.client.post(
            reverse("pagamentos:webhook"),
            data=json.dumps({"charge": {"id": c.gateway_id, "chargeStatus": "Captured"}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def test_sinal_pago_sincroniza_recibo_site(self):
        from apps.reservas.models import Reserva
        from apps.site.models import CategoriaQuarto, Hospede, Quarto
        from apps.site.models import Reserva as SiteReserva
        tipo = TipoUH.objects.create(nome="Std2", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Q-99", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede Site")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje + timedelta(days=3),
            checkout=hoje + timedelta(days=5), status=Reserva.Status.PRE_RESERVA,
            valor_diaria=Decimal("200"), criado_por=self.op,
        )
        cat = CategoriaQuarto.objects.create(nome="Cat")
        quarto = Quarto.objects.create(
            nome="Q", categoria=cat, descricao="x", descricao_curta="x",
            capacidade=2, metragem=20, preco_base=Decimal("200"),
            status="disponivel", tipo_uh=tipo,
        )
        h = Hospede.objects.create(nome="H", email="h@ex.com", telefone="1", cpf="11144477735")
        site = SiteReserva.objects.create(
            hospede=h, quarto=quarto, data_checkin=r.checkin, data_checkout=r.checkout,
            num_hospedes=1, preco_noite=Decimal("200"), status="aguardando",
            crm_reserva_id=r.pk,
        )
        c = self.cobranca(finalidade="sinal_reserva", reserva_id=r.pk)
        services.confirmar_pagamento(c, self.op)
        site.refresh_from_db()
        self.assertEqual(site.status, "confirmada")


@override_settings(PAGAMENTOS_GATEWAY="simulado")
class CartaoOnlineTests(PagamentosBase):
    """Captura e autorização de cartão na página pública (crédito à vista)."""

    def test_autorizar_cartao_aprova_e_confirma(self):
        cb = self.cobranca(metodo="cartao")
        card = {
            "cardholderName": "FULANO TESTE", "cardNumber": "4111111111111111",
            "expirationMonth": 12, "expirationYear": 2030, "securityCode": "123",
        }
        ok, _ = services.autorizar_cartao_online(cb, card, usuario=self.op)
        cb.refresh_from_db()
        self.assertTrue(ok)
        self.assertEqual(cb.status, Cobranca.Status.PAGO)

    def test_cartao_recusado_nao_confirma(self):
        """REGRESSÃO: gateway aceita a requisição (HTTP 200) mas RECUSA a transação
        (chargeStatus=NotAuthorized/Denied) → NÃO pode marcar pago."""
        from unittest.mock import patch
        cb = self.cobranca(metodo="cartao")

        class GwRecusa:
            def autorizar_cartao(self, cobranca, card):
                return {"gateway_id": "GID-RECUSADO", "status_raw": "Denied",
                        "payload": {"safrapay": {"charge": {"chargeStatus": "NotAuthorized"}}}}

        with patch("apps.pagamentos.services.get_gateway", return_value=GwRecusa()):
            ok, msg = services.autorizar_cartao_online(cb, {"cardNumber": "4"}, usuario=self.op)
        cb.refresh_from_db()
        self.assertFalse(ok)
        self.assertIn("não autoriz", msg.lower())
        self.assertEqual(cb.status, Cobranca.Status.PENDENTE)  # continua pendente

    def test_status_pago_mapeia_corretamente(self):
        from apps.pagamentos.gateways import status_pago
        self.assertIs(status_pago("Captured"), True)
        self.assertIs(status_pago("Paid"), True)
        self.assertIs(status_pago("Denied"), False)
        self.assertIs(status_pago("NotAuthorized"), False)
        self.assertIs(status_pago("PreAuthorized"), False)   # criado, não pago
        self.assertIsNone(status_pago(""))                   # desconhecido → fail-safe
        self.assertIsNone(status_pago("QualquerCoisa"))

    def test_pan_nunca_persistido(self):
        cb = self.cobranca(metodo="cartao")
        services.autorizar_cartao_online(
            cb, {"cardholderName": "X", "cardNumber": "4111111111111111",
                 "expirationMonth": 1, "expirationYear": 2031, "securityCode": "999"},
            usuario=self.op,
        )
        cb.refresh_from_db()
        self.assertNotIn("card", cb.payload)
        self.assertNotIn("4111111111111111", str(cb.payload))

    def test_view_pagar_cartao_fluxo_completo(self):
        cb = self.cobranca(metodo="cartao")
        resp = self.client.post(
            reverse("pagamentos:pagar_cartao", args=[cb.token]),
            {"nome": "Fulano Teste", "numero": "4111 1111 1111 1111",
             "validade": "12/30", "cvv": "123", "documento": "111.444.777-35"},
        )
        self.assertEqual(resp.status_code, 302)
        cb.refresh_from_db()
        self.assertEqual(cb.status, Cobranca.Status.PAGO)

    def test_validade_invalida_nao_cobra(self):
        cb = self.cobranca(metodo="cartao")
        self.client.post(
            reverse("pagamentos:pagar_cartao", args=[cb.token]),
            {"nome": "X", "numero": "4111111111111111", "validade": "xx", "cvv": "123"},
        )
        cb.refresh_from_db()
        self.assertEqual(cb.status, Cobranca.Status.PENDENTE)


class WebhookSegurancaTests(PagamentosBase):
    """TM-001: fora do sandbox, o webhook não confia no corpo — consulta a fonte."""

    def test_webhook_forjado_nao_confirma_no_gateway_real(self):
        from unittest.mock import patch
        c = self.cobranca()
        c.gateway_id = "VT-REAL-1"
        c.save(update_fields=["gateway_id"])
        # Atacante manda status=paid; o provedor diz que está pendente.
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"), patch(
            "apps.pagamentos.gateways.GatewaySafrapay.consultar_status",
            return_value={"status_raw": "pending"},
        ):
            r = self.client.post(
                reverse("pagamentos:webhook"),
                {"gateway_id": "VT-REAL-1", "status": "paid"},
            )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PENDENTE)  # NÃO confirmou

    def test_webhook_confirma_quando_provedor_confirma(self):
        from unittest.mock import patch
        c = self.cobranca()
        c.gateway_id = "VT-REAL-2"
        c.save(update_fields=["gateway_id"])
        with override_settings(PAGAMENTOS_GATEWAY="safrapay"), patch(
            "apps.pagamentos.gateways.GatewaySafrapay.consultar_status",
            return_value={"status_raw": "paid"},
        ):
            r = self.client.post(
                reverse("pagamentos:webhook"),
                {"gateway_id": "VT-REAL-2", "status": "whatever"},
            )
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)


class RateLimitTests(PagamentosBase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def test_cartao_bloqueia_apos_tentativas(self):
        c = self.cobranca(metodo="cartao")
        url = reverse("pagamentos:pagar_cartao", args=[c.token])
        dados = {"nome": "X", "numero": "1", "validade": "xx", "cvv": "1"}  # inválido de propósito
        # 5 permitidas; a 6ª é barrada pelo rate limit por token.
        for _ in range(5):
            self.client.post(url, dados)
        r = self.client.post(url, dados, follow=True)
        self.assertContains(r, "Muitas tentativas")

    def test_webhook_bloqueia_flood(self):
        c = self.cobranca()
        url = reverse("pagamentos:webhook")
        codigo = 200
        for _ in range(61):
            codigo = self.client.post(url, {"gateway_id": c.gateway_id}).status_code
        self.assertEqual(codigo, 429)  # passou de 60/min


class RedacaoWebhookTests(PagamentosBase):
    """TM-004: o corpo do webhook é redigido antes de virar trilha (sem PAN/PII)."""

    def test_cartao_e_pii_redigidos_no_evento(self):
        import json as _json
        c = self.cobranca()
        corpo = {
            "charge": {
                "id": c.gateway_id, "chargeStatus": "paid",
                "customer": {"name": "Fulano", "document": "11144477735"},
                "transactions": [{
                    "transactionStatus": "captured",
                    "card": {"cardNumber": "4111111111111111", "securityCode": "123"},
                }],
            }
        }
        self.client.post(
            reverse("pagamentos:webhook"), data=_json.dumps(corpo),
            content_type="application/json",
        )
        ev = EventoPagamento.objects.filter(cobranca=c, tipo="webhook").latest("id")
        blob = _json.dumps(ev.detalhe)
        # PAN, CVV e documento não podem aparecer em lugar nenhum da trilha.
        self.assertNotIn("4111111111111111", blob)
        self.assertNotIn("11144477735", blob)
        self.assertIn("[REDACTED]", blob)
        # Dados de reconciliação (id/status) permanecem.
        self.assertIn("paid", blob)

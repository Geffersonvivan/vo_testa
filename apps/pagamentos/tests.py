from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, ModuloContratado, Pessoa, TipoUH, TrilhaAuditoria
from apps.nucleo.modulos import Modulo

from . import services
from .models import Cobranca, EventoPagamento

Usuario = get_user_model()


class PagamentosBase(TestCase):
    def setUp(self):
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

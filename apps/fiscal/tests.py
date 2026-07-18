from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Pessoa, TrilhaAuditoria
from apps.nucleo.modulos import Modulo

from . import services
from .models import DocumentoFiscal

Usuario = get_user_model()


class EmissaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="fisc", password="senha-forte-123")

    def test_servico_emite_nfse_autorizada(self):
        doc = services.emitir(self.op, natureza="servico", valor=Decimal("200"),
                              descricao="Diária Quarto 01")
        self.assertEqual(doc.tipo, DocumentoFiscal.Tipo.NFSE)
        self.assertEqual(doc.status, DocumentoFiscal.Status.AUTORIZADA)
        self.assertTrue(doc.chave)

    def test_consumo_emite_nfce(self):
        doc = services.emitir(self.op, natureza="consumo", valor=Decimal("36"),
                              descricao="Restaurante")
        self.assertEqual(doc.tipo, DocumentoFiscal.Tipo.NFCE)
        self.assertTrue(doc.autorizada)

    def test_valor_invalido(self):
        with self.assertRaises(ValidationError):
            services.emitir(self.op, natureza="servico", valor=0, descricao="x")

    def test_cancelar_autorizada_audita(self):
        p = Pessoa.objects.create(nome="Hóspede")
        doc = services.emitir(self.op, natureza="servico", valor=Decimal("200"),
                              descricao="Diária", tomador=p)
        services.cancelar(doc, self.op, "erro de digitação")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentoFiscal.Status.CANCELADA)
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="cancelamento_fiscal").exists())


class NfseDaDiariaTests(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.nucleo.models import UH, TipoUH
        from apps.reservas.models import Reserva
        self.op = Usuario.objects.create_superuser(username="fisc", password="senha-forte-123")
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Quarto 01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        self.reserva = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        self.conta = self.reserva.fazer_checkin(self.op)  # lança 2 diárias = 400 (serviço)

    def test_emite_nfse_do_servico_da_conta(self):
        doc = services.emitir_nfse_da_conta(self.conta.pk, self.op)
        self.assertEqual(doc.tipo, DocumentoFiscal.Tipo.NFSE)
        self.assertEqual(doc.natureza, "servico")
        self.assertEqual(doc.valor, Decimal("400.00"))  # 2 × 200
        self.assertEqual(doc.tomador, self.reserva.hospede)
        self.assertEqual(doc.payload.get("codigo_servico"), "090101")
        self.assertEqual(doc.payload.get("iss_aliquota"), "4.0")

    def test_idempotente_por_conta(self):
        d1 = services.emitir_nfse_da_conta(self.conta.pk, self.op)
        d2 = services.emitir_nfse_da_conta(self.conta.pk, self.op)
        self.assertEqual(d1.pk, d2.pk)  # não duplica
        self.assertEqual(DocumentoFiscal.objects.filter(tipo="nfse").count(), 1)


class WebhookFocusTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="fisc", password="senha-forte-123")

    def _doc_processando(self, ref):
        doc = DocumentoFiscal.objects.create(
            tipo=DocumentoFiscal.Tipo.NFSE, natureza="servico",
            status=DocumentoFiscal.Status.PROCESSANDO, descricao="Diária",
            valor=Decimal("400"), gateway="focus", gateway_id=ref, criado_por=self.op,
        )
        return doc

    def test_webhook_autoriza_e_guarda_pdf(self):
        doc = self._doc_processando("crm-1")
        payload = {
            "ref": "crm-1", "status": "autorizado", "numero": "42",
            "codigo_verificacao": "ABC123",
            "url": "https://focusnfe.s3.amazonaws.com/nota.pdf",
            "url_danfse": "https://focusnfe.s3.amazonaws.com/danfse.pdf",
            "caminho_xml_nota_fiscal": "/notas/nfse.xml",
        }
        r = self.client.post(reverse("fiscal:webhook"), data=payload,
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentoFiscal.Status.AUTORIZADA)
        self.assertEqual(doc.numero, "42")
        self.assertEqual(doc.pdf_url, "https://focusnfe.s3.amazonaws.com/danfse.pdf")
        self.assertEqual(doc.xml_url, "/notas/nfse.xml")

    def test_webhook_ref_desconhecida_404(self):
        r = self.client.post(reverse("fiscal:webhook"), data={"ref": "nao-existe"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)


class PermissaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="fisc", password="senha-forte-123")

    def test_modulo_inativo_da_404(self):
        # Fiscal é fase 2 — inativo por padrão.
        self.client.login(username="fisc", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("fiscal:painel")).status_code, 404)

    def test_ativo_superuser_ok(self):
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.FISCAL, defaults={"ativo": True}
        )
        self.client.login(username="fisc", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("fiscal:painel")).status_code, 200)

    def test_ativo_sem_acesso_da_403(self):
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.FISCAL, defaults={"ativo": True}
        )
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("fiscal:painel")).status_code, 403)

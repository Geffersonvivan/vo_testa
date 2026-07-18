from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .proposta import PROPOSTA
from .services import payload_stub, proposta

Usuario = get_user_model()


class NpsPropostaTests(TestCase):
    def test_proposta_tem_api_e_documento(self):
        p = proposta()
        self.assertFalse(p["implementado"])
        self.assertEqual(p["documento"], "docs/Proposta_NPS.md")
        self.assertTrue(p["api"]["endpoints"])
        self.assertEqual(p, PROPOSTA)

    def test_painel_exige_login(self):
        resp = self.client.get(reverse("nps:painel"))
        self.assertEqual(resp.status_code, 302)

    def test_painel_mostra_proposta(self):
        Usuario.objects.create_user(username="nps", password="x")
        self.client.login(username="nps", password="x")
        resp = self.client.get(reverse("nps:painel"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Proposta registrada")
        self.assertContains(resp, "/api/nps/v1/")

    def test_api_criar_resposta_retorna_501(self):
        resp = Client().post(reverse("nps_api:criar_resposta"), {})
        self.assertEqual(resp.status_code, 501)
        body = resp.json()
        self.assertFalse(body["implementado"])
        self.assertIn("proposta", body)

    def test_api_resumo_exige_login(self):
        resp = self.client.get(reverse("nps_api:resumo"))
        self.assertEqual(resp.status_code, 302)

    def test_payload_stub_marca_fase(self):
        body = payload_stub("GET /api/nps/v1/resumo/")
        self.assertIn("CRM do Hóspede", body["fase"])

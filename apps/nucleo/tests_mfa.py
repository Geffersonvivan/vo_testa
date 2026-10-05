"""Testes do MFA (TOTP) — Fase 4 de segurança."""
import pyotp
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import mfa

Usuario = get_user_model()


class MFAFluxoTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="op", password="senha-forte-123")

    def test_ativar_mostra_qr_e_confirma_com_codigo(self):
        self.client.login(username="op", password="senha-forte-123")
        # GET gera o secret em sessão e mostra o QR
        r = self.client.get(reverse("mfa_ativar"))
        self.assertEqual(r.status_code, 200)
        secret = self.client.session["mfa_secret_novo"]
        self.assertTrue(secret)
        # POST com código válido ativa e revela backups
        codigo = pyotp.TOTP(secret).now()
        r = self.client.post(reverse("mfa_ativar"), {"codigo": codigo})
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_ativo)
        self.assertEqual(len(self.user.mfa_backup_codes), 8)

    def test_login_com_mfa_exige_segundo_fator(self):
        secret = mfa.novo_secret()
        self.user.mfa_secret = secret
        self.user.mfa_ativo = True
        self.user.save()
        # senha correta → NÃO loga, manda pro desafio
        r = self.client.post(reverse("login"),
                             {"username": "op", "password": "senha-forte-123"})
        self.assertRedirects(r, reverse("mfa_desafio"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        # código TOTP válido → loga
        r = self.client.post(reverse("mfa_desafio"), {"codigo": pyotp.TOTP(secret).now()})
        self.assertIn("_auth_user_id", self.client.session)

    def test_codigo_de_backup_funciona_uma_vez(self):
        claros, hashes = mfa.gerar_backup_codes()
        self.user.mfa_secret = mfa.novo_secret()
        self.user.mfa_ativo = True
        self.user.mfa_backup_codes = hashes
        self.user.save()
        self.assertTrue(mfa.consumir_backup(self.user, claros[0]))   # 1ª vez: ok
        self.assertFalse(mfa.consumir_backup(self.user, claros[0]))  # reuso: recusa

    def test_mfa_obrigatorio_para_superuser(self):
        su = Usuario.objects.create_superuser(username="chefe", password="senha-forte-123")
        self.assertTrue(mfa.mfa_obrigatorio(su))
        self.assertFalse(mfa.mfa_obrigatorio(self.user))


class HeadersSegurancaTests(TestCase):
    def test_csp_report_only_presente(self):
        r = self.client.get(reverse("login"))
        self.assertIn("Content-Security-Policy-Report-Only", r.headers)
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy-Report-Only"])

    def test_nosniff_presente(self):
        r = self.client.get(reverse("login"))
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

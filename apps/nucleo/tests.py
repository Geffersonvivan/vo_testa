from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import ModuloContratado, modulo_ativo, modulos_ativos
from .modulos import Modulo

Usuario = get_user_model()


class AutenticacaoTests(TestCase):
    def test_pagina_de_login_carrega(self):
        resposta = self.client.get(reverse("login"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Pousada Vô Testa")

    def test_dashboard_exige_login(self):
        resposta = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            resposta, f"{reverse('login')}?next={reverse('dashboard')}"
        )

    def test_dashboard_carrega_para_usuario_logado(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Módulos contratados")

    def test_login_e_logout_funcionam(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        resposta = self.client.post(
            reverse("login"),
            {"username": "recepcao", "password": "senha-forte-123"},
        )
        self.assertRedirects(resposta, reverse("dashboard"))
        resposta = self.client.post(reverse("logout"))
        self.assertRedirects(resposta, reverse("login"))


class RegistroDeModulosTests(TestCase):
    def test_seed_ativou_os_11_modulos_da_fase_1(self):
        self.assertEqual(ModuloContratado.objects.filter(ativo=True).count(), 11)
        self.assertTrue(modulo_ativo(Modulo.RESERVAS))
        self.assertTrue(modulo_ativo(Modulo.LOJA))
        self.assertFalse(modulo_ativo(Modulo.FISCAL))  # fase 2, não contratado

    def test_modulos_ativos_respeita_ordem_do_catalogo(self):
        ativos = modulos_ativos()
        self.assertEqual(ativos[0], Modulo.RESERVAS)
        self.assertIn(Modulo.APPSITE, ativos)

    def test_ativacao_valida_dependencias(self):
        # Loja depende de Estoque: desativando Estoque, Loja não pode ser ativada.
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        loja = ModuloContratado.objects.get(codigo=Modulo.LOJA)
        with self.assertRaises(ValidationError):
            loja.full_clean()

    def test_menu_so_aparece_para_usuario_logado(self):
        resposta = self.client.get(reverse("login"))
        self.assertNotContains(resposta, "nav-item")


class PermissoesPorModuloTests(TestCase):
    def setUp(self):
        self.funcionaria = Usuario.objects.create_user(
            username="loja", password="senha-forte-123"
        )
        self.funcionaria.modulos.add(
            ModuloContratado.objects.get(codigo=Modulo.LOJA)
        )
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )

    def test_usuario_acessa_somente_modulos_atribuidos(self):
        self.assertTrue(self.funcionaria.pode_acessar(Modulo.LOJA))
        self.assertFalse(self.funcionaria.pode_acessar(Modulo.RESERVAS))

    def test_superusuario_acessa_todos_os_modulos_ativos(self):
        self.assertTrue(self.gerente.pode_acessar(Modulo.RESERVAS))
        self.assertTrue(self.gerente.pode_acessar(Modulo.LOJA))

    def test_modulo_inativo_nega_acesso_mesmo_atribuido(self):
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.assertFalse(self.funcionaria.pode_acessar(Modulo.LOJA))
        self.assertFalse(self.gerente.pode_acessar(Modulo.LOJA))

    def test_menu_filtra_por_permissao_do_usuario(self):
        self.client.login(username="loja", password="senha-forte-123")
        resposta = self.client.get(reverse("dashboard"))
        self.assertContains(resposta, "Loja")
        self.assertNotContains(resposta, "Governança")

    def test_decorator_requer_modulo(self):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404, HttpResponse
        from django.test import RequestFactory

        from .permissoes import requer_modulo

        @requer_modulo(Modulo.LOJA)
        def view_loja(request):
            return HttpResponse("ok")

        @requer_modulo(Modulo.FISCAL)  # não contratado
        def view_fiscal(request):
            return HttpResponse("ok")

        fabrica = RequestFactory()

        pedido = fabrica.get("/loja/")
        pedido.user = self.funcionaria
        self.assertEqual(view_loja(pedido).status_code, 200)

        pedido = fabrica.get("/loja/")
        pedido.user = Usuario.objects.create_user(
            username="sem-acesso", password="senha-forte-123"
        )
        with self.assertRaises(PermissionDenied):
            view_loja(pedido)

        pedido = fabrica.get("/fiscal/")
        pedido.user = self.gerente
        with self.assertRaises(Http404):
            view_fiscal(pedido)

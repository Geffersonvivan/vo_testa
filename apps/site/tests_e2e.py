"""Testes E2E (navegador real via Playwright) dos fluxos críticos.

Rodam no próprio `manage.py test` usando StaticLiveServerTestCase (sobe um servidor
de verdade) + Playwright headless. Pulam sozinhos se o Playwright/navegador não
estiver instalado — não quebram a suíte de quem não tem.

Para rodar localmente:
    .venv/bin/pip install playwright && .venv/bin/playwright install chromium
    .venv/bin/python manage.py test apps.site.tests_e2e
"""
import os
import unittest

# Playwright (sync) sobe um event loop; sem isto o Django acha que está em contexto
# async e recusa as operações de DB do LiveServer. É só para os testes E2E.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_OK = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_OK = False


class _BaseE2E(StaticLiveServerTestCase):
    """Sobe um navegador headless por classe; uma aba (page) por teste."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        self.page = self._browser.new_page()

    def tearDown(self):
        self.page.close()

    def url(self, caminho):
        return self.live_server_url + caminho


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class SiteHomeE2ETests(_BaseE2E):
    def test_hero_mostra_campanha(self):
        self.page.goto(self.url("/"))
        self.page.wait_for_selector("text=É a casa do vô!", timeout=10000)
        self.assertTrue(self.page.get_by_text("É a casa do vô!").is_visible())

    def test_secao_revela(self):
        # Guarda o bug de reveal (fade-section com opacity travada em 0): a seção de
        # experiências precisa ficar VISÍVEL (opacity → 1) ao entrar na viewport ou
        # pelo fail-safe. Semeia 1 experiência para a seção ter conteúdo.
        from apps.site.models import Experiencia
        Experiencia.objects.create(
            nome="Trilha do Teste E2E", descricao="desc", destaque=True)
        self.page.goto(self.url("/"))
        self.page.get_by_text("Trilha do Teste E2E").scroll_into_view_if_needed()
        self.page.wait_for_function(
            "() => { const s = document.querySelector('#experiencias .fade-section');"
            "        return s && getComputedStyle(s).opacity === '1'; }",
            timeout=6000)
        op = self.page.eval_on_selector(
            "#experiencias .fade-section", "el => getComputedStyle(el).opacity")
        self.assertEqual(op, "1")


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class FunilBuscaE2ETests(_BaseE2E):
    def _login(self, username, senha):
        self.page.goto(self.url("/crm/entrar/"))
        self.page.fill("input[name=username]", username)
        self.page.fill("input[name=password]", senha)
        self.page.press("input[name=password]", "Enter")
        self.page.wait_for_load_state("networkidle")

    def test_busca_do_funil_filtra_cards(self):
        from apps.comercial import services
        from apps.nucleo.models import Pessoa, Usuario
        u = Usuario.objects.create_superuser(username="e2e", password="forte-123-abc")
        for nome in ("Alpha Lead E2E", "Beta Lead E2E"):
            p = Pessoa.objects.create(nome=nome)
            services.criar_oportunidade(usuario=u, pessoa=p, titulo="Proposta")

        self._login("e2e", "forte-123-abc")
        self.page.goto(self.url("/crm/comercial/"))
        self.page.wait_for_selector("#funilBusca")
        board = self.page.locator("#funilBoard")  # escopo: só os cards do quadro

        # antes de filtrar: os dois cards aparecem
        self.assertTrue(board.get_by_text("Alpha Lead E2E").is_visible())
        self.assertTrue(board.get_by_text("Beta Lead E2E").is_visible())

        # digita "Alpha" → só o card Alpha permanece
        self.page.fill("#funilBusca", "Alpha")
        self.page.wait_for_timeout(300)
        self.assertTrue(board.get_by_text("Alpha Lead E2E").is_visible())
        self.assertFalse(board.get_by_text("Beta Lead E2E").is_visible())

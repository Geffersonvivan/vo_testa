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
    """Sobe um navegador headless por classe; uma aba (page) por teste.

    Atenção: StaticLiveServerTestCase é um TransactionTestCase — ele dá FLUSH no banco
    após cada teste, o que APAGA os dados semeados por migração (etapas do funil
    comercial, módulos, formas de pagamento…). Classes que dependem desses seeds
    precisam recriá-los no próprio setUp (ver `FunilBuscaE2ETests`), pois outra classe
    E2E rodando antes pode já ter limpado o banco.
    """

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


class _UnidadeVendavelMixin:
    """Semeia um quarto físico vendável pelo site (venda por unidade): TipoUH + UH
    ATIVA + VitrineQuarto publicada + site.Quarto como recibo do canal. A fonte da
    verdade do preço/disponibilidade é o CRM, igual à produção."""

    def _semear_unidade(self, *, capacidade=2, tarifa="400.00"):
        from decimal import Decimal
        from apps.nucleo.models import UH, TipoUH
        from apps.site.models import CategoriaQuarto, Quarto, VitrineQuarto
        tipo = TipoUH.objects.create(
            nome="Suíte E2E", tarifa_base=Decimal(tarifa), capacidade=capacidade)
        uh = UH.objects.create(
            numero="E2E-1", tipo=tipo, nome_tematico="Cabine do Lago E2E",
            vista_lago=True)
        VitrineQuarto.objects.create(
            uh=uh, publicar=True, destaque=True, metragem=25)
        cat, _ = CategoriaQuarto.objects.get_or_create(nome="Suíte E2E")
        Quarto.objects.create(
            nome="Cabine E2E", categoria=cat, descricao="x", descricao_curta="x",
            capacidade=capacidade, metragem=25, preco_base=Decimal(tarifa),
            status="disponivel", tipo_uh=tipo)
        return uh

    def _datas(self, dias_ini=10, dias_fim=13):
        from datetime import date, timedelta
        hoje = date.today()
        return (hoje + timedelta(days=dias_ini), hoje + timedelta(days=dias_fim))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class ReservaSiteE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    """Fluxo de reserva do site ponta a ponta no navegador real: lista de quartos
    (passo 2) → dados do hóspede (passo 3) → resumo (passo 4) → confirmação (passo 5).
    Prova que o clique-a-clique cria a PRÉ-RESERVA no CRM (fonte da verdade) e o
    recibo do canal (`site.Reserva`), sem overbooking."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()  # o rate-limit do site vive em LocMemCache entre testes
        self.uh = self._semear_unidade()

    def test_reserva_ponta_a_ponta(self):
        checkin, checkout = self._datas()
        # Passo 2 — entra direto com as datas (o calendário tem teste próprio) e
        # confere que o quarto físico aparece com o nome temático.
        self.page.goto(self.url(
            f"/reservar/?checkin={checkin:%Y-%m-%d}"
            f"&checkout={checkout:%Y-%m-%d}&hospedes=2"))
        self.page.wait_for_selector("text=Cabine do Lago E2E", timeout=10000)
        self.page.get_by_role("link", name="Reservar").first.click()

        # Passo 3 — dados do hóspede (CPF válido p/ passar na validação do form).
        self.page.wait_for_selector("input[name=nome]", timeout=10000)
        self.page.fill("input[name=nome]", "Maria Teste E2E")
        self.page.fill("input[name=email]", "maria.e2e@exemplo.com")
        self.page.fill("input[name=telefone]", "(49) 99143-8813")
        self.page.fill("input[name=cpf]", "111.444.777-35")
        self.page.get_by_role("button", name="Continuar").click()

        # Passo 4 — resumo e confirmação.
        self.page.wait_for_selector("text=Confirmar Reserva", timeout=10000)
        self.page.get_by_role("button", name="Confirmar Reserva").click()

        # Passo 5 — página de confirmação (URL com token /reserva/<uuid>/).
        self.page.wait_for_selector("text=Reserva Registrada!", timeout=10000)
        self.assertIn("/reserva/", self.page.url)

        # Invariante: a reserva do canal e a PRÉ-RESERVA no CRM foram criadas.
        from apps.site.models import Reserva as ReservaSite
        from apps.reservas.models import Reserva as ReservaCRM
        rs = ReservaSite.objects.get(hospede__nome="Maria Teste E2E")
        self.assertEqual(rs.status, "aguardando")
        self.assertIsNotNone(rs.crm_reserva_id)
        crm = ReservaCRM.objects.get(pk=rs.crm_reserva_id)
        self.assertEqual(crm.uh_id, self.uh.pk)
        self.assertEqual(crm.status, ReservaCRM.Status.PRE_RESERVA)
        self.assertEqual(crm.checkin, checkin)
        self.assertEqual(crm.checkout, checkout)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class CalendarioDatasE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    """Passo 1 real: dirige o calendário (flatpickr, servido local em /static) e o
    stepper de hóspedes, provando que selecionar um intervalo habilita o botão e leva
    à lista de quartos. Guarda o tipo de regressão de UI que só aparece no navegador."""

    def setUp(self):
        super().setUp()
        self._semear_unidade(capacidade=4)  # comporta os 3 hóspedes do stepper

    def test_selecionar_intervalo_habilita_e_lista_quartos(self):
        self.page.goto(self.url("/reservar/"))
        # inline flatpickr insere o calendário como IRMÃO de #calendario-inline.
        self.page.wait_for_selector(".flatpickr-calendar", timeout=10000)
        cal = self.page.locator(".flatpickr-calendar")

        # Mês seguinte: todos os dias são futuros (robusto em qualquer dia do mês).
        cal.locator(".flatpickr-next-month").click()
        self.page.wait_for_timeout(200)
        # Intervalo (range): dia 10 = check-in, dia 13 = check-out.
        cal.get_by_text("10", exact=True).first.click()
        cal.get_by_text("13", exact=True).first.click()

        # +1 hóspede pelo stepper (3 pessoas) — exercita o controle customizado.
        self.page.click("#hosp-mais")
        self.assertEqual(self.page.input_value("#f-hospedes"), "3")

        # Com check-in + check-out preenchidos, o botão deixa de ser desabilitado.
        self.page.wait_for_function(
            "() => { const b = document.getElementById('btn-ver-quartos');"
            "        return b && !b.disabled; }",
            timeout=6000)
        self.assertNotEqual(self.page.input_value("#f-checkin"), "")
        self.assertNotEqual(self.page.input_value("#f-checkout"), "")

        # Submete → passo 2 (lista de quartos) com as datas na URL.
        self.page.click("#btn-ver-quartos")
        self.page.wait_for_selector("text=Cabine do Lago E2E", timeout=10000)
        self.assertIn("checkin=", self.page.url)


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


class _FunilComercialMixin:
    """Prepara o módulo Comercial para as E2E do funil: reativa o módulo e recria as
    etapas de funil no setUp. O flush do TransactionTestCase apaga o seed de migração,
    então uma classe E2E que rode antes deixaria /crm/comercial/ 404 e o funil vazio."""

    # Etapas do funil (espelham a migração comercial.0002).
    _ETAPAS = [
        ("Novo lead", 10, 10, "aberta"), ("Contato feito", 20, 30, "aberta"),
        ("Cotação enviada", 30, 50, "aberta"), ("Negociação", 40, 70, "aberta"),
        ("Ganho", 50, 100, "ganho"), ("Perdido", 60, 0, "perdido"),
    ]

    def setUp(self):
        super().setUp()
        from apps.comercial.models import EtapaFunil
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.COMERCIAL, defaults={"ativo": True})
        for nome, ordem, prob, tipo in self._ETAPAS:
            EtapaFunil.objects.get_or_create(
                nome=nome, defaults={"ordem": ordem, "probabilidade": prob, "tipo": tipo})

    def _login(self, username, senha):
        self.page.goto(self.url("/crm/entrar/"))
        self.page.fill("input[name=username]", username)
        self.page.fill("input[name=password]", senha)
        self.page.press("input[name=password]", "Enter")
        self.page.wait_for_load_state("networkidle")


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class FunilBuscaE2ETests(_FunilComercialMixin, _BaseE2E):
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


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class FunilMoverLeadE2ETests(_FunilComercialMixin, _BaseE2E):
    """Caminho feliz: login + arrastar um lead de "Novo lead" para "Contato feito".

    O Kanban usa drag-and-drop nativo (HTML5), que o mouse sintético do Playwright não
    dispara de forma confiável — então simulamos o arrasto despachando os eventos
    dragstart→dragover→drop com um MESMO DataTransfer, exatamente como o `cardDragStart`
    (setData('op', id)) e o `soltarCard` (getData('op') → submete o form-mover) esperam.
    Assim o teste exercita os handlers reais + a view `mover` + o service `mover_etapa`.
    """

    _DRAG_JS = """
    ([origem, destino]) => {
        const src = document.querySelector(origem);
        const tgt = document.querySelector(destino);
        const dt = new DataTransfer();
        src.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: dt}));
        tgt.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));
        tgt.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
        src.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
    }
    """

    def test_mover_lead_entre_etapas(self):
        from apps.comercial import services
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa, Usuario

        u = Usuario.objects.create_superuser(username="mov", password="forte-123-abc")
        pessoa = Pessoa.objects.create(nome="Lead Arrastável E2E")
        op = services.criar_oportunidade(usuario=u, pessoa=pessoa, titulo="Proposta")
        novo = EtapaFunil.objects.get(nome="Novo lead")
        contato = EtapaFunil.objects.get(nome="Contato feito")
        self.assertEqual(op.etapa_id, novo.id)  # nasce em "Novo lead"

        self._login("mov", "forte-123-abc")
        self.page.goto(self.url("/crm/comercial/"))
        self.page.wait_for_selector("#funilBoard")

        card = f'.funil-card[data-op="{op.id}"]'
        coluna_contato = f'.funil-coluna[data-etapa="{contato.id}"]'
        # Estado inicial: o card está na coluna "Novo lead".
        self.assertTrue(self.page.locator(
            f'.funil-coluna[data-etapa="{novo.id}"] {card}').is_visible())

        # Arrasta o card para "Contato feito"; o drop submete o form-mover (reload).
        with self.page.expect_navigation():
            self.page.evaluate(self._DRAG_JS, [card, coluna_contato])

        # UI: o card agora vive dentro da coluna "Contato feito".
        self.page.wait_for_selector(f'{coluna_contato} {card}', timeout=10000)
        self.assertTrue(self.page.locator(f'{coluna_contato} {card}').is_visible())

        # Invariante: a etapa mudou no banco (via mover_etapa), sem tocar outros leads.
        op.refresh_from_db()
        self.assertEqual(op.etapa_id, contato.id)
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)

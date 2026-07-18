from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, TipoUH

from . import services

Usuario = get_user_model()


class RelatoriosServiceTests(TestCase):
    def setUp(self):
        from apps.reservas.models import Reserva
        self.op = Usuario.objects.create_superuser(username="ger", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        self.r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje - timedelta(days=2),
            checkout=hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("200"), criado_por=self.op,
        )
        self.r.fazer_checkin(self.op)  # lança diárias na conta

    def _periodo(self):
        hoje = timezone.localdate()
        return hoje - timedelta(days=7), hoje

    def test_producao_soma_diarias(self):
        ini, fim = self._periodo()
        p = services.rel_producao(ini, fim)
        # três noites (hoje-2 a hoje+1) × 200 = 600 em serviço
        self.assertTrue(any("600" in v for _, v in p["kpis"]))

    def test_ocupacao_calcula_taxa(self):
        ini, fim = self._periodo()
        o = services.rel_ocupacao(ini, fim)
        rotulos = [r for r, _ in o["kpis"]]
        self.assertIn("Ocupação", rotulos)
        self.assertIn("Diária média (ADR)", rotulos)

    def test_reservas_conta_por_canal(self):
        ini, fim = self._periodo()
        r = services.rel_reservas(ini, fim)
        self.assertEqual(r["kpis"][0], ("Reservas criadas", "1"))

    def test_disponiveis_agrupa(self):
        grupos = services.disponiveis()
        self.assertIn("Consolidados", grupos)


class RelatoriosViewTests(TestCase):
    def setUp(self):
        self.ger = Usuario.objects.create_superuser(username="ger", password="senha-forte-123")

    def test_index_ok(self):
        self.client.login(username="ger", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("relatorios:index")).status_code, 200)

    def test_relatorio_render(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["caixa"]))
        self.assertEqual(r.status_code, 200)

    def test_export_csv(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["caixa"]), {"export": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv")

    def test_relatorio_inexistente_404(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["nao-existe"]))
        self.assertEqual(r.status_code, 404)

    def test_sem_gerencia_403(self):
        Usuario.objects.create_user(username="op", password="senha-forte-123")
        self.client.login(username="op", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("relatorios:index")).status_code, 403)

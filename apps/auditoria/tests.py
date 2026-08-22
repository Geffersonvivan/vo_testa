from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, TipoUH, registrar_auditoria
from apps.reservas.models import Reserva

from . import services

Usuario = get_user_model()


class VarreduraTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede")

    def _hospedada(self, checkout_offset):
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje - timedelta(days=3),
            checkout=hoje + timedelta(days=checkout_offset),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        r.fazer_checkin(self.op)
        return r

    def test_detecta_checkout_vencido(self):
        self._hospedada(checkout_offset=-1)  # checkout ontem, ainda hospedada
        achados = services.varrer()
        tipos = {a["tipo"] for a in achados}
        self.assertIn("checkout_vencido", tipos)
        # conta com saldo também aparece (diárias lançadas, nada pago)
        self.assertIn("conta_com_saldo", tipos)

    def test_sem_pendencias_quando_tudo_ok(self):
        # nenhuma reserva/pendência criada
        achados = services.varrer()
        self.assertEqual([a for a in achados if a["area"] == "Reservas"], [])

    def test_resumo_conta_por_gravidade(self):
        self._hospedada(checkout_offset=-1)
        achados = services.varrer()
        r = services.resumo(achados)
        self.assertEqual(r["total"], len(achados))
        self.assertGreaterEqual(r["por_gravidade"]["alta"], 1)


class ComandaLavanderiaTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")

    def test_comanda_aberta_ha_muito(self):
        from apps.nucleo.models import LocalEstoque
        from apps.restaurante.models import Comanda
        local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        c = Comanda.objects.create(local=local, rotulo="Mesa 1", criado_por=self.op)
        Comanda.objects.filter(pk=c.pk).update(
            aberta_em=timezone.now() - timedelta(hours=20)  # burla o auto_now_add
        )
        tipos = {a["tipo"] for a in services.varrer()}
        self.assertIn("comanda_antiga", tipos)

    def test_ordem_lavanderia_atrasada(self):
        from apps.lavanderia.models import OrdemLavanderia
        o = OrdemLavanderia.objects.create(rotulo="Quarto 5", criado_por=self.op,
                                           prazo=timezone.localdate() - timedelta(days=1))
        self.assertTrue(o.em_producao)
        tipos = {a["tipo"] for a in services.varrer()}
        self.assertIn("lavanderia_atrasada", tipos)


class PainelTrilhaTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")
        self.client.login(username="aud", password="senha-forte-123")

    def test_painel_ok(self):
        self.assertEqual(self.client.get(reverse("auditoria:painel")).status_code, 200)

    def test_trilha_e_export_csv(self):
        registrar_auditoria(self.op, "estorno_pagamento", self.op, {"valor": "100"})
        r = self.client.get(reverse("auditoria:trilha"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "estorno_pagamento")
        csv_resp = self.client.get(reverse("auditoria:trilha"), {"export": "csv"})
        self.assertEqual(csv_resp["Content-Type"], "text/csv")
        self.assertIn("estorno_pagamento", csv_resp.content.decode())

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("auditoria:painel")).status_code, 403)


class FormatacaoTrilhaTests(TestCase):
    """A trilha lê como frase, não como JSON cru."""

    def _reg(self, acao, alvo="", detalhe=None, alvo_id="1"):
        from types import SimpleNamespace
        return SimpleNamespace(acao=acao, alvo=alvo, detalhe=detalhe or {}, alvo_id=alvo_id)

    def _frase(self, *a, **k):
        from .formatacao import frase
        return frase(self._reg(*a, **k))

    def test_login_logout(self):
        self.assertEqual(self._frase("login", "Usuario"), "Entrou no sistema")
        self.assertEqual(self._frase("logout", "Usuario"), "Saiu do sistema")

    def test_abrir_caixa(self):
        f = self._frase("criar", "SessaoCaixa",
                        {"valores": {"modulo": "reservas", "fundo_troco": "50.00"}})
        self.assertIn("Abriu o caixa de reservas", f)
        self.assertIn("R$ 50,00", f)

    def test_fechar_caixa(self):
        f = self._frase("fechamento_caixa", "SessaoCaixa",
                        {"contado": "350.00", "diferenca": "0.00"})
        self.assertIn("Fechou o caixa", f)
        self.assertIn("contado R$ 350,00", f)
        self.assertIn("diferença R$ 0,00", f)

    def test_recebimento(self):
        f = self._frase("criar", "MovimentoCaixa",
                        {"valores": {"tipo": "recebimento", "valor": "120.00",
                                     "descricao": "Conta reserva #5"}})
        self.assertIn("Recebeu R$ 120,00", f)
        self.assertIn("Conta reserva #5", f)

    def test_editar_mostra_diff(self):
        f = self._frase("editar", "Reserva", {"alteracoes": {"status": ["confirmada", "hospedada"]}})
        self.assertIn("Alterou reserva", f)
        self.assertIn("status: confirmada → hospedada", f)

    def test_fallback_nunca_quebra(self):
        f = self._frase("acao_desconhecida", "Reserva", {"algo": "x"})
        self.assertIn("Acao desconhecida", f)
        self.assertNotIn("{", f)  # nada de JSON cru

    def test_entidades_operacionais(self):
        self.assertEqual(self._frase("criar", "EntradaLogbook"), "Deixou um recado no turno")
        self.assertIn("Abriu ordem de serviço", self._frase("criar", "OrdemServico", alvo_id="12"))
        self.assertIn("Registrou venda", self._frase("criar", "Venda", alvo_id="45"))
        self.assertIn("Abriu comanda", self._frase("criar", "Comanda", alvo_id="3"))

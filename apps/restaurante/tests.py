from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    FormaPagamento,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    SessaoCaixa,
    TipoUH,
    TrilhaAuditoria,
    registrar_entrada,
    saldo,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import Comanda, Mesa

Usuario = get_user_model()


class RestauranteBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(
            username="garcom", password="senha-forte-123"
        )
        cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        self.cerveja = Produto.objects.create(
            nome="Cerveja", categoria=cat, preco_venda=Decimal("12.00")
        )
        registrar_entrada(self.cerveja, self.local, 20, Decimal("4.00"), self.op)
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.mesa = Mesa.objects.create(nome="Mesa 1")

    def comanda(self):
        return services.abrir_comanda(self.op, self.local, mesa=self.mesa)

    def abrir_caixa(self):
        return SessaoCaixa.objects.create(
            operador=self.op, modulo="nucleo", fundo_troco=Decimal("0.00")
        )


class ComandaTests(RestauranteBase):
    def test_adicionar_baixa_estoque_e_agrupa(self):
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 2, self.op)
        services.adicionar_item(c, self.cerveja, 1, self.op)
        self.assertEqual(c.itens.count(), 1)  # agrupou na mesma linha
        self.assertEqual(c.itens.first().quantidade, Decimal("3.000"))
        self.assertEqual(c.total(), Decimal("36.00"))
        self.assertEqual(saldo(self.cerveja, self.local), Decimal("17.000"))

    def test_remover_devolve_estoque(self):
        c = self.comanda()
        item = services.adicionar_item(c, self.cerveja, 4, self.op)
        services.remover_item(item, self.op)
        self.assertEqual(c.itens.count(), 0)
        self.assertEqual(saldo(self.cerveja, self.local), Decimal("20.000"))

    def test_saldo_insuficiente_bloqueia(self):
        c = self.comanda()
        with self.assertRaises(ValidationError):
            services.adicionar_item(c, self.cerveja, 999, self.op)

    def test_abrir_exige_identificacao(self):
        with self.assertRaises(ValidationError):
            services.abrir_comanda(self.op, self.local)


class FechamentoTests(RestauranteBase):
    def test_fechar_no_caixa(self):
        sessao = self.abrir_caixa()
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 2, self.op)
        services.fechar_comanda(c, self.op, "caixa", forma=self.dinheiro)
        c.refresh_from_db()
        self.assertEqual(c.status, "fechada")
        self.assertIsNotNone(c.movimento_caixa)
        self.assertEqual(sessao.esperado_em_dinheiro(), Decimal("24.00"))

    def test_fechar_na_conta_do_quarto(self):
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Quarto 01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        from apps.reservas.models import Reserva

        r = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.op,
        )
        conta = r.fazer_checkin(self.op)
        base = conta.total_lancamentos()
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 3, self.op)
        services.fechar_comanda(c, self.op, "conta", conta_id=conta.pk)
        c.refresh_from_db()
        self.assertIsNone(c.movimento_caixa)
        self.assertEqual(conta.total_lancamentos(), base + Decimal("36.00"))

    def test_fechar_vazia_bloqueia(self):
        self.abrir_caixa()
        c = self.comanda()
        with self.assertRaises(ValidationError):
            services.fechar_comanda(c, self.op, "caixa", forma=self.dinheiro)


class CancelamentoTests(RestauranteBase):
    def test_cancelar_devolve_estoque(self):
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 5, self.op)
        services.cancelar_comanda(c, self.op, "erro no pedido")
        c.refresh_from_db()
        self.assertEqual(c.status, "cancelada")
        self.assertEqual(saldo(self.cerveja, self.local), Decimal("20.000"))
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="cancelamento_comanda").exists()
        )


class PermissaoTests(RestauranteBase):
    def test_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("restaurante:comandas")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESTAURANTE).update(ativo=False)
        self.client.login(username="garcom", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("restaurante:comandas")).status_code, 404)

    def test_abrir_so_com_rotulo_pela_view(self):
        # regressão: selects mesa/cliente vazios não podem virar filter(pk="")
        self.client.login(username="garcom", password="senha-forte-123")
        r = self.client.post(
            reverse("restaurante:abrir"),
            {"mesa": "", "cliente": "", "rotulo": "guarda-sol 4"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Comanda.objects.filter(rotulo="guarda-sol 4").exists())

    def test_historico_lista_fechadas_e_canceladas(self):
        self.abrir_caixa()
        self.client.login(username="garcom", password="senha-forte-123")
        # uma fechada
        f = self.comanda()
        services.adicionar_item(f, self.cerveja, 1, self.op)
        services.fechar_comanda(f, self.op, "caixa", forma=self.dinheiro)
        # uma cancelada
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 1, self.op)
        services.cancelar_comanda(c, self.op, "cliente desistiu")
        # abertas não entram
        self.comanda()

        r = self.client.get(reverse("restaurante:historico"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["comandas"]), 2)

        so_canceladas = self.client.get(reverse("restaurante:historico"), {"status": "cancelada"})
        nomes = [x.pk for x in so_canceladas.context["comandas"]]
        self.assertEqual(nomes, [c.pk])
        self.assertContains(so_canceladas, "cliente desistiu")

    def test_add_item_pela_view(self):
        self.client.login(username="garcom", password="senha-forte-123")
        c = self.comanda()
        r = self.client.post(
            reverse("restaurante:add_item", args=[c.pk]),
            {"produto_id": self.cerveja.pk, "quantidade": 2},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(saldo(self.cerveja, self.local), Decimal("18.000"))

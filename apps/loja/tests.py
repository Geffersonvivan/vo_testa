import json
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
from .models import Venda

Usuario = get_user_model()


class LojaBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(
            username="loja", password="senha-forte-123"
        )
        self.cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.local = LocalEstoque.objects.create(nome="Loja dep", modulo="loja")
        self.produto = Produto.objects.create(
            nome="Refri", categoria=self.cat, preco_venda=Decimal("7.00")
        )
        registrar_entrada(self.produto, self.local, 20, Decimal("2.50"), self.op)
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def abrir_caixa(self):
        return SessaoCaixa.objects.create(
            operador=self.op, modulo="loja", fundo_troco=Decimal("0.00")
        )

    def itens(self, qtd=2):
        return [{"produto_id": self.produto.pk, "quantidade": qtd}]

    def conta_aberta(self):
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="C1", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede X")
        from apps.reservas.models import Reserva

        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.op,
        )
        return r.fazer_checkin(self.op)


class VendaCaixaTests(LojaBase):
    def test_venda_baixa_estoque_e_recebe_no_caixa(self):
        sessao = self.abrir_caixa()
        venda = services.finalizar_venda(
            self.op, self.local, self.itens(2), "caixa", forma=self.dinheiro
        )
        self.assertEqual(venda.total, Decimal("14.00"))
        self.assertEqual(saldo(self.produto, self.local), Decimal("18.000"))
        self.assertIsNotNone(venda.movimento_caixa)
        self.assertEqual(sessao.esperado_em_dinheiro(), Decimal("14.00"))

    def test_desconto(self):
        self.abrir_caixa()
        venda = services.finalizar_venda(
            self.op, self.local, self.itens(2), "caixa",
            forma=self.dinheiro, desconto=Decimal("4.00"),
        )
        self.assertEqual(venda.total, Decimal("10.00"))

    def test_saldo_insuficiente_bloqueia(self):
        self.abrir_caixa()
        with self.assertRaises(ValidationError):
            services.finalizar_venda(
                self.op, self.local, self.itens(999), "caixa", forma=self.dinheiro
            )
        self.assertEqual(saldo(self.produto, self.local), Decimal("20.000"))

    def test_sem_caixa_aberto_bloqueia(self):
        with self.assertRaises(ValidationError):
            services.finalizar_venda(
                self.op, self.local, self.itens(1), "caixa", forma=self.dinheiro
            )
        # venda não persiste sem pagamento (transação revertida)
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(saldo(self.produto, self.local), Decimal("20.000"))

    def test_forma_obrigatoria_no_caixa(self):
        self.abrir_caixa()
        with self.assertRaises(ValidationError):
            services.finalizar_venda(self.op, self.local, self.itens(1), "caixa")


class VendaContaTests(LojaBase):
    def test_venda_lancada_na_conta_do_quarto(self):
        conta = self.conta_aberta()
        base = conta.total_lancamentos()  # diárias já lançadas
        venda = services.finalizar_venda(
            self.op, self.local, self.itens(3), "conta", conta_id=conta.pk
        )
        self.assertEqual(venda.total, Decimal("21.00"))
        self.assertIsNone(venda.movimento_caixa)  # não passou pelo caixa
        self.assertEqual(saldo(self.produto, self.local), Decimal("17.000"))
        self.assertEqual(conta.total_lancamentos(), base + Decimal("21.00"))

    def test_conta_inexistente_bloqueia(self):
        with self.assertRaises(ValidationError):
            services.finalizar_venda(
                self.op, self.local, self.itens(1), "conta", conta_id=999
            )


class CancelamentoTests(LojaBase):
    def test_cancelar_reverte_estoque_e_estorna_caixa(self):
        self.abrir_caixa()
        venda = services.finalizar_venda(
            self.op, self.local, self.itens(3), "caixa", forma=self.dinheiro
        )
        self.assertEqual(saldo(self.produto, self.local), Decimal("17.000"))
        services.cancelar_venda(venda, self.op, "Cliente desistiu")
        venda.refresh_from_db()
        self.assertEqual(venda.status, Venda.Status.CANCELADA)
        self.assertEqual(saldo(self.produto, self.local), Decimal("20.000"))
        self.assertTrue(
            venda.movimento_caixa.estornos.exists()
        )
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="cancelamento_venda").exists()
        )

    def test_cancelar_conta_bloqueado(self):
        conta = self.conta_aberta()
        venda = services.finalizar_venda(
            self.op, self.local, self.itens(1), "conta", conta_id=conta.pk
        )
        with self.assertRaises(ValidationError):
            services.cancelar_venda(venda, self.op, "tentativa")


class PermissaoTests(LojaBase):
    def test_pdv_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("loja:pdv")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.client.login(username="loja", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("loja:pdv")).status_code, 404)

    def test_finalizar_pela_view(self):
        self.abrir_caixa()
        self.client.login(username="loja", password="senha-forte-123")
        body = {
            "local_id": self.local.pk, "destino": "caixa",
            "forma_id": self.dinheiro.pk, "desconto": "0",
            "itens": self.itens(2),
        }
        r = self.client.post(
            reverse("loja:finalizar"), data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(saldo(self.produto, self.local), Decimal("18.000"))

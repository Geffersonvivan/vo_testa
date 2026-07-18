from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import (
    CategoriaProduto,
    Inventario,
    ItemInventario,
    LocalEstoque,
    ModuloContratado,
    MovimentoEstoque,
    Produto,
    TrilhaAuditoria,
    ajustar,
    posicao_estoque,
    produtos_abaixo_minimo,
    registrar_entrada,
    registrar_saida,
    saldo,
    transferir,
)
from apps.nucleo.modulos import Modulo

Usuario = get_user_model()


class EstoqueBase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(
            username="estoquista", password="senha-forte-123"
        )
        self.cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.almox = LocalEstoque.objects.create(nome="Almox", modulo="nucleo")
        self.loja = LocalEstoque.objects.create(nome="Loja dep", modulo="loja")
        self.produto = Produto.objects.create(
            nome="Refri lata", categoria=self.cat,
            preco_venda=Decimal("6.00"), estoque_minimo=Decimal("24"),
        )


class CustoMedioTests(EstoqueBase):
    def test_custo_medio_ponderado(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        registrar_entrada(self.produto, self.almox, 10, Decimal("3.00"), self.user)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, Decimal("2.5000"))
        self.assertEqual(saldo(self.produto, self.almox), Decimal("20.000"))

    def test_saida_mantem_custo_e_valida_saldo(self):
        registrar_entrada(self.produto, self.almox, 5, Decimal("4.00"), self.user)
        registrar_saida(self.produto, self.almox, 2, self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("3.000"))
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, Decimal("4.0000"))

    def test_saida_nao_deixa_saldo_negativo(self):
        registrar_entrada(self.produto, self.almox, 1, Decimal("1.00"), self.user)
        with self.assertRaises(ValidationError):
            registrar_saida(self.produto, self.almox, 5, self.user)

    def test_natureza_padrao_consumo(self):
        self.assertEqual(self.produto.natureza, "consumo")


class ImutabilidadeTests(EstoqueBase):
    def test_movimento_imutavel(self):
        mov = registrar_entrada(self.produto, self.almox, 3, Decimal("1.00"), self.user)
        mov.quantidade = Decimal("9")
        with self.assertRaises(ValidationError):
            mov.save()
        with self.assertRaises(ValidationError):
            mov.delete()

    def test_movimento_quantidade_nao_zero(self):
        with self.assertRaises(ValidationError):
            MovimentoEstoque(
                produto=self.produto, local=self.almox,
                tipo=MovimentoEstoque.Tipo.AJUSTE, quantidade=Decimal("0"),
                criado_por=self.user,
            ).save()


class TransferenciaTests(EstoqueBase):
    def test_transferencia_dois_lados(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        saida, entrada = transferir(self.produto, self.almox, self.loja, 4, self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("6.000"))
        self.assertEqual(saldo(self.produto, self.loja), Decimal("4.000"))
        self.assertEqual(saldo(self.produto), Decimal("10.000"))  # total inalterado
        self.assertEqual(saida.transferencia_par, entrada)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="transferencia_estoque").exists()
        )

    def test_transferencia_valida_saldo_e_locais(self):
        with self.assertRaises(ValidationError):
            transferir(self.produto, self.almox, self.almox, 1, self.user)
        with self.assertRaises(ValidationError):
            transferir(self.produto, self.almox, self.loja, 1, self.user)  # sem saldo


class AjusteEInventarioTests(EstoqueBase):
    def test_ajuste_gera_diferenca_e_audita(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        ajustar(self.produto, self.almox, 8, self.user, motivo="quebra")
        self.assertEqual(saldo(self.produto, self.almox), Decimal("8.000"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="ajuste_estoque").exists())

    def test_inventario_aplica_ajustes(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        inv = Inventario.objects.create(local=self.almox, criado_por=self.user)
        ItemInventario.objects.create(
            inventario=inv, produto=self.produto,
            saldo_sistema=Decimal("10"), quantidade_contada=Decimal("7"),
        )
        inv.aplicar(self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("7.000"))
        self.assertEqual(inv.status, Inventario.Status.APLICADO)
        with self.assertRaises(ValidationError):
            inv.aplicar(self.user)  # não aplica duas vezes

    def test_posicao_e_alerta_minimo(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        # 10 < mínimo 24 → alerta
        self.assertEqual(produtos_abaixo_minimo(), 1)
        registrar_entrada(self.produto, self.almox, 20, Decimal("2.00"), self.user)
        self.assertEqual(produtos_abaixo_minimo(), 0)
        linhas = posicao_estoque(self.almox)
        self.assertEqual(linhas[0]["saldo"], Decimal("30.000"))


class PermissaoTests(EstoqueBase):
    def test_view_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("estoque:posicao")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        self.client.login(username="estoquista", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("estoque:posicao")).status_code, 404)

    def test_fluxo_entrada_pela_view(self):
        self.client.login(username="estoquista", password="senha-forte-123")
        resposta = self.client.post(
            reverse("estoque:entrada"),
            {
                "produto": self.produto.pk, "local": self.almox.pk,
                "quantidade": "12", "custo_unitario": "2.5",
                "documento": "NF 10", "observacao": "",
            },
        )
        self.assertRedirects(resposta, reverse("estoque:posicao"))
        self.assertEqual(saldo(self.produto, self.almox), Decimal("12.000"))

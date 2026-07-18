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
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    TipoUH,
    registrar_entrada,
    saldo,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import Conferencia, ItemComposicao

Usuario = get_user_model()


class FrigobarBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="frig", password="senha-forte-123")
        cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.agua = Produto.objects.create(nome="Água", categoria=cat, preco_venda=Decimal("5.00"))
        self.cerveja = Produto.objects.create(nome="Cerveja", categoria=cat, preco_venda=Decimal("12.00"))
        self.central = LocalEstoque.objects.create(nome="Frigobar central", modulo="frigobar")
        registrar_entrada(self.agua, self.central, 100, Decimal("1.00"), self.op)
        registrar_entrada(self.cerveja, self.central, 100, Decimal("4.00"), self.op)

        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        ItemComposicao.objects.create(tipo_uh=self.tipo, produto=self.agua, quantidade=2)
        ItemComposicao.objects.create(tipo_uh=self.tipo, produto=self.cerveja, quantidade=1)

    def conta_aberta(self):
        from apps.reservas.models import Reserva
        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        return r.fazer_checkin(self.op)


class ConferenciaTests(FrigobarBase):
    def test_conferencia_lanca_consumo_na_conta(self):
        from apps.reservas.models import LancamentoConta
        conta = self.conta_aberta()
        base = conta.total_lancamentos()
        conf = services.registrar_conferencia(
            self.op, conta, "checkout", [(self.agua, 1), (self.cerveja, 2)]
        )
        # 1×5 + 2×12 = 29
        self.assertEqual(conf.total(), Decimal("29.00"))
        self.assertEqual(conta.total_lancamentos(), base + Decimal("29.00"))
        self.assertTrue(
            LancamentoConta.objects.filter(conta=conta, tipo="consumo", natureza="consumo").exists()
        )

    def test_conferencia_sem_consumo_nao_cobra(self):
        conta = self.conta_aberta()
        base = conta.total_lancamentos()
        conf = services.registrar_conferencia(self.op, conta, "arrumacao", [(self.agua, 0)])
        self.assertEqual(conf.itens.count(), 0)
        self.assertEqual(conta.total_lancamentos(), base)

    def test_reposicao_baixa_estoque_central(self):
        conta = self.conta_aberta()
        conf = services.registrar_conferencia(self.op, conta, "checkout", [(self.cerveja, 3)])
        self.assertEqual(saldo(self.cerveja, self.central), Decimal("100"))  # ainda não repôs
        services.repor(conf, self.op, self.central)
        conf.refresh_from_db()
        self.assertEqual(conf.status, Conferencia.Status.REPOSTA)
        self.assertEqual(saldo(self.cerveja, self.central), Decimal("97"))

    def test_repor_duas_vezes_bloqueia(self):
        conta = self.conta_aberta()
        conf = services.registrar_conferencia(self.op, conta, "checkout", [(self.agua, 1)])
        services.repor(conf, self.op, self.central)
        with self.assertRaises(ValidationError):
            services.repor(conf, self.op, self.central)

    def test_lista_reposicao_agrega_pendentes(self):
        conta = self.conta_aberta()
        services.registrar_conferencia(self.op, conta, "arrumacao", [(self.agua, 2)])
        services.registrar_conferencia(self.op, conta, "arrumacao", [(self.agua, 3)])
        lista = {r["produto__nome"]: r["total"] for r in services.lista_reposicao()}
        self.assertEqual(lista["Água"], 5)

    def test_conferencia_checkout_feita(self):
        conta = self.conta_aberta()
        self.assertFalse(services.conferencia_checkout_feita(conta=conta))
        # Arrumação não libera o check-out.
        services.registrar_conferencia(self.op, conta, "arrumacao", [])
        self.assertFalse(services.conferencia_checkout_feita(conta=conta))
        conf = services.registrar_conferencia(self.op, conta, "checkout", [])
        self.assertEqual(conf.conta_id, conta.pk)
        self.assertTrue(services.conferencia_checkout_feita(conta=conta))


class PermissaoTests(FrigobarBase):
    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.FRIGOBAR).update(ativo=False)
        self.client.login(username="frig", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("frigobar:painel")).status_code, 404)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("frigobar:painel")).status_code, 403)

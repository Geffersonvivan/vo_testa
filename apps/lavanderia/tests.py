from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import ItemEnxoval, MovimentoEnxoval, OrdemLavanderia, ServicoLavanderia

Usuario = get_user_model()
Estado = MovimentoEnxoval.Estado


class LavanderiaBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="lav", password="senha-forte-123")
        self.camisa = ServicoLavanderia.objects.create(nome="Camisa", preco=Decimal("8.00"))
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def abrir_caixa(self):
        return SessaoCaixa.objects.create(operador=self.op, modulo="nucleo",
                                          fundo_troco=Decimal("0.00"))


# ───────── (a) Serviço ao hóspede ─────────

class OrdemHospedeTests(LavanderiaBase):
    def test_abrir_exige_identificacao(self):
        with self.assertRaises(ValidationError):
            services.abrir_ordem(self.op)

    def test_item_agrupa_e_soma(self):
        o = services.abrir_ordem(self.op, rotulo="Quarto 5")
        services.adicionar_item(o, self.camisa, 2, self.op)
        services.adicionar_item(o, self.camisa, 1, self.op)
        self.assertEqual(o.itens.count(), 1)
        self.assertEqual(o.total(), Decimal("24.00"))

    def test_fluxo_status(self):
        o = services.abrir_ordem(self.op, rotulo="Q1")
        self.assertEqual(o.status, OrdemLavanderia.Status.RECEBIDA)
        services.avancar_status(o)
        self.assertEqual(o.status, OrdemLavanderia.Status.LAVANDO)
        services.avancar_status(o)
        self.assertEqual(o.status, OrdemLavanderia.Status.PRONTA)
        with self.assertRaises(ValidationError):
            services.avancar_status(o)  # não passa de pronta

    def test_entregar_no_caixa(self):
        sessao = self.abrir_caixa()
        o = services.abrir_ordem(self.op, rotulo="Q1")
        services.adicionar_item(o, self.camisa, 2, self.op)
        services.entregar(o, self.op, "caixa", forma=self.dinheiro)
        o.refresh_from_db()
        self.assertEqual(o.status, OrdemLavanderia.Status.ENTREGUE)
        self.assertIsNotNone(o.movimento_caixa)
        self.assertEqual(sessao.esperado_em_dinheiro(), Decimal("16.00"))

    def test_entregar_na_conta_do_quarto_como_servico(self):
        from apps.reservas.models import LancamentoConta, Reserva
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Quarto 01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        conta = r.fazer_checkin(self.op)
        o = services.abrir_ordem(self.op, cliente=hospede)
        services.adicionar_item(o, self.camisa, 3, self.op)
        services.entregar(o, self.op, "conta", conta_id=conta.pk)
        lanc = LancamentoConta.objects.filter(conta=conta, tipo="servico").first()
        self.assertIsNotNone(lanc)
        self.assertEqual(lanc.natureza, "servico")

    def test_cancelar_entregue_bloqueia(self):
        self.abrir_caixa()
        o = services.abrir_ordem(self.op, rotulo="Q1")
        services.adicionar_item(o, self.camisa, 1, self.op)
        services.entregar(o, self.op, "caixa", forma=self.dinheiro)
        with self.assertRaises(ValidationError):
            services.cancelar_ordem(o, self.op, "tarde demais")


# ───────── (b) Rouparia interna ─────────

class RoupariaTests(LavanderiaBase):
    def setUp(self):
        super().setUp()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol", minimo=10, por_faxina=1)

    def test_ciclo_completo(self):
        services.adquirir(self.lencol, 50, self.op)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.LIMPA), 50)
        services.distribuir(self.lencol, 20, self.op)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.EM_USO), 20)
        services.coletar_suja(self.lencol, 8, self.op)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.SUJA), 8)
        services.enviar_lavar(self.lencol, 8, self.op)
        services.receber_limpo(self.lencol, 8, self.op)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.LIMPA), 38)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.SUJA), 0)

    def test_nao_move_sem_saldo(self):
        services.adquirir(self.lencol, 5, self.op)
        with self.assertRaises(ValidationError):
            services.distribuir(self.lencol, 10, self.op)

    def test_movimento_imutavel(self):
        services.adquirir(self.lencol, 5, self.op)
        mov = self.lencol.movimentos.first()
        mov.quantidade = 99
        with self.assertRaises(ValidationError):
            mov.save()

    def test_baixa_auditada(self):
        services.adquirir(self.lencol, 5, self.op)
        services.baixar(self.lencol, 2, Estado.LIMPA, "rasgado", self.op)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.LIMPA), 3)
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="baixa_enxoval").exists())

    def test_faxina_recolhe_enxoval(self):
        # em uso disponível para a coleta automática pela faxina
        services.adquirir(self.lencol, 10, self.op)
        services.distribuir(self.lencol, 4, self.op)
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        uh = UH.objects.create(numero="Quarto 07", tipo=tipo)
        from apps.governanca import services as gov
        tarefa = gov.abrir_faxina(uh, usuario=self.op)
        gov.concluir_tarefa(tarefa, self.op)  # dispara o sinal → coleta
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.SUJA), 1)  # por_faxina=1
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.EM_USO), 3)


class PermissaoTests(LavanderiaBase):
    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.LAVANDERIA).update(ativo=False)
        self.client.login(username="lav", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("lavanderia:painel")).status_code, 404)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("lavanderia:painel")).status_code, 403)

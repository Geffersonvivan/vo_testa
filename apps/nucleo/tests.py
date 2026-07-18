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
        self.assertContains(resposta, "Visão geral")

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
    def test_seed_ativou_os_modulos_da_fase_1(self):
        # 11 da fase 1 + Auditoria + Relatórios + Comercial (migrações dos módulos) = 14
        self.assertEqual(ModuloContratado.objects.filter(ativo=True).count(), 14)
        self.assertTrue(modulo_ativo(Modulo.RESERVAS))
        self.assertTrue(modulo_ativo(Modulo.LOJA))
        self.assertTrue(modulo_ativo(Modulo.AUDITORIA))
        self.assertTrue(modulo_ativo(Modulo.RELATORIOS))
        self.assertTrue(modulo_ativo(Modulo.COMERCIAL))
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


# ============================================================
# Núcleo completo: cadastros, financeiro/caixa, logbook
# ============================================================

from datetime import date, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from .models import (  # noqa: E402
    UH,
    CategoriaFinanceira,
    ContaPagarReceber,
    FormaPagamento,
    Hospede,
    LancamentoFinanceiro,
    MovimentoCaixa,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    TrilhaAuditoria,
    estornar_movimento,
)


class CadastrosTests(TestCase):
    def test_pessoa_com_especializacao_hospede(self):
        pessoa = Pessoa.objects.create(nome="Maria Silva", documento="111.222.333-44")
        Hospede.objects.create(pessoa=pessoa, preferencias="Quarto silencioso")
        self.assertEqual(pessoa.papeis, ["Hóspede"])

    def test_uh_exige_numero_unico(self):
        tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("250.00"))
        UH.objects.create(numero="01", tipo=tipo)
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            UH.objects.create(numero="01", tipo=tipo)

    def test_temporada_rejeita_fim_antes_do_inicio(self):
        temporada = Temporada(
            nome="Réveillon",
            classificacao=Temporada.Classificacao.SUPER_ALTA,
            inicio=date(2026, 12, 28),
            fim=date(2026, 12, 20),
        )
        with self.assertRaises(ValidationError):
            temporada.full_clean()


class CaixaTestsBase(TestCase):
    def setUp(self):
        self.operador = Usuario.objects.create_user(
            username="recepcao", password="senha-forte-123"
        )
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.pix = FormaPagamento.objects.get(tipo="pix")
        self.sessao = SessaoCaixa.objects.create(
            operador=self.operador, modulo="nucleo", fundo_troco=Decimal("100.00")
        )

    def receber(self, valor, forma=None, descricao="Diária"):
        movimento = MovimentoCaixa(
            sessao=self.sessao,
            tipo=MovimentoCaixa.Tipo.RECEBIMENTO,
            forma_pagamento=forma or self.dinheiro,
            valor=Decimal(valor),
            descricao=descricao,
            criado_por=self.operador,
        )
        movimento.save()
        return movimento


class RegrasDeCaixaTests(CaixaTestsBase):
    def test_apenas_uma_sessao_aberta_por_operador_e_modulo(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SessaoCaixa.objects.create(operador=self.operador, modulo="nucleo")

    def test_movimento_e_imutavel(self):
        movimento = self.receber("50.00")
        movimento.valor = Decimal("60.00")
        with self.assertRaises(ValidationError):
            movimento.save()
        with self.assertRaises(ValidationError):
            movimento.delete()

    def test_movimento_exige_sessao_aberta(self):
        self.sessao.fechar(Decimal("150.00"), self.operador)
        with self.assertRaises(ValidationError):
            self.receber("10.00")

    def test_esperado_em_dinheiro_considera_apenas_dinheiro(self):
        self.receber("200.00")                      # dinheiro
        self.receber("300.00", forma=self.pix)      # pix não entra na gaveta
        MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.SANGRIA,
            valor=Decimal("80.00"), descricao="Sangria cofre",
            criado_por=self.operador,
        ).save()
        MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.REFORCO,
            valor=Decimal("30.00"), descricao="Reforço de troco",
            criado_por=self.operador,
        ).save()
        # 100 fundo + 200 dinheiro + 30 reforço − 80 sangria = 250
        self.assertEqual(self.sessao.esperado_em_dinheiro(), Decimal("250.00"))

    def test_fechamento_cego_aponta_diferenca(self):
        self.receber("200.00")
        self.sessao.fechar(Decimal("290.00"), self.operador)  # esperado: 300
        self.assertEqual(self.sessao.diferenca, Decimal("-10.00"))
        self.assertEqual(self.sessao.status, SessaoCaixa.Status.FECHADA)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="fechamento_caixa").exists()
        )

    def test_estorno_exige_motivo_e_nao_excede_original(self):
        movimento = self.receber("100.00")
        with self.assertRaises(ValidationError):
            estornar_movimento(movimento, self.sessao, self.gerente, motivo="")
        estornar_movimento(
            movimento, self.sessao, self.gerente, "Cobrança duplicada",
            valor=Decimal("60.00"),
        )
        with self.assertRaises(ValidationError):
            estornar_movimento(
                movimento, self.sessao, self.gerente, "De novo",
                valor=Decimal("50.00"),  # 60 + 50 > 100
            )
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="estorno").exists())

    def test_so_recebimento_pode_ser_estornado(self):
        sangria = MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.SANGRIA,
            valor=Decimal("10.00"), descricao="Sangria",
            criado_por=self.operador,
        )
        sangria.save()
        with self.assertRaises(ValidationError):
            estornar_movimento(sangria, self.sessao, self.gerente, "Teste")

    def test_reabertura_exige_motivo_e_audita(self):
        self.sessao.fechar(Decimal("100.00"), self.operador)
        with self.assertRaises(ValidationError):
            self.sessao.reabrir(self.gerente, motivo="  ")
        self.sessao.reabrir(self.gerente, motivo="Faltou lançar um recebimento")
        self.assertTrue(self.sessao.aberta)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="reabertura_caixa").exists()
        )

    def test_view_estorno_exige_gerencia(self):
        movimento = self.receber("50.00")
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.post(
            reverse("estorno", args=[movimento.pk]),
            {"valor": "50.00", "motivo": "Tentativa sem permissão"},
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(movimento.estornos.count(), 0)

    def test_fluxo_caixa_pelas_views(self):
        outro = Usuario.objects.create_user(
            username="loja", password="senha-forte-123"
        )
        self.client.login(username="loja", password="senha-forte-123")
        self.client.post(
            reverse("caixa_abrir"), {"modulo": "nucleo", "fundo_troco": "50.00"}
        )
        sessao = SessaoCaixa.objects.get(operador=outro)
        self.client.post(
            reverse("caixa_movimento"),
            {
                "tipo": "recebimento",
                "forma_pagamento": self.dinheiro.pk,
                "valor": "70.00",
                "parcelas": "1",
                "descricao": "Venda balcão",
            },
        )
        self.client.post(
            reverse("caixa_fechar"), {"valor_contado": "120.00", "observacoes": ""}
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.status, SessaoCaixa.Status.FECHADA)
        self.assertEqual(sessao.diferenca, Decimal("0.00"))


class FinanceiroTests(CaixaTestsBase):
    def setUp(self):
        super().setUp()
        self.categoria_despesa = CategoriaFinanceira.objects.create(
            nome="Insumos", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        self.categoria_receita = CategoriaFinanceira.objects.create(
            nome="Hospedagem", tipo=CategoriaFinanceira.Tipo.RECEITA
        )

    def test_lancamento_valida_tipo_da_categoria(self):
        lancamento = LancamentoFinanceiro(
            tipo="receita", categoria=self.categoria_despesa,
            descricao="Errado", valor=Decimal("10.00"), criado_por=self.operador,
        )
        with self.assertRaises(ValidationError):
            lancamento.full_clean()

    def test_baixa_de_conta_gera_lancamento_e_audita(self):
        fornecedor = Pessoa.objects.create(nome="Hortifrúti do Vale")
        conta = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR,
            pessoa=fornecedor,
            categoria=self.categoria_despesa,
            descricao="Frutas da semana",
            valor=Decimal("340.00"),
            vencimento=date.today(),
        )
        conta.baixar(self.operador)
        self.assertEqual(conta.status, ContaPagarReceber.Status.BAIXADA)
        self.assertIsNotNone(conta.lancamento)
        self.assertEqual(conta.lancamento.tipo, "despesa")
        self.assertEqual(conta.lancamento.valor, Decimal("340.00"))
        with self.assertRaises(ValidationError):
            conta.baixar(self.operador)  # não baixa duas vezes
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="baixa_conta").exists())

    def test_conta_vencida(self):
        conta = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR,
            categoria=self.categoria_despesa,
            descricao="Atrasada",
            valor=Decimal("10.00"),
            vencimento=date.today() - timedelta(days=1),
        )
        self.assertTrue(conta.vencida)


class LogbookTests(TestCase):
    def test_registro_pela_view(self):
        Usuario.objects.create_user(username="turno", password="senha-forte-123")
        self.client.login(username="turno", password="senha-forte-123")
        resposta = self.client.post(
            reverse("logbook"),
            {"texto": "Hóspede do 12 pediu late check-out.", "importante": "on"},
        )
        self.assertRedirects(resposta, reverse("logbook"))
        resposta = self.client.get(reverse("logbook"))
        self.assertContains(resposta, "late check-out")


class CadastroRapidoTests(TestCase):
    def setUp(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        self.client.login(username="recepcao", password="senha-forte-123")

    def test_cria_hospede_e_devolve_json(self):
        resposta = self.client.post(
            reverse("pessoa_nova_rapida"),
            {"nome": "Peterson", "documento": "043.015.359-77",
             "telefone": "(49) 99143-8813"},
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        pessoa = Pessoa.objects.get(pk=dados["id"])
        self.assertEqual(dados["nome"], "Peterson")
        self.assertTrue(hasattr(pessoa, "hospede"))

    def test_nome_obrigatorio(self):
        resposta = self.client.post(reverse("pessoa_nova_rapida"), {"nome": "  "})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("erro", resposta.json())

    def test_exige_login(self):
        self.client.logout()
        resposta = self.client.post(reverse("pessoa_nova_rapida"), {"nome": "X"})
        self.assertEqual(resposta.status_code, 302)


class TabelaPessoasTests(TestCase):
    def setUp(self):
        from apps.nucleo.models import Agencia, Fornecedor, Hospede
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        self.client.login(username="recepcao", password="senha-forte-123")
        h = Pessoa.objects.create(nome="Hóspede Um")
        Hospede.objects.create(pessoa=h)
        f = Pessoa.objects.create(nome="Fornecedor Um", tipo=Pessoa.Tipo.JURIDICA)
        Fornecedor.objects.create(pessoa=f)
        a = Pessoa.objects.create(nome="Agência Um", tipo=Pessoa.Tipo.JURIDICA)
        Agencia.objects.create(pessoa=a)
        Pessoa.objects.create(nome="Avulso Um")  # sem papel

    def test_filtro_por_papel(self):
        r = self.client.get(reverse("pessoas"), {"papel": "agencias"})
        self.assertContains(r, "Agência Um")
        self.assertNotContains(r, "Fornecedor Um")

    def test_filtro_avulsos(self):
        r = self.client.get(reverse("pessoas"), {"papel": "avulsos"})
        self.assertContains(r, "Avulso Um")
        self.assertNotContains(r, "Hóspede Um")

    def test_sigla_tipo(self):
        self.assertEqual(Pessoa.objects.get(nome="Fornecedor Um").sigla_tipo, "PJ")
        self.assertEqual(Pessoa.objects.get(nome="Hóspede Um").sigla_tipo, "PF")


class CentralModulosTests(TestCase):
    def setUp(self):
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )
        self.operador = Usuario.objects.create_user(
            username="op", password="senha-forte-123"
        )

    def test_exige_gerencia(self):
        self.client.login(username="op", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("modulos_central")).status_code, 403
        )

    def test_carrega_para_gerencia(self):
        self.client.login(username="gerente", password="senha-forte-123")
        r = self.client.get(reverse("modulos_central"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Central de Módulos")

    def test_ativar_modulo_disponivel(self):
        self.client.login(username="gerente", password="senha-forte-123")
        self.assertFalse(modulo_ativo(Modulo.FISCAL))
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.FISCAL, "acao": "ativar"},
        )
        self.assertTrue(modulo_ativo(Modulo.FISCAL))

    def test_ativar_sem_dependencia_falha(self):
        # Loja exige Estoque: desativa Estoque no banco e tenta ativar Loja isolada
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.client.login(username="gerente", password="senha-forte-123")
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.LOJA, "acao": "ativar"},
        )
        self.assertFalse(modulo_ativo(Modulo.LOJA))

    def test_desativar_bloqueado_por_dependente(self):
        # Estoque tem Loja ativa dependendo dele → não pode desativar
        self.client.login(username="gerente", password="senha-forte-123")
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.ESTOQUE, "acao": "desativar"},
        )
        self.assertTrue(modulo_ativo(Modulo.ESTOQUE))

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
        outro.areas = ["financeiro"]
        outro.save()
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


class AreaCaixaTests(TestCase):
    """Operar o próprio caixa (área 'caixa') é separado da gestão financeira."""

    def setUp(self):
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def _user(self, username, areas):
        u = Usuario.objects.create_user(username=username, password="senha-forte-123")
        u.areas = areas
        u.save()
        self.client.force_login(u)
        return u

    def test_area_caixa_abre_o_proprio_caixa(self):
        u = self._user("atendente", ["caixa"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 200)
        self.client.post(
            reverse("caixa_abrir"), {"modulo": "nucleo", "fundo_troco": "50.00"}
        )
        self.assertTrue(SessaoCaixa.objects.filter(operador=u).exists())

    def test_sem_caixa_nem_financeiro_bloqueia(self):
        self._user("semacesso", ["logbook"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 403)

    def test_financeiro_ainda_acessa_caixa(self):
        self._user("gestor", ["financeiro"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 200)

    def test_caixa_nao_da_acesso_a_gestao_financeira(self):
        self._user("atendente", ["caixa"])
        self.assertEqual(self.client.get(reverse("contas")).status_code, 403)
        self.assertEqual(self.client.get(reverse("lancamentos")).status_code, 403)


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
        u = Usuario.objects.create_user(username="turno", password="senha-forte-123")
        u.areas = ["logbook"]
        u.save()
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
        u = Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        u.areas = ["pessoas"]
        u.save()
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


class MoedaFiltroTests(TestCase):
    """Filtro de moeda único do sistema (apps/nucleo/templatetags/moeda.py)."""

    def _fmt(self, valor):
        from apps.nucleo.templatetags.moeda import intcomma_brl
        return intcomma_brl(valor)

    def test_zero(self):
        self.assertEqual(self._fmt(0), "R$ 0,00")

    def test_milhar(self):
        self.assertEqual(self._fmt(1600), "R$ 1.600,00")

    def test_milhao_com_centavos(self):
        self.assertEqual(self._fmt(Decimal("1234567.5")), "R$ 1.234.567,50")

    def test_negativo(self):
        self.assertEqual(self._fmt(Decimal("-67.5")), "-R$ 67,50")

    def test_none_e_vazio(self):
        self.assertEqual(self._fmt(None), "R$ 0,00")
        self.assertEqual(self._fmt(""), "R$ 0,00")

    def test_invalido(self):
        self.assertEqual(self._fmt("abc"), "R$ 0,00")


class EstruturaCamasTests(TestCase):
    """Capacidade derivada da unidade e frase de camas gerada (Passo 2).

    Os 24 quartos vêm de um seed manual (não de migração), então o teste cria a
    estrutura e roda o seeder de camas para valer sobre dados controlados.
    """

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        from apps.nucleo.management.commands.popular_camas import semear_camas
        from apps.nucleo.models import UH, TipoUH

        # As unidades day use (DAY-01..08) já vêm da migração 0015; aqui criamos
        # só os 24 quartos de pernoite (que em produção vêm do seed manual).
        hosp = TipoUH.objects.create(nome="Hospedagem Teste", tarifa_base=Decimal("250"))
        for i in range(1, 25):
            UH.objects.create(numero=f"Quarto {i:02d}", tipo=hosp)
        semear_camas()

    def _uh(self, numero):
        from apps.nucleo.models import UH
        return UH.objects.get(numero=numero)

    def test_lotacao_total_bate_118_e_131(self):
        from apps.nucleo.estrutura import capacidade
        from apps.nucleo.models import UH
        hosp = UH.objects.filter(tipo__modalidade="hospedagem")
        self.assertEqual(sum(capacidade(u)["maxima"] for u in hosp), 118)
        self.assertEqual(sum(capacidade(u)["maxima_criancas"] for u in hosp), 131)
        self.assertEqual(sum(capacidade(u)["fixa"] for u in hosp), 70)
        self.assertEqual(sum(capacidade(u)["extras"] for u in hosp), 35)

    def test_dois_comodos_com_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 17"))
        self.assertEqual(cap["maxima"], 7)
        self.assertEqual(cap["maxima_criancas"], 8)

    def test_um_comodo_com_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 09"))
        self.assertEqual(cap["maxima"], 4)
        self.assertEqual(cap["maxima_criancas"], 5)

    def test_um_comodo_sem_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 03"))
        self.assertEqual(cap["maxima"], 3)
        self.assertEqual(cap["maxima_criancas"], 3)

    def test_day_use_zero_e_sem_camas(self):
        from apps.nucleo.estrutura import capacidade, descricao_camas
        from apps.nucleo.models import UH
        day = UH.objects.filter(tipo__modalidade="day_use").first()
        self.assertEqual(capacidade(day)["maxima"], 0)
        self.assertEqual(
            descricao_camas(day), "Sem pernoite · acesso à estrutura no período"
        )

    def test_descricao_dois_comodos_exata(self):
        from apps.nucleo.estrutura import descricao_camas
        self.assertEqual(
            descricao_camas(self._uh("Quarto 17")),
            "Quarto 1 com 1 cama de casal · Quarto 2 com 1 cama de casal · "
            "sofá-cama para 1 adulto ou 2 crianças até 15 anos · "
            "até 2 colchões de solteiro extras",
        )

    def test_descricao_um_comodo_omite_prefixo(self):
        from apps.nucleo.estrutura import descricao_camas
        self.assertEqual(
            descricao_camas(self._uh("Quarto 03")),
            "1 cama de casal · até 1 colchão de solteiro extra",
        )

    def test_faixa_do_tipo_mostra_intervalo(self):
        """Quando as unidades do tipo variam, a faixa é 'N a M', não 'até M'."""
        from decimal import Decimal

        from apps.nucleo.estrutura import faixa_do_tipo
        from apps.nucleo.models import UH, ConfiguracaoUH, PosicaoCama, TipoUH
        tipo = TipoUH.objects.create(nome="Teste Faixa", tarifa_base=Decimal("200"))
        pequena = UH.objects.create(numero="TST-P", tipo=tipo)
        PosicaoCama.objects.create(uh=pequena, nome="Quarto", ordem=0)
        grande = UH.objects.create(numero="TST-G", tipo=tipo)
        PosicaoCama.objects.create(uh=grande, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=grande, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(uh=grande, tem_sofa_cama=True, max_colchoes_extras=2)
        self.assertEqual(faixa_do_tipo(tipo), "2 a 8 pessoas")


class EquipeAcessosTests(TestCase):
    """Equipe & Acessos: gating por área, gestão de usuários e travas."""

    def setUp(self):
        self.dono = Usuario.objects.create_superuser(
            username="dono", password="senha-forte-123"
        )
        self.op = Usuario.objects.create_user(
            username="operador", password="senha-forte-123"
        )

    def test_pode_area(self):
        self.assertFalse(self.op.pode_area("quartos"))
        self.op.areas = ["quartos"]
        self.assertTrue(self.op.pode_area("quartos"))
        self.assertTrue(self.dono.pode_area("financeiro"))  # super bypassa

    def test_estrutura_gateada_por_area(self):
        self.client.force_login(self.op)
        self.assertEqual(self.client.get(reverse("estrutura")).status_code, 403)
        self.op.areas = ["quartos"]
        self.op.save()
        self.assertEqual(self.client.get(reverse("estrutura")).status_code, 200)

    # A gestão de acesso migrou para a ficha do Funcionário — coberta em
    # FuncionariosTests (conceder acesso, salário só-gerência, self-protection).


class AuditoriaAutomaticaTests(TestCase):
    """Piso garantido: escrita em model de negócio com usuário no contexto vira trilha."""

    def setUp(self):
        from apps.nucleo import audit
        self.audit = audit
        self.user = Usuario.objects.create_user(username="rec", password="x")

    def tearDown(self):
        self.audit.limpar_contexto()

    def _pessoa(self):
        from apps.nucleo.models import Pessoa
        return Pessoa

    def _trilha(self, **f):
        from apps.nucleo.models import TrilhaAuditoria
        return TrilhaAuditoria.objects.filter(**f)

    def test_sem_usuario_no_contexto_nao_registra(self):
        self.audit.limpar_contexto()
        p = self._pessoa().objects.create(nome="Anônimo")
        self.assertFalse(self._trilha(alvo="Pessoa", alvo_id=str(p.pk)).exists())

    def test_criar_registra_com_usuario_e_ip(self):
        self.audit.definir_contexto(self.user, "200.1.2.3")
        p = self._pessoa().objects.create(nome="Fulano")
        t = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="criar").first()
        self.assertIsNotNone(t)
        self.assertEqual(t.usuario, self.user)
        self.assertEqual(t.ip, "200.1.2.3")
        self.assertIn("valores", t.detalhe)

    def test_editar_registra_diff(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        p.nome = "Beltrano"
        p.save()
        t = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="editar").first()
        self.assertIsNotNone(t)
        self.assertEqual(t.detalhe["alteracoes"]["nome"], ["Fulano", "Beltrano"])

    def test_save_sem_mudanca_nao_registra_edicao(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        antes = self._trilha(alvo="Pessoa", acao="editar").count()
        p.save()  # nenhum campo mudou
        self.assertEqual(self._trilha(alvo="Pessoa", acao="editar").count(), antes)

    def test_excluir_registra(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        pk = p.pk
        p.delete()
        self.assertTrue(
            self._trilha(alvo="Pessoa", alvo_id=str(pk), acao="excluir").exists()
        )

    def test_middleware_define_e_limpa_contexto(self):
        from django.test import RequestFactory
        capturado = {}

        def get_response(req):
            capturado["u"] = self.audit.usuario_atual()
            capturado["ip"] = self.audit.ip_atual()
            return "ok"

        req = RequestFactory().get("/", REMOTE_ADDR="9.9.9.9")
        req.user = self.user
        self.audit.AuditContextMiddleware(get_response)(req)
        self.assertEqual(capturado["u"], self.user)
        self.assertEqual(capturado["ip"], "9.9.9.9")
        self.assertIsNone(self.audit.usuario_atual())  # limpou depois da requisição

    def test_usuario_anonimo_nao_vira_contexto(self):
        from django.contrib.auth.models import AnonymousUser
        self.audit.definir_contexto(AnonymousUser(), "1.1.1.1")
        self.assertIsNone(self.audit.usuario_atual())

    def test_login_registra_na_trilha(self):
        self.user.set_password("senha-forte-123")
        self.user.save()
        self.client.login(username="rec", password="senha-forte-123")
        t = self._trilha(alvo="Usuario", acao="login", usuario=self.user).first()
        self.assertIsNotNone(t)

    def test_logout_registra_na_trilha(self):
        self.user.set_password("senha-forte-123")
        self.user.save()
        self.client.login(username="rec", password="senha-forte-123")
        self.client.logout()
        self.assertTrue(
            self._trilha(alvo="Usuario", acao="logout", usuario=self.user).exists()
        )


class FuncionariosTests(TestCase):
    """Onda 1: tela de Funcionários (RH) + acesso derivando do funcionário."""

    def setUp(self):
        from apps.nucleo.models import Funcionario, Pessoa
        self.Funcionario = Funcionario
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        p = Pessoa.objects.create(nome="Fulano")
        self.func = Funcionario.objects.create(pessoa=p, cargo="Recepcionista")

    def test_lista_exige_area(self):
        op = Usuario.objects.create_user(username="op", password="x")
        self.client.force_login(op)
        self.assertEqual(self.client.get(reverse("funcionarios")).status_code, 403)
        op.areas = ["funcionarios"]; op.save()
        self.assertEqual(self.client.get(reverse("funcionarios")).status_code, 200)

    def test_novo_cria_pessoa_e_funcionario(self):
        self.client.force_login(self.dono)
        n = self.Funcionario.objects.count()
        self.client.post(reverse("funcionario_novo"), {"nome": "Nova Camareira", "cargo": "Camareira"})
        self.assertEqual(self.Funcionario.objects.count(), n + 1)
        self.assertTrue(self.Funcionario.objects.filter(pessoa__nome="Nova Camareira").exists())

    def test_gerencia_edita_rh_e_salario(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano da Silva", "cargo": "Gerente", "setor": "Recepção",
            "turno": "manha", "carga_semanal": "40", "salario": "2.400,00",
        })
        self.func.refresh_from_db()
        self.assertEqual(self.func.cargo, "Gerente")
        self.assertEqual(self.func.turno, "manha")
        self.assertEqual(str(self.func.salario), "2400.00")
        self.assertEqual(self.func.pessoa.nome, "Fulano da Silva")

    def test_nao_gerencia_nao_ve_nem_edita_salario(self):
        op = Usuario.objects.create_user(username="rh", password="x")
        op.areas = ["funcionarios"]; op.save()
        self.client.force_login(op)
        r = self.client.get(reverse("funcionario_editar", args=[self.func.pk]))
        self.assertNotContains(r, "Salário base")
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista", "salario": "9999",
        })
        self.func.refresh_from_db()
        self.assertIsNone(self.func.salario)  # ignorado — não é gerência

    def test_gerencia_cria_login_e_concede_acesso(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista",
            "username": "fulano", "password": "senha-forte-123",
            "areas": ["caixa", "logbook"],
        })
        self.func.refresh_from_db()
        self.assertIsNotNone(self.func.usuario)
        self.assertEqual(self.func.usuario.username, "fulano")
        self.assertIn("caixa", self.func.usuario.areas)

    def test_nao_rebaixa_a_si_mesmo(self):
        from apps.nucleo.models import Funcionario, Pessoa
        ger = Usuario.objects.create_user(username="ger", password="x", is_staff=True)
        ger.areas = ["funcionarios"]; ger.save()
        fg = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Ger"), cargo="Gerente", usuario=ger)
        self.client.force_login(ger)
        self.client.post(reverse("funcionario_editar", args=[fg.pk]), {
            "nome": "Ger", "cargo": "Gerente",  # sem 'gerente'/'ativo' — tentaria rebaixar
        })
        ger.refresh_from_db()
        self.assertTrue(ger.is_staff)   # não se rebaixou
        self.assertTrue(ger.is_active)  # não se desativou

    def test_area_invalida_descartada(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista",
            "username": "ful", "password": "senha-forte-123",
            "areas": ["caixa", "hackeando"],
        })
        self.func.refresh_from_db()
        self.assertEqual(self.func.usuario.areas, ["caixa"])  # 'hackeando' fora


class PessoasPapelTests(TestCase):
    """Onda 2: telas separadas por papel (Hóspedes/Agências/Empresas)."""

    def setUp(self):
        from apps.nucleo.models import Agencia, Hospede, Pessoa
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        self.client.force_login(self.dono)
        self.ph = Pessoa.objects.create(nome="Hospede X"); Hospede.objects.create(pessoa=self.ph)
        self.pa = Pessoa.objects.create(nome="Agencia CVC"); Agencia.objects.create(pessoa=self.pa, categoria="agencia")
        self.pe = Pessoa.objects.create(nome="Empresa ACME"); Agencia.objects.create(pessoa=self.pe, categoria="empresa")

    def test_papeis_distingue_agencia_empresa(self):
        self.assertIn("Agência", self.pa.papeis)
        self.assertIn("Empresa", self.pe.papeis)
        self.assertNotIn("Empresa", self.pa.papeis)

    def test_tela_hospedes_so_hospedes(self):
        b = self.client.get(reverse("hospedes")).content.decode()
        self.assertIn("Hospede X", b)
        self.assertNotIn("Agencia CVC", b)
        self.assertNotIn("Empresa ACME", b)

    def test_tela_agencias_so_agencias(self):
        b = self.client.get(reverse("agencias")).content.decode()
        self.assertIn("Agencia CVC", b)
        self.assertNotIn("Empresa ACME", b)

    def test_tela_empresas_so_empresas(self):
        b = self.client.get(reverse("empresas")).content.decode()
        self.assertIn("Empresa ACME", b)
        self.assertNotIn("Agencia CVC", b)

    def test_novo_empresa_cria_agencia_categoria_empresa(self):
        from apps.nucleo.models import Pessoa
        self.client.post(reverse("pessoa_nova") + "?papel=empresa", {
            "nome": "Nova Empresa Ltda", "tipo": "juridica",
            "eh_agencia": "on",
            "agencia-categoria": "empresa", "agencia-comissao_padrao": "0",
        })
        p = Pessoa.objects.filter(nome="Nova Empresa Ltda").first()
        self.assertIsNotNone(p)
        self.assertEqual(p.agencia.categoria, "empresa")

    def test_tela_fornecedores_so_fornecedores(self):
        from apps.nucleo.models import Fornecedor, Pessoa
        pf = Pessoa.objects.create(nome="Hortifruti Itá")
        Fornecedor.objects.create(pessoa=pf, atividade="hortifrúti")
        b = self.client.get(reverse("fornecedores")).content.decode()
        self.assertIn("Hortifruti Itá", b)
        self.assertNotIn("Hospede X", b)
        self.assertNotIn("Empresa ACME", b)

    def test_pessoa_form_nao_mexe_no_funcionario(self):
        from apps.nucleo.models import Funcionario, Pessoa
        p = Pessoa.objects.create(nome="Zé Funcionário")
        Funcionario.objects.create(pessoa=p, cargo="Jardineiro")
        # Salvar a pessoa (sem eh_funcionario, que nem existe mais) não apaga o funcionário.
        self.client.post(reverse("pessoa_editar", args=[p.pk]), {"nome": "Zé F.", "tipo": "fisica"})
        self.assertTrue(Funcionario.objects.filter(pessoa=p).exists())


class HistoricoFuncionarioTests(TestCase):
    """Fase 1: histórico do funcionário montado da trilha, gerência-only."""

    def setUp(self):
        from datetime import date
        from apps.nucleo.models import Funcionario, Pessoa
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        p = Pessoa.objects.create(nome="Zé Cozinha")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Cozinheiro", admissao=date(2024, 3, 12))

    def test_tempo_de_casa(self):
        from datetime import date
        from apps.nucleo.historico import tempo_de_casa
        self.assertIsNone(tempo_de_casa(None))
        self.assertIn("ano", tempo_de_casa(date(2024, 3, 12)))

    def test_progressao_le_da_trilha(self):
        from apps.nucleo.historico import progressao_salarial
        from apps.nucleo.models import TrilhaAuditoria
        TrilhaAuditoria.objects.create(
            usuario=self.dono, acao="editar", alvo="Funcionario", alvo_id=str(self.f.pk),
            detalhe={"alteracoes": {"salario": ["2000", "2200"]}},
        )
        prog = progressao_salarial(self.f)
        self.assertEqual(len(prog), 1)
        self.assertEqual(str(prog[0]["valor"]), "2200")

    def test_painel_historico_so_gerencia(self):
        self.client.force_login(self.dono)
        self.assertContains(self.client.get(reverse("funcionario_painel", args=[self.f.pk])), "Tempo de casa")
        op = Usuario.objects.create_user(username="rh", password="x")
        op.areas = ["funcionarios"]; op.save()
        self.client.force_login(op)
        r = self.client.get(reverse("funcionario_painel", args=[self.f.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Tempo de casa")  # sem aba Histórico p/ não-gerência

    def test_ficha_nao_desativa_superusuario(self):
        from apps.nucleo.models import Funcionario, Pessoa
        dono2 = Usuario.objects.create_superuser(username="dono2", password="senha-forte-123")
        fs = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Dono2"), cargo="Dono", usuario=dono2)
        self.client.force_login(self.dono)  # outro gerente edita a ficha do superusuário
        self.client.post(reverse("funcionario_editar", args=[fs.pk]), {"nome": "Dono2", "cargo": "Dono"})
        dono2.refresh_from_db()
        self.assertTrue(dono2.is_active)   # superusuário não é desativado pela ficha
        self.assertTrue(dono2.is_superuser)

    def test_produtividade_conta_faxinas(self):
        from django.utils import timezone
        from apps.governanca.models import TarefaGovernanca
        from apps.nucleo.historico import produtividade
        from apps.nucleo.models import UH, TipoUH
        u = Usuario.objects.create_user(username="cam", password="x")
        self.f.usuario = u
        self.f.save()
        tipo = TipoUH.objects.create(nome="T", tarifa_base=Decimal("100"))
        uh = UH.objects.create(numero="Q1", tipo=tipo)
        TarefaGovernanca.objects.create(
            uh=uh, camareira=u, status="concluida", concluida_em=timezone.now()
        )
        hoje = timezone.localdate()
        prod = produtividade(self.f, hoje.replace(day=1), hoje)
        self.assertTrue(any("Faxina" in p["rotulo"] for p in prod))

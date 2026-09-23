"""Testes do Passo 1 — fundação do módulo Marketing.

Critério de aceite: migração aplica; módulo ativado e no catálogo (grupo Comercial,
sem tela ainda); verba é singleton; Campanha nasce em 'ideia' e sem anúncio tem gasta=0.
"""
from decimal import Decimal

from django.test import TestCase

from apps.marketing.models import Campanha, VerbaMarketing
from apps.nucleo.areas import Area
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import APRESENTACAO, Modulo


class FundacaoMarketingTests(TestCase):
    def test_modulo_ativado(self):
        self.assertTrue(modulo_ativo(Modulo.MARKETING))

    def test_modulo_no_catalogo_grupo_comercial(self):
        self.assertIn(Modulo.MARKETING, APRESENTACAO)
        info = APRESENTACAO[Modulo.MARKETING]
        self.assertEqual(info["grupo"], "Comercial")
        # Passo 2 ligou a tela: o catálogo aponta para o quadro (aparece na sidebar).
        self.assertEqual(info["url_name"], "marketing:quadro")

    def test_area_marketing_existe(self):
        self.assertIn("marketing", Area.values)

    def test_verba_e_singleton(self):
        v1 = VerbaMarketing.atual()
        v2 = VerbaMarketing.atual()
        self.assertEqual(v1.pk, v2.pk)
        self.assertEqual(VerbaMarketing.objects.count(), 1)

    def test_teto_do_mes_vazio_e_zero(self):
        v = VerbaMarketing.atual()
        self.assertEqual(v.teto_do_mes("2026-09"), Decimal("0"))

    def test_campanha_nasce_ideia_e_sem_anuncio_gasta_zero(self):
        c = Campanha.objects.create(nome="Feriadão de setembro")
        self.assertEqual(c.fase, Campanha.Fase.IDEIA)
        self.assertEqual(c.gasta, Decimal("0.00"))
        self.assertEqual(c.sobra_travada, Decimal("0.00"))
        self.assertEqual(list(c.canais), [])


class QuadroTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="mkt", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_quadro_renderiza_as_7_fases(self):
        r = self.client.get("/crm/marketing/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ideia")
        self.assertContains(r, "Encerrada")
        self.assertContains(r, "Quadro")

    def test_nova_campanha_nasce_em_ideia(self):
        r = self.client.post("/crm/marketing/campanha/nova/", {"nome": "Feriadão"})
        self.assertEqual(r.status_code, 302)
        c = Campanha.objects.get(nome="Feriadão")
        self.assertEqual(c.fase, Campanha.Fase.IDEIA)
        self.assertEqual(c.solicitante_id, self.user.id)

    def test_mover_fase_avanca_um_passo_com_portao_ok(self):
        # portão da Ideia = objetivo (resolve sozinho quando preenchido)
        c = Campanha.objects.create(nome="X", objetivo="vender mais")
        r = self.client.post(f"/crm/marketing/campanha/{c.id}/fase/", {"fase": "proposta"})
        self.assertEqual(r.status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.PROPOSTA)

    def test_mover_fase_recusa_pulo_de_varias_fases(self):
        c = Campanha.objects.create(nome="X", objetivo="v")
        self.client.post(f"/crm/marketing/campanha/{c.id}/fase/", {"fase": "producao"})
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.IDEIA)  # pulo de mais de uma fase recusado

    def test_faixa_atrasado_lista_peca_vencida(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.marketing.models import PecaCampanha
        c = Campanha.objects.create(nome="Y")
        PecaCampanha.objects.create(
            campanha=c, nome="Post atrasado",
            data=timezone.localdate() - timedelta(days=3),
            status=PecaCampanha.Status.A_FAZER)
        r = self.client.get("/crm/marketing/")
        self.assertContains(r, "Post atrasado")


class VerbaTests(TestCase):
    def _mes(self):
        from django.utils import timezone
        return timezone.localdate().strftime("%Y-%m")

    def test_teto_travada_disponivel_e_pct(self):
        from django.utils import timezone
        from apps.marketing import services
        mes = self._mes()
        services.definir_teto(mes, "10000")
        Campanha.objects.create(nome="A", verba_travada=Decimal("5000"),
                                inicio=timezone.localdate())
        pos = services.posicao_verba(mes)
        self.assertEqual(pos["teto"], Decimal("10000"))
        self.assertEqual(pos["travada"], Decimal("5000"))
        self.assertEqual(pos["disponivel"], Decimal("5000"))
        self.assertEqual(pos["pct"], 50)
        self.assertFalse(pos["alerta"])

    def test_alerta_dispara_acima_do_pct(self):
        from django.utils import timezone
        from apps.marketing import services
        mes = self._mes()
        services.definir_teto(mes, "6000")
        Campanha.objects.create(nome="B", verba_travada=Decimal("5000"),
                                inicio=timezone.localdate())
        pos = services.posicao_verba(mes)
        self.assertTrue(pos["alerta"])  # 5000/6000 = 83% ≥ 80

    def test_sobra_nao_acumula_mes_isolado(self):
        from apps.marketing import services
        services.definir_teto("2026-01", "1000")
        self.assertEqual(services.posicao_verba("2026-02")["teto"], Decimal("0"))

    def test_encerrar_devolve_verba_nao_gasta(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from apps.marketing import services
        U = get_user_model()
        u = U.objects.create_user(username="ge", password="x123456789",
                                  is_superuser=True, is_staff=True)
        c = Campanha.objects.create(
            nome="C", verba_travada=Decimal("3000"), inicio=timezone.localdate(),
            fase=Campanha.Fase.NOAR,
            retro_funcionou="a", retro_nao="b", retro_diferente="c")
        self.assertEqual(services.posicao_verba(self._mes())["travada"], Decimal("3000"))
        services.avancar(c, u)  # No ar → Encerrada; sem gastos → devolve tudo
        self.assertEqual(c.fase, Campanha.Fase.ENCERRADA)
        self.assertEqual(services.posicao_verba(self._mes())["travada"], Decimal("0"))

    def test_gerencia_edita_teto(self):
        from django.contrib.auth import get_user_model
        from apps.marketing.models import VerbaMarketing
        U = get_user_model()
        u = U.objects.create_user(username="gestor", password="x123456789")
        u.is_superuser = True
        u.is_staff = True
        u.save()
        self.client.force_login(u)
        r = self.client.post("/crm/marketing/verba/teto/", {"mes": "2026-09", "valor": "18000"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(VerbaMarketing.atual().teto_do_mes("2026-09"), Decimal("18000"))


class PortoesTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        U = get_user_model()
        self.user = U.objects.create_user(username="gestor2", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.hoje = timezone.localdate()
        self.mes = self.hoje.strftime("%Y-%m")

    def _pronta_em_aprovacao(self, verba="1000"):
        """Campanha com o funil satisfeito até parar na fase Aprovação (sem travar verba ainda)."""
        from apps.marketing import services
        c = Campanha.objects.create(
            nome="X", objetivo="obj", publico="pub", canais=["Instagram"],
            inicio=self.hoje, fim=self.hoje, verba_prevista=Decimal(verba),
            responsavel=self.user)
        services.avancar(c, self.user)  # Ideia → Proposta
        services.garantir_itens(c)      # Proposta cobra 3 itens manuais (marcar)
        for chave in ("objetivo_mensuravel", "publico_delimitado", "verba_base"):
            services.marcar_item(c.checks.get(chave=chave), self.user, feito=True)
        services.avancar(c, self.user)  # Proposta → Aprovação
        self.assertEqual(c.fase, Campanha.Fase.APROVACAO)
        return c

    def test_avancar_bloqueia_sem_o_portao_e_nao_grava(self):
        from django.core.exceptions import ValidationError
        from apps.marketing import services
        c = Campanha.objects.create(nome="X", inicio=self.hoje)  # sem objetivo → Ideia trava
        with self.assertRaises(ValidationError):
            services.avancar(c, self.user)
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.IDEIA)

    def test_aprovar_bloqueia_verba_insuficiente(self):
        from django.core.exceptions import ValidationError
        from apps.marketing import services
        services.definir_teto(self.mes, "1000")
        c = self._pronta_em_aprovacao(verba="5000")
        with self.assertRaises(ValidationError):
            services.avancar(c, self.user)  # Aprovação → Estruturação trava a verba
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.APROVACAO)
        self.assertEqual(c.verba_travada, Decimal("0.00"))

    def test_aprovar_trava_verba_e_cria_anuncio(self):
        from apps.marketing import services
        services.definir_teto(self.mes, "10000")
        c = self._pronta_em_aprovacao(verba="4000")
        services.avancar(c, self.user)  # aprova → Estruturação
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.ESTRUTURACAO)
        self.assertEqual(c.verba_travada, Decimal("4000"))
        self.assertIsNotNone(c.anuncio_id)
        self.assertEqual(c.aprovada_por_id, self.user.id)
        self.assertEqual(services.posicao_verba(self.mes)["travada"], Decimal("4000"))

    def test_aprovacao_so_da_gerencia(self):
        from django.contrib.auth import get_user_model
        from django.core.exceptions import ValidationError
        from apps.marketing import services
        services.definir_teto(self.mes, "10000")
        c = self._pronta_em_aprovacao(verba="1000")
        peao = get_user_model().objects.create_user(username="peao", password="x123456789")
        with self.assertRaises(ValidationError):
            services.avancar(c, peao)
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.APROVACAO)

    def test_dispensar_item_obrigatorio_permite_avancar(self):
        from apps.marketing import services
        # Proposta: 3 itens obrigatórios. Marca 2 e dispensa o 3º → libera o avanço.
        c = Campanha.objects.create(nome="Z", fase=Campanha.Fase.PROPOSTA)
        services.garantir_itens(c)
        services.marcar_item(c.checks.get(chave="objetivo_mensuravel"), self.user, feito=True)
        services.marcar_item(c.checks.get(chave="publico_delimitado"), self.user, feito=True)
        services.dispensar_item(c.checks.get(chave="verba_base"), self.user, "não se aplica")
        services.avancar(c, self.user)
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.APROVACAO)

    def test_anexar_arquivo_resolve_item(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.marketing import services
        c = Campanha.objects.create(nome="AF", fase=Campanha.Fase.PROPOSTA)
        services.garantir_itens(c)
        item = c.checks.get(chave="referencia_visual")  # item pede_arquivo (opcional)
        self.assertFalse(services.portao_da(c)["itens"][-1]["resolvido"])
        services.anexar_arquivo(item, SimpleUploadedFile("ref.png", b"x" * 8, content_type="image/png"), self.user)
        item.refresh_from_db()
        self.assertTrue(item.arquivo)
        self.assertTrue(services.portao_da(c)["itens"][-1]["resolvido"])

    def test_encerrar_exige_retrospectiva(self):
        from django.core.exceptions import ValidationError
        from apps.marketing import services
        c = Campanha.objects.create(nome="W", fase=Campanha.Fase.NOAR)
        with self.assertRaises(ValidationError):
            services.avancar(c, self.user)  # No ar → Encerrada exige retrô
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.NOAR)

    def test_arraste_pela_view_respeita_portao(self):
        # move uma fase sem o portão → barra; com o portão → avança
        self.client.force_login(self.user)
        c = Campanha.objects.create(nome="V", inicio=self.hoje)  # sem objetivo
        self.client.post(f"/crm/marketing/campanha/{c.id}/fase/", {"fase": "proposta"})
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.IDEIA)  # portão barrou
        c.objetivo = "agora tem"
        c.save()
        self.client.post(f"/crm/marketing/campanha/{c.id}/fase/", {"fase": "proposta"})
        c.refresh_from_db()
        self.assertEqual(c.fase, Campanha.Fase.PROPOSTA)


class CalendarioTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="cal", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _peca(self, dia):
        from datetime import date
        from apps.marketing.models import PecaCampanha
        # a linha do tempo é por período: a campanha precisa de vigência para aparecer.
        c = Campanha.objects.create(nome="Camp cal",
                                    inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
        return PecaCampanha.objects.create(campanha=c, nome="Post " + str(dia),
                                           canal="Instagram", data=date(2026, 9, dia))

    def test_service_poe_peca_no_dia_certo(self):
        from apps.marketing import services
        self._peca(15)
        grade = services.calendario_mes(2026, 9)
        achou = any(cel["dia"] == 15 and cel["pecas"]
                    for semana in grade for cel in semana)
        self.assertTrue(achou)

    def test_calendario_mes_renderiza_a_peca(self):
        self._peca(15)
        r = self.client.get("/crm/marketing/calendario/?vista=mes&ano=2026&mes=9")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Camp cal")     # linha da campanha na timeline
        self.assertContains(r, "Post 15")       # peça na dica do ponto
        self.assertContains(r, "mkt-dica")      # o balão da dica instantânea

    def test_calendario_ano_renderiza(self):
        self._peca(10)
        r = self.client.get("/crm/marketing/calendario/?vista=ano&ano=2026")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Camp cal")      # a campanha aparece na escala anual
        self.assertContains(r, "2026")          # título da janela

    def test_adicionar_peca(self):
        c = Campanha.objects.create(nome="Camp")
        r = self.client.post(f"/crm/marketing/campanha/{c.id}/peca/",
                             {"nome": "Reel", "canal": "IG", "data": "2026-09-20"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.pecas.count(), 1)
        self.assertEqual(c.pecas.first().nome, "Reel")


class RelatorioTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="rel", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_lancar_gasto_cria_anuncio_e_soma(self):
        from datetime import date
        from apps.marketing import services
        mc = Campanha.objects.create(nome="G", inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
        services.lancar_gasto(mc, date(2026, 9, 10), "1000", self.user)
        mc.refresh_from_db()
        self.assertIsNotNone(mc.anuncio_id)          # anúncio criado (fonte única)
        self.assertEqual(mc.gasta, Decimal("1000"))

    def test_gasto_entra_no_mes_do_dinheiro(self):
        from datetime import date
        from apps.marketing import services
        mc = Campanha.objects.create(nome="H", inicio=date(2026, 9, 1), fim=date(2026, 12, 31))
        services.lancar_gasto(mc, date(2026, 10, 5), "700", self.user)  # dinheiro saiu em outubro
        self.assertEqual(services.relatorio(date(2026, 9, 1), date(2026, 9, 30))["gasto"], Decimal("0.00"))
        self.assertEqual(services.relatorio(date(2026, 10, 1), date(2026, 10, 31))["gasto"], Decimal("700"))

    def test_retorno_rastreado_cac_e_ordem(self):
        from datetime import date
        from apps.marketing import services
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa
        mc = Campanha.objects.create(nome="R", inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
        services.lancar_gasto(mc, date(2026, 9, 10), "1000", self.user)
        etapa = (EtapaFunil.objects.filter(tipo="ganho").first()
                 or EtapaFunil.objects.create(nome="Ganho", ordem=99, probabilidade=100, tipo="ganho"))
        p = Pessoa.objects.create(nome="Cliente")
        for v in (3000, 5000):
            Oportunidade.objects.create(
                pessoa=p, titulo="X", etapa=etapa, campanha=mc.anuncio,
                status=Oportunidade.Status.GANHA, valor_estimado=Decimal(v),
                checkin_previsto=date(2026, 9, 15), criado_por=self.user)
        dados = services.relatorio(date(2026, 9, 1), date(2026, 9, 30))
        linha = [l for l in dados["linhas"] if l["nome"] == "R"][0]
        self.assertEqual(linha["gasto"], Decimal("1000.00"))
        self.assertEqual(linha["rastreada"], Decimal("8000.00"))  # rastreada, não somada à janela
        self.assertEqual(linha["fechamentos"], 2)
        self.assertEqual(linha["cac"], Decimal("500.00"))         # CAC = gasto / fechamentos

    def test_relatorio_renderiza_e_csv(self):
        r = self.client.get("/crm/marketing/relatorio/?mes=9&ano=2026")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "rastreada")
        r2 = self.client.get("/crm/marketing/relatorio/?mes=9&ano=2026&export=csv")
        self.assertEqual(r2["Content-Type"], "text/csv; charset=utf-8")


class VigenciaTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="vig", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()

    def _vigente(self, nome="Vig", canais=None, offset_inicio=1):
        from datetime import timedelta
        from django.utils import timezone
        from apps.marketing import services
        hoje = timezone.localdate()
        c = Campanha.objects.create(
            nome=nome, fase=Campanha.Fase.NOAR,
            inicio=hoje - timedelta(days=offset_inicio), fim=hoje + timedelta(days=10),
            canais=canais or [])
        c.anuncio = services._garantir_anuncio(c, self.user)
        c.save()
        return c

    def test_campanha_vigente_retorna_a_ativa(self):
        from apps.marketing import services
        c = self._vigente()
        self.assertEqual(services.campanha_vigente(), c)

    def test_fase_pre_ativa_nao_e_vigente(self):
        from apps.marketing import services
        Campanha.objects.create(nome="I", fase=Campanha.Fase.PROPOSTA)
        self.assertIsNone(services.campanha_vigente())

    def test_sobreposicao_mais_recente_vence(self):
        from apps.marketing import services
        self._vigente(nome="Antiga", offset_inicio=5)
        nova = self._vigente(nome="Nova", offset_inicio=0)  # começou hoje
        self.assertEqual(services.campanha_vigente(), nova)

    def test_canal_filtra(self):
        from apps.marketing import services
        self._vigente(nome="SoIG", canais=["Instagram"])
        self.assertIsNone(services.campanha_vigente("Google"))
        self.assertIsNotNone(services.campanha_vigente("Instagram"))

    def test_lead_novo_recebe_campanha_vigente(self):
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa
        c = self._vigente()
        etapa = (EtapaFunil.objects.first()
                 or EtapaFunil.objects.create(nome="Novo", ordem=1, probabilidade=10, tipo="aberta"))
        p = Pessoa.objects.create(nome="Lead")
        op = Oportunidade.objects.create(pessoa=p, titulo="T", etapa=etapa, criado_por=self.user)
        op.refresh_from_db()
        self.assertEqual(op.campanha_id, c.anuncio_id)  # atribuído pelo signal

    def test_lead_sem_vigente_fica_organico(self):
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa
        etapa = (EtapaFunil.objects.first()
                 or EtapaFunil.objects.create(nome="Novo", ordem=1, probabilidade=10, tipo="aberta"))
        p = Pessoa.objects.create(nome="Lead")
        op = Oportunidade.objects.create(pessoa=p, titulo="T", etapa=etapa, criado_por=self.user)
        op.refresh_from_db()
        self.assertIsNone(op.campanha_id)  # Orgânico

    def test_lead_com_campanha_nao_e_sobrescrito(self):
        from apps.comercial.models import Campanha as CA, EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa
        self._vigente()
        outra = CA.objects.create(nome="Outra", codigo="outra-x",
                                  provedor=CA.Provedor.OUTRO, criado_por=self.user)
        etapa = (EtapaFunil.objects.first()
                 or EtapaFunil.objects.create(nome="Novo", ordem=1, probabilidade=10, tipo="aberta"))
        p = Pessoa.objects.create(nome="Lead")
        op = Oportunidade.objects.create(pessoa=p, titulo="T", etapa=etapa,
                                         criado_por=self.user, campanha=outra)
        op.refresh_from_db()
        self.assertEqual(op.campanha_id, outra.id)  # não sobrescreve


class AquisicaoTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from datetime import date, timedelta
        from django.utils import timezone
        from apps.marketing import services
        from apps.comercial.models import EtapaFunil, MotivoPerda
        from apps.nucleo.models import Pessoa
        U = get_user_model()
        self.user = U.objects.create_user(username="aq", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        hoje = timezone.localdate()
        self.mc = Campanha.objects.create(nome="AQ", fase=Campanha.Fase.NOAR,
            inicio=hoje - timedelta(days=1), fim=hoje + timedelta(days=10))
        services.lancar_gasto(self.mc, hoje, "1000", self.user)  # cria anúncio + gasto 1000
        self.etapa = (EtapaFunil.objects.first()
                      or EtapaFunil.objects.create(nome="Novo", ordem=1, probabilidade=10, tipo="aberta"))
        self.pessoa = Pessoa.objects.create(nome="Cli")
        self.motivo, _ = MotivoPerda.objects.get_or_create(nome="Preço")

    def _op(self, status, valor=0, motivo=None, reserva_id=None):
        from apps.comercial.models import Oportunidade
        return Oportunidade.objects.create(
            pessoa=self.pessoa, titulo="T", etapa=self.etapa, campanha=self.mc.anuncio,
            status=status, valor_estimado=Decimal(valor), motivo_perda=motivo,
            reserva_id=reserva_id, criado_por=self.user)

    def test_aquisicao_reflete_conversao_e_perda(self):
        from apps.comercial.models import Oportunidade
        from apps.marketing import services
        self._op(Oportunidade.Status.GANHA, 3000, reserva_id=101)
        self._op(Oportunidade.Status.GANHA, 5000, reserva_id=102)
        self._op(Oportunidade.Status.PERDIDA, motivo=self.motivo)
        self._op(Oportunidade.Status.ABERTA, 2000)
        aq = services.aquisicao(self.mc)
        self.assertEqual(aq["total"], 4)
        self.assertEqual(aq["ganhos"], 2)
        self.assertEqual(aq["perdidos"], 1)
        self.assertEqual(aq["abertos"], 1)
        self.assertEqual(aq["receita"], Decimal("8000"))   # rastreada
        self.assertEqual(aq["conversao"], 50)              # 2/4
        self.assertEqual(aq["cac"], Decimal("500.00"))     # 1000/2 fechamentos
        self.assertEqual(aq["motivos"], [{"motivo": "Preço", "n": 1}])

    def test_origem_viaja_na_conversao(self):
        # lead ganho com reserva_id mantém a atribuição à campanha (origem viaja)
        from apps.comercial.models import Oportunidade
        op = self._op(Oportunidade.Status.GANHA, 4000, reserva_id=200)
        self.assertEqual(op.campanha_id, self.mc.anuncio_id)
        self.assertEqual(op.reserva_id, 200)

    def test_detalhe_mostra_aquisicao(self):
        from apps.comercial.models import Oportunidade
        self._op(Oportunidade.Status.GANHA, 3000, reserva_id=1)
        self.client.force_login(self.user)
        r = self.client.get(f"/crm/marketing/campanha/{self.mc.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Aquisição")


class OcupacaoTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        U = get_user_model()
        self.user = U.objects.create_user(username="ocu", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.hoje = timezone.localdate()

    def test_vazio_sem_campanha_e_oportunidade(self):
        from apps.marketing import services
        blocos = services.ocupacao_x_campanha(dias=14)
        self.assertEqual(len(blocos), 2)
        self.assertTrue(all(b["situacao"] == "oportunidade" for b in blocos))
        self.assertTrue(all(not b["tem_campanha"] for b in blocos))

    def test_vazio_com_campanha_e_problema(self):
        from datetime import timedelta
        from apps.marketing import services
        c = Campanha.objects.create(nome="V", fase=Campanha.Fase.NOAR,
            inicio=self.hoje - timedelta(days=1), fim=self.hoje + timedelta(days=30))
        c.anuncio = services._garantir_anuncio(c, self.user)
        c.save()
        blocos = services.ocupacao_x_campanha(dias=14)
        self.assertTrue(all(b["tem_campanha"] for b in blocos))
        self.assertTrue(all(b["situacao"] == "problema" for b in blocos))

    def test_ocupacao_renderiza(self):
        self.client.force_login(self.user)
        r = self.client.get("/crm/marketing/ocupacao/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "anunciar")


class DuplicarTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="dup", password="x123456789")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()

    def test_duplica_resetando_o_que_nao_se_herda(self):
        from datetime import date
        from apps.marketing import services
        from apps.marketing.models import EtapaCampanha, PecaCampanha
        src = Campanha.objects.create(
            nome="Fonte", objetivo="obj", publico="pub", canais=["Instagram"],
            verba_prevista=Decimal("2000"), verba_travada=Decimal("2000"),
            fase=Campanha.Fase.NOAR, inicio=date(2026, 9, 1), fim=date(2026, 9, 30),
            retro_funcionou="x", retro_nao="y", retro_diferente="z")
        src.anuncio = services._garantir_anuncio(src, self.user)
        src.save()
        PecaCampanha.objects.create(campanha=src, nome="Post", canal="IG",
                                    data=date(2026, 9, 10), status=PecaCampanha.Status.PRONTA)
        EtapaCampanha.objects.create(campanha=src, texto="Tarefa", feito=True)

        nova = services.duplicar(src, self.user)
        self.assertNotEqual(nova.pk, src.pk)
        self.assertEqual(nova.nome, "Fonte (cópia)")
        self.assertEqual(nova.fase, Campanha.Fase.IDEIA)
        self.assertEqual(nova.verba_travada, Decimal("0.00"))
        self.assertIsNone(nova.anuncio_id)
        self.assertEqual(nova.retro_funcionou, "")
        self.assertIsNone(nova.inicio)
        self.assertEqual(nova.objetivo, "obj")            # herdado
        self.assertEqual(list(nova.canais), ["Instagram"])
        peca = nova.pecas.get()
        self.assertIsNone(peca.data)
        self.assertEqual(peca.status, PecaCampanha.Status.A_FAZER)
        self.assertFalse(nova.etapas.get().feito)
        # original intacto
        src.refresh_from_db()
        self.assertEqual(src.fase, Campanha.Fase.NOAR)
        self.assertEqual(src.verba_travada, Decimal("2000"))

    def test_view_duplica_redireciona(self):
        self.client.force_login(self.user)
        c = Campanha.objects.create(nome="C")
        r = self.client.post(f"/crm/marketing/campanha/{c.id}/duplicar/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Campanha.objects.filter(nome="C (cópia)").exists())


class FichaGavetaTests(TestCase):
    """A ficha como GAVETA (drawer HTMX) sobre o quadro — divergência 2 da correção."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="drw", password="x123456789",
                                           is_superuser=True, is_staff=True)
        self.client.force_login(self.user)
        self.c = Campanha.objects.create(nome="Gaveta", solicitante=self.user)

    def test_quadro_tem_slot_e_cards_abrem_a_gaveta(self):
        r = self.client.get("/crm/marketing/")
        self.assertContains(r, 'id="ficha-slot"')
        self.assertContains(r, f"/crm/marketing/campanha/{self.c.id}/ficha/")

    def test_ficha_renderiza_a_gaveta(self):
        r = self.client.get(f"/crm/marketing/campanha/{self.c.id}/ficha/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<aside")           # a gaveta lateral
        self.assertContains(r, "ficha-slot")        # fecha esvaziando o slot
        self.assertContains(r, self.c.codigo)

    def test_acao_htmx_rerenderiza_a_gaveta_sem_redirect(self):
        from apps.marketing import services
        services.garantir_itens(self.c)
        r = self.client.post(
            f"/crm/marketing/campanha/{self.c.id}/check/objetivo/",
            HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)        # não redireciona: devolve a gaveta
        self.assertContains(r, "<aside")

    def test_salvar_parcial_nao_zera_outros_campos(self):
        self.c.objetivo = "vender mais"
        self.c.save()
        # posta só a retrospectiva — o objetivo tem que sobreviver
        self.client.post(f"/crm/marketing/campanha/{self.c.id}/salvar/",
                         {"retro_funcionou": "foi bem"}, HTTP_HX_REQUEST="true")
        self.c.refresh_from_db()
        self.assertEqual(self.c.objetivo, "vender mais")
        self.assertEqual(self.c.retro_funcionou, "foi bem")


class FichaCompletaTests(TestCase):
    """Ficha do protótipo #7: canais-pílula, portão por fase, etapas, envolvidos, conversa."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.user = U.objects.create_user(username="ficha", password="x123456789",
                                           first_name="Ana", last_name="Lima",
                                           is_superuser=True, is_staff=True)
        self.client.force_login(self.user)
        self.c = Campanha.objects.create(nome="Réveillon", solicitante=self.user)

    def _url(self, sufixo):
        return f"/crm/marketing/campanha/{self.c.id}/{sufixo}"

    def test_gaveta_traz_as_secoes_do_prototipo(self):
        r = self.client.get(self._url("ficha/"))
        for txt in ("CANAIS", "TRAVADA", "DISPONÍVEL", "Para sair de Ideia",
                    "Etapas desta campanha", "Quem está envolvido", "Conversa"):
            self.assertContains(r, txt)

    def test_canal_pilula_alterna(self):
        self.client.post(self._url("canal/"), {"canal": "Instagram"}, HTTP_HX_REQUEST="true")
        self.c.refresh_from_db()
        self.assertEqual(list(self.c.canais), ["Instagram"])
        self.client.post(self._url("canal/"), {"canal": "Instagram"}, HTTP_HX_REQUEST="true")
        self.c.refresh_from_db()
        self.assertEqual(list(self.c.canais), [])

    def test_atribuir_papel_responsavel(self):
        self.client.post(self._url("papel/"),
                         {"papel": "responsavel", "valor": self.user.id}, HTTP_HX_REQUEST="true")
        self.c.refresh_from_db()
        self.assertEqual(self.c.responsavel_id, self.user.id)

    def test_atribuir_fornecedor_texto(self):
        self.client.post(self._url("papel/"),
                         {"papel": "fornecedor", "valor": "Agência X"}, HTTP_HX_REQUEST="true")
        self.c.refresh_from_db()
        self.assertEqual(self.c.fornecedor, "Agência X")

    def test_etapa_adicionar_alternar_remover(self):
        from apps.marketing.models import EtapaCampanha
        self.client.post(self._url("etapa/"),
                         {"texto": "Levantar preço da concorrência", "dono": self.user.id},
                         HTTP_HX_REQUEST="true")
        e = EtapaCampanha.objects.get(campanha=self.c)
        self.assertFalse(e.feito)
        self.client.post(f"/crm/marketing/etapa/{e.id}/alternar/", HTTP_HX_REQUEST="true")
        e.refresh_from_db()
        self.assertTrue(e.feito)
        self.client.post(f"/crm/marketing/etapa/{e.id}/remover/", HTTP_HX_REQUEST="true")
        self.assertFalse(EtapaCampanha.objects.filter(id=e.id).exists())

    def test_conversa_registra_comentario(self):
        r = self.client.post(self._url("comentar/"),
                             {"texto": "Fechamos o público."}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.conversa.count(), 1)
        self.assertContains(r, "Fechamos o público.")

    def test_avancar_pelo_rodape(self):
        self.c.objetivo = "vender a virada"   # satisfaz o portão da Ideia
        self.c.save()
        r = self.client.post(self._url("avancar/"), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.c.refresh_from_db()
        self.assertEqual(self.c.fase, Campanha.Fase.PROPOSTA)

    def test_portao_ideia_conta_objetivo(self):
        from apps.marketing import services
        port = services.portao_da(self.c)
        self.assertEqual(port["fase_nome"], "Ideia")
        self.assertFalse(port["pode_avancar"])   # objetivo vazio → item obrigatório pendente
        self.c.objetivo = "x"
        self.c.save()
        self.assertTrue(services.portao_da(self.c)["pode_avancar"])


class CincoCorrecoesTests(TestCase):
    """As 5 correções: só-meus (4 vínculos), sem papel, ordem, moeda, canal no atraso."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.gestor = U.objects.create_user(username="ges", password="x123456789",
                                             is_superuser=True, is_staff=True)
        self.outro = U.objects.create_user(username="out", password="x123456789")
        self.client.force_login(self.gestor)

    def test_so_meus_cobre_os_4_vinculos(self):
        from apps.marketing import services
        from apps.marketing.models import EtapaCampanha
        a = Campanha.objects.create(nome="Espera", fase=Campanha.Fase.APROVACAO)  # gestor aprova
        b = Campanha.objects.create(nome="Responde", responsavel=self.gestor)
        c = Campanha.objects.create(nome="Pediu", solicitante=self.gestor)
        d = Campanha.objects.create(nome="Tarefa")
        EtapaCampanha.objects.create(campanha=d, texto="t", dono=self.gestor, feito=False)
        # de outra pessoa (não deve entrar)
        Campanha.objects.create(nome="Alheia", responsavel=self.outro, solicitante=self.outro)
        mot = services.motivos_meus(self.gestor)
        self.assertEqual(set(mot), {a.id, b.id, c.id, d.id})
        total, label = services.meus_resumo(self.gestor)
        self.assertEqual(total, 4)
        self.assertIn("4 campanhas", label)
        self.assertIn("1 a aprovar", label)

    def test_contador_e_filtro_usam_a_mesma_fonte(self):
        # o filtro do quadro usa motivos_meus; o card traz o motivo em âmbar
        from apps.marketing import services
        Campanha.objects.create(nome="Minha", solicitante=self.gestor, fase=Campanha.Fase.IDEIA)
        r = self.client.get("/crm/marketing/?meus=1")
        self.assertContains(r, "você pediu")            # motivo no card
        _, label = services.meus_resumo(self.gestor)
        self.assertContains(r, label)                   # mesmo rótulo no botão

    def test_quadro_sem_seletor_de_papel(self):
        r = self.client.get("/crm/marketing/")
        self.assertNotContains(r, "VOCÊ É")
        self.assertNotContains(r, "Gestor de Marketing")

    def test_coluna_vazia_por_filtro_explica(self):
        Campanha.objects.create(nome="Alheia", responsavel=self.outro,
                                solicitante=self.outro, fase=Campanha.Fase.IDEIA)
        r = self.client.get("/crm/marketing/?meus=1")
        self.assertContains(r, "Nada seu aqui")
        self.assertContains(r, "de outra")

    def test_verba_formatada_em_moeda(self):
        from apps.marketing import services
        services.definir_teto(services.mes_atual(), "18000")
        r = self.client.get("/crm/marketing/")
        self.assertContains(r, "R$ 18.000,00")

    def test_atraso_traz_o_canal(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.marketing import services
        from apps.marketing.models import PecaCampanha
        c = Campanha.objects.create(nome="C")
        PecaCampanha.objects.create(campanha=c, nome="Três estáticos", canal="Meta Ads",
                                    data=timezone.localdate() - timedelta(days=2),
                                    status=PecaCampanha.Status.A_FAZER)
        at = services.banda_atrasados()
        self.assertEqual(at[0]["canal"], "Meta Ads")
        r = self.client.get("/crm/marketing/")
        self.assertContains(r, "Três estáticos · Meta Ads")

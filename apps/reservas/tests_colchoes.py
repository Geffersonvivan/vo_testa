"""Testes do serviço de arranjo de camas + trava global por noite (Fases 2/3 —
estoque de colchões)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.nucleo.models import Hospede, Pessoa
from apps.nucleo.models.cadastros import ConfiguracaoUH, PosicaoCama, TipoUH, UH
from apps.reservas import colchoes, services
from apps.reservas.models import ColchoesExtra, Reserva


def criar_quarto(numero, casais_max, camas_solteiro, sofa):
    tipo, _ = TipoUH.objects.get_or_create(
        nome=f"Tipo {numero}",
        defaults={"capacidade": camas_solteiro, "tarifa_base": Decimal("100.00")},
    )
    uh = UH.objects.create(numero=numero, tipo=tipo)
    for i in range(casais_max):
        PosicaoCama.objects.create(uh=uh, nome=f"Q{i+1}", ordem=i + 1)
    ConfiguracaoUH.objects.create(
        uh=uh, tem_sofa_cama=sofa, sofa_adultos=1, sofa_criancas=2,
        max_colchoes_extras=camas_solteiro - 2 * casais_max,
    )
    return uh


class ArranjoSugestaoTests(TestCase):
    def test_sem_sofa_casal_e_extra(self):
        q = criar_quarto("Q03", casais_max=1, camas_solteiro=3, sofa=False)
        self.assertEqual(colchoes.sugerir_arranjo(q, 2), colchoes.Arranjo(1, 0, False))
        # 3 pessoas, sem sofá → casal + 1 solteiro extra
        a = colchoes.sugerir_arranjo(q, 3)
        self.assertEqual(a, colchoes.Arranjo(1, 1, False))
        self.assertEqual(colchoes.consumo_extra(q, a.casais, a.solteiros), 1)

    def test_sofa_absorve_sem_extra(self):
        q = criar_quarto("Q09", casais_max=1, camas_solteiro=4, sofa=True)
        # 3 adultos: casal + 1 no sofá → 0 extra
        a = colchoes.sugerir_arranjo(q, 3)
        self.assertEqual(a, colchoes.Arranjo(1, 0, True))
        self.assertEqual(colchoes.consumo_extra(q, a.casais, a.solteiros), 0)
        # 2 adultos + 2 crianças: casal + 2 crianças no sofá → 0 extra
        a2 = colchoes.sugerir_arranjo(q, adultos=2, criancas=2)
        self.assertEqual(a2, colchoes.Arranjo(1, 0, True))
        self.assertEqual(colchoes.consumo_extra(q, a2.casais, a2.solteiros), 0)
        # 4 adultos: casal + 1 adulto no sofá + 1 solteiro extra → 1 extra
        a3 = colchoes.sugerir_arranjo(q, 4)
        self.assertEqual(a3, colchoes.Arranjo(1, 1, True))
        self.assertEqual(colchoes.consumo_extra(q, a3.casais, a3.solteiros), 1)

    def test_dois_casais(self):
        q = criar_quarto("Q16", casais_max=2, camas_solteiro=7, sofa=True)
        self.assertEqual(colchoes.sugerir_arranjo(q, 4), colchoes.Arranjo(2, 0, False))
        a = colchoes.sugerir_arranjo(q, 7)  # 2 casais + sofá + 2 solteiros
        self.assertEqual(a, colchoes.Arranjo(2, 2, True))
        self.assertEqual(colchoes.consumo_extra(q, a.casais, a.solteiros), 2)


class CabeNoQuartoTests(TestCase):
    def test_estrutura(self):
        q = criar_quarto("Q03", casais_max=1, camas_solteiro=3, sofa=False)
        self.assertEqual(colchoes.cabe_no_quarto(q, 1, 1, False, 3, 0), [])  # 3 camas ok
        self.assertTrue(colchoes.cabe_no_quarto(q, 2, 0, False, 4, 0))       # 2 casais > max
        self.assertTrue(colchoes.cabe_no_quarto(q, 1, 2, False, 4, 0))       # 4 camas > 3
        self.assertTrue(colchoes.cabe_no_quarto(q, 1, 0, True, 2, 0))        # sem sofá
        # hóspedes demais p/ as camas
        self.assertTrue(colchoes.cabe_no_quarto(q, 1, 0, False, 3, 0))       # 3 pessoas, 2 camas


class PresetsTests(TestCase):
    def test_presets(self):
        q = criar_quarto("Q03", casais_max=1, camas_solteiro=3, sofa=False)
        ps = colchoes.presets(q)
        rotulos = [p["rotulo"] for p in ps]
        self.assertIn("Base (só casais)", rotulos)
        self.assertIn("Só solteiros", rotulos)
        base = next(p for p in ps if p["rotulo"].startswith("Base"))
        self.assertEqual((base["casais"], base["solteiros"], base["colchoes_extra"]), (1, 0, 0))
        so_solt = next(p for p in ps if p["rotulo"] == "Só solteiros")
        self.assertEqual((so_solt["casais"], so_solt["solteiros"], so_solt["colchoes_extra"]), (0, 3, 1))


class TravaGlobalPorNoiteTests(TestCase):
    """Fase 3 — trava global do pool de colchões extra por noite (conferir_arranjo +
    criar_prereserva)."""

    def setUp(self):
        self.hoje = timezone.localdate()
        self.amanha = self.hoje + timedelta(days=1)
        # Dois quartos iguais: casais_max=1, 3 camas de solteiro → 1 colchão extra cada.
        self.qa = criar_quarto("A01", casais_max=1, camas_solteiro=3, sofa=False)
        self.qb = criar_quarto("A02", casais_max=1, camas_solteiro=3, sofa=False)
        ColchoesExtra.objects.create(quantidade=1, alerta_minimo=0)  # pool = 1 extra
        pessoa = Pessoa.objects.create(nome="Hóspede Teste")
        Hospede.objects.create(pessoa=pessoa)
        self.hospede = pessoa
        self.user = get_user_model().objects.create_user(
            username="op", password="x", email="op@teste.com")

    def _conf(self, uh, casais, solteiros, ci=None, co=None, excluir=None):
        return services.conferir_arranjo(
            uh, casais=casais, solteiros=solteiros, usa_sofa_cama=False,
            adultos=casais * 2 + solteiros, criancas=0,
            checkin=ci or self.hoje, checkout=co or self.amanha, excluir_id=excluir)

    def _reservar(self, uh, casais, solteiros, ci=None, co=None):
        return services.criar_prereserva(
            uh=uh, checkin=ci or self.hoje, checkout=co or self.amanha,
            hospede=self.hospede, usuario=self.user, valor_diaria=Decimal("100.00"),
            casais=casais, solteiros=solteiros, adultos=casais * 2 + solteiros)

    def test_base_casal_nunca_bloqueia(self):
        # Mesmo com pool zerado, o arranjo base (1 casal) não usa extra → sempre passa.
        ColchoesExtra.objects.update(quantidade=0)
        conf = self._conf(self.qa, casais=1, solteiros=0)
        self.assertEqual(conf["extra"], 0)
        self.assertEqual(conf["erros"], [])

    def test_reserva_nao_reembolsavel_desconta_a_diaria(self):
        from apps.reservas import precos
        r = services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha,
            hospede=self.hospede, usuario=self.user,
            casais=1, solteiros=0, adultos=2, nao_reembolsavel=True)
        self.assertTrue(r.nao_reembolsavel)
        cot_nr = precos.cotacao(uh=self.qa, checkin=self.hoje, checkout=self.amanha,
                                adultos=2, nao_reembolsavel=True)
        cot_full = precos.cotacao(uh=self.qa, checkin=self.hoje, checkout=self.amanha,
                                  adultos=2)
        self.assertEqual(r.valor_diaria, cot_nr["media_noite"])
        self.assertLess(cot_nr["media_noite"], cot_full["media_noite"])

    def test_estrutura_excede_casais(self):
        conf = self._conf(self.qa, casais=2, solteiros=0)
        self.assertTrue(any("casais" in e for e in conf["erros"]))

    def test_pool_bloqueia_segunda_reserva_na_mesma_noite(self):
        self._reservar(self.qa, casais=1, solteiros=1)   # usa o único extra
        conf = self._conf(self.qb, casais=1, solteiros=1)
        self.assertTrue(conf["erros"])
        self.assertIn("Sem colchão extra", conf["erros"][0])
        with self.assertRaises(ValidationError):
            self._reservar(self.qb, casais=1, solteiros=1)

    def test_apenas_a_noite_sem_colchao_e_apontada(self):
        meio = self.hoje + timedelta(days=1)
        fim = self.hoje + timedelta(days=3)
        # Ocupa o extra só na 2ª noite [meio, meio+1).
        self._reservar(self.qa, casais=1, solteiros=1, ci=meio, co=meio + timedelta(days=1))
        conf = self._conf(self.qb, casais=1, solteiros=1, ci=self.hoje, co=fim)
        self.assertTrue(conf["erros"])
        self.assertIn(f"{meio:%d/%m}", conf["erros"][0])
        self.assertNotIn(f"{self.hoje:%d/%m}", conf["erros"][0])

    def test_cancelada_libera_o_extra(self):
        r = self._reservar(self.qa, casais=1, solteiros=1)
        r.status = Reserva.Status.CANCELADA
        r.save(update_fields=["status"])
        conf = self._conf(self.qb, casais=1, solteiros=1)
        self.assertEqual(conf["erros"], [])

    def test_edicao_nao_conta_o_proprio_consumo_em_dobro(self):
        r = self._reservar(self.qa, casais=1, solteiros=1)
        # Revalidar a própria reserva, excluindo-a da soma, continua válido.
        conf = self._conf(self.qa, casais=1, solteiros=1, excluir=r.pk)
        self.assertEqual(conf["erros"], [])

    def test_aviso_quando_resta_pouco(self):
        ColchoesExtra.objects.update(quantidade=1, alerta_minimo=1)
        conf = self._conf(self.qa, casais=1, solteiros=1)  # consome o último extra
        self.assertEqual(conf["erros"], [])
        self.assertTrue(conf["avisos"])
        self.assertIn("resta", conf["avisos"][0].lower())

    def test_prereserva_persiste_arranjo(self):
        r = self._reservar(self.qa, casais=1, solteiros=1)
        self.assertEqual((r.casais, r.solteiros), (1, 1))
        self.assertEqual(r.colchoes_extra, 1)

    def test_confirmar_orcamento_revalida_pool(self):
        # Orçamento no qb pede 1 extra; depois o qa consome o único extra do pool →
        # confirmar o orçamento revalida e bloqueia (orçamento não reservava o pool).
        orc = Reserva.objects.create(
            uh=self.qb, hospede=self.hospede, checkin=self.hoje, checkout=self.amanha,
            status=Reserva.Status.ORCAMENTO, valor_diaria=Decimal("100.00"),
            casais=1, solteiros=1, adultos=3, criado_por=self.user)
        self._reservar(self.qa, casais=1, solteiros=1)  # consome o extra (pool=1)
        with self.assertRaises(ValidationError):
            orc.confirmar(self.user)

    def test_pool_editavel_libera_todas_as_vagas(self):
        ColchoesExtra.objects.update(quantidade=2)
        self._reservar(self.qa, casais=1, solteiros=1)
        conf = self._conf(self.qb, casais=1, solteiros=1)
        self.assertEqual(conf["erros"], [])

    def test_site_unidade_respeita_arranjo_escolhido(self):
        # UI de arranjos: o hóspede escolhe "só solteiros"; a reserva do site grava assim.
        opcoes = services.arranjos_disponiveis(self.qa)
        self.assertTrue(any(o["rotulo"] == "Só solteiros" for o in opcoes))
        r = services.criar_reserva_site_unidade(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, adultos=2, casais=0, solteiros=2)
        self.assertEqual((r.casais, r.solteiros), (0, 2))


class DisponibilidadeComPoolTests(TestCase):
    """Fase 4 — disponibilidade (uh_disponivel/uhs_disponiveis/tipo_disponivel) olha o
    pool de colchões extra por noite quando a lotação é informada."""

    def setUp(self):
        self.hoje = timezone.localdate()
        self.amanha = self.hoje + timedelta(days=1)
        self.qa = criar_quarto("D01", casais_max=1, camas_solteiro=3, sofa=False)
        self.qb = criar_quarto("D02", casais_max=1, camas_solteiro=3, sofa=False)
        ColchoesExtra.objects.create(quantidade=1, alerta_minimo=0)
        pessoa = Pessoa.objects.create(nome="Hóspede D")
        Hospede.objects.create(pessoa=pessoa)
        self.hospede = pessoa
        self.user = get_user_model().objects.create_user(
            username="opd", password="x", email="opd@teste.com")
        # Ocupa o único colchão extra no quarto A (1 casal + 1 solteiro).
        services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), casais=1, solteiros=1,
            adultos=3)

    def test_sem_lotacao_mantem_disponibilidade_base(self):
        # Sem adultos, ignora o pool: o quarto B segue "disponível" (base garantida).
        self.assertTrue(services.uh_disponivel(self.qb, self.hoje, self.amanha))

    def test_base_sempre_disponivel_mesmo_pool_zerado(self):
        # 2 pessoas no B → arranjo base (1 casal), não usa extra → disponível.
        self.assertTrue(services.uh_disponivel(
            self.qb, self.hoje, self.amanha, adultos=2))

    def test_lotacao_sem_colchao_fica_indisponivel(self):
        # 3 pessoas no B exigem 1 extra, mas o pool está esgotado → indisponível.
        self.assertFalse(services.uh_disponivel(
            self.qb, self.hoje, self.amanha, adultos=3))

    def test_uhs_disponiveis_filtra_por_pool(self):
        ids_base = set(services.uhs_disponiveis(
            self.hoje, self.amanha).values_list("pk", flat=True))
        self.assertIn(self.qb.pk, ids_base)  # B livre na base
        ids_3 = set(services.uhs_disponiveis(
            self.hoje, self.amanha, adultos=3).values_list("pk", flat=True))
        self.assertNotIn(self.qb.pk, ids_3)  # mas sem colchão p/ 3 pessoas
        ids_2 = set(services.uhs_disponiveis(
            self.hoje, self.amanha, adultos=2).values_list("pk", flat=True))
        self.assertIn(self.qb.pk, ids_2)  # cabe p/ 2 (base)

    def test_pool_reabastecido_volta_a_oferecer(self):
        ColchoesExtra.objects.update(quantidade=2)
        self.assertTrue(services.uh_disponivel(
            self.qb, self.hoje, self.amanha, adultos=3))

    def test_pool_negativo_nao_esconde_quarto_de_base(self):
        # qa já usa 1 extra; com pool 0 o saldo da noite fica negativo (−1). Um quarto
        # em base (2 pessoas, 0 extra) tem de continuar disponível.
        ColchoesExtra.objects.update(quantidade=0)
        ids_base = set(services.uhs_disponiveis(
            self.hoje, self.amanha, adultos=2).values_list("pk", flat=True))
        self.assertIn(self.qb.pk, ids_base)


class PaineisColchoesTests(TestCase):
    """Fase 5 — painéis: painel por noite, alertas do dashboard, montagem do dia."""

    def setUp(self):
        self.hoje = timezone.localdate()
        self.amanha = self.hoje + timedelta(days=1)
        self.qa = criar_quarto("P01", casais_max=1, camas_solteiro=3, sofa=False)
        ColchoesExtra.objects.create(quantidade=1, alerta_minimo=0)
        pessoa = Pessoa.objects.create(nome="Hóspede P")
        Hospede.objects.create(pessoa=pessoa)
        self.hospede = pessoa
        self.user = get_user_model().objects.create_user(
            username="opp", password="x", email="opp@teste.com")
        self.reserva = services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), casais=1, solteiros=1,
            adultos=3)

    def test_painel_por_noite(self):
        painel = services.painel_colchoes(self.hoje, self.hoje)
        self.assertEqual(painel["pool"], 1)
        self.assertEqual(len(painel["linhas"]), 1)
        linha = painel["linhas"][0]
        self.assertEqual((linha["usados"], linha["livres"]), (1, 0))
        self.assertEqual(linha["status"], "esgotado")

    def test_alertas_proximos_detecta_esgotado(self):
        alerta = services.colchoes_alertas_proximos(dias=2)
        self.assertIsNotNone(alerta)
        self.assertEqual(len(alerta["esgotadas"]), 1)

    def test_alertas_proximos_none_quando_folgado(self):
        ColchoesExtra.objects.update(quantidade=10, alerta_minimo=1)
        self.assertIsNone(services.colchoes_alertas_proximos(dias=7))

    def test_montagem_do_dia(self):
        linhas = services.montagem_do_dia(self.hoje)
        self.assertEqual(len(linhas), 1)
        m = linhas[0]
        self.assertEqual((m["uh"], m["casais"], m["solteiros"], m["extra"]), ("P01", 1, 1, 1))

    def test_montagem_ignora_dia_sem_chegada(self):
        self.assertEqual(services.montagem_do_dia(self.hoje + timedelta(days=5)), [])

    def test_view_painel_colchoes_abre(self):
        gerente = get_user_model().objects.create_user(
            username="ger", password="x", email="ger@teste.com",
            is_staff=True, is_superuser=True)
        self.client.force_login(gerente)
        resp = self.client.get("/crm/reservas/colchoes/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Colchões extra por noite")


class AceiteColchoesTests(TestCase):
    """Fase 7 — testes de aceite §9 da pousada inteira (seed real dos 24 quartos)."""

    def setUp(self):
        from django.core.management import call_command
        self.tipo = TipoUH.objects.create(nome="Padrão", tarifa_base=Decimal("100.00"))
        for n in range(1, 25):
            UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo)
        call_command("configurar_camas", verbosity=0)
        # Só os 24 quartos (o banco de teste já traz DAY-01..08 por migração).
        self.quartos = UH.objects.filter(numero__startswith="Quarto ")
        pessoa = Pessoa.objects.create(nome="Hóspede Aceite")
        Hospede.objects.create(pessoa=pessoa)
        self.hospede = pessoa
        self.user = get_user_model().objects.create_user(
            username="opa", password="x", email="opa@teste.com")
        self.hoje = timezone.localdate()
        self.amanha = self.hoje + timedelta(days=1)

    def _reservar(self, uh, casais, solteiros, adultos=None):
        return services.criar_prereserva(
            uh=uh, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), casais=casais,
            solteiros=solteiros, adultos=adultos or (2 * casais + solteiros))

    def test_1_seed_totais(self):
        # 24 quartos, 112 camas de solteiro, 35 casais, base 70, 42 vagas extras, 13 sofás, pool 10.
        self.assertEqual(self.quartos.count(), 24)
        cfgs = ConfiguracaoUH.objects.filter(uh__numero__startswith="Quarto ")
        casais = sum(c.uh.posicoes_cama.count() for c in cfgs)
        self.assertEqual(casais, 35)
        self.assertEqual(2 * casais, 70)                                 # base garantida
        self.assertEqual(sum(c.max_colchoes_extras for c in cfgs), 42)   # vagas extras
        self.assertEqual(sum(2 * c.uh.posicoes_cama.count() + c.max_colchoes_extras
                             for c in cfgs), 112)                        # camas de solteiro
        self.assertEqual(cfgs.filter(tem_sofa_cama=True).count(), 13)
        self.assertEqual(ColchoesExtra.atual().quantidade, 10)

    def test_2_todos_em_base_zero_extra(self):
        # 24 quartos em config base (só casais) na mesma noite → 0 extras usados.
        for uh in self.quartos:
            self._reservar(uh, casais=uh.posicoes_cama.count(), solteiros=0)
        usados = services.colchoes_extra_por_noite(self.hoje, self.amanha)
        self.assertEqual(usados[self.hoje], 0)
        self.assertEqual(Reserva.objects.filter(uh__numero__startswith="Quarto ").count(), 24)

    def test_3_dez_extras_ok_decimo_primeiro_recusado(self):
        # 10 solteiros extras distribuídos em quartos com vaga → ok (extras=10). 11º → recusado.
        com_vaga = [uh for uh in self.quartos.order_by("numero")
                    if uh.config.max_colchoes_extras >= 1]
        self.assertGreaterEqual(len(com_vaga), 11)
        for uh in com_vaga[:10]:
            self._reservar(uh, casais=uh.posicoes_cama.count(), solteiros=1)  # +1 extra cada
        livres = services.colchoes_extra_livres(self.hoje, self.amanha)
        self.assertEqual(livres[self.hoje], 0)  # pool esgotado
        with self.assertRaises(ValidationError):
            self._reservar(com_vaga[10], casais=com_vaga[10].posicoes_cama.count(), solteiros=1)

    def test_7_quarto_22_cheio_com_sofa(self):
        # Quarto 22 (2 casais, 7 camas, sofá): 2 casais + 3 solteiros + sofá 2 crianças (10) →
        # 9 hóspedes, 3 extras. Com 3 livres no pool → aceito.
        ColchoesExtra.objects.update(quantidade=3)
        q22 = UH.objects.get(numero="Quarto 22")
        conf = services.conferir_arranjo(
            q22, casais=2, solteiros=3, usa_sofa_cama=True, adultos=7, criancas=2,
            checkin=self.hoje, checkout=self.amanha)
        self.assertEqual(conf["extra"], 3)
        self.assertEqual(conf["erros"], [])
        r = services.criar_prereserva(
            uh=q22, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"),
            casais=2, solteiros=3, usa_sofa_cama=True, adultos=7,
            criancas_6_15=2)
        self.assertEqual(r.colchoes_extra, 3)


class BercoRecursoTests(TestCase):
    """Berço como recurso global (grátis), trava por noite."""

    def setUp(self):
        self.hoje = timezone.localdate()
        self.amanha = self.hoje + timedelta(days=1)
        self.qa = criar_quarto("B01", casais_max=1, camas_solteiro=3, sofa=False)
        self.qb = criar_quarto("B02", casais_max=1, camas_solteiro=3, sofa=False)
        from apps.reservas.models import BercoEstoque
        BercoEstoque.objects.create(quantidade=1)
        pessoa = Pessoa.objects.create(nome="Hóspede B")
        Hospede.objects.create(pessoa=pessoa)
        self.hospede = pessoa
        self.user = get_user_model().objects.create_user(
            username="opb", password="x", email="opb@teste.com")

    def test_berco_disponivel_e_bloqueio(self):
        self.assertTrue(services.berco_disponivel(self.hoje, self.amanha))
        # Reserva pega o único berço na noite.
        services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), usa_berco=True)
        self.assertFalse(services.berco_disponivel(self.hoje, self.amanha))
        # Outra reserva na mesma noite não consegue berço.
        with self.assertRaises(ValidationError):
            services.criar_prereserva(
                uh=self.qb, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
                usuario=self.user, valor_diaria=Decimal("100.00"), usa_berco=True)

    def test_berco_cancelado_libera(self):
        r = services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), usa_berco=True)
        r.status = Reserva.Status.CANCELADA
        r.save(update_fields=["status"])
        self.assertTrue(services.berco_disponivel(self.hoje, self.amanha))

    def test_estoque_editavel_libera_dois(self):
        from apps.reservas.models import BercoEstoque
        BercoEstoque.objects.update(quantidade=2)
        services.criar_prereserva(
            uh=self.qa, checkin=self.hoje, checkout=self.amanha, hospede=self.hospede,
            usuario=self.user, valor_diaria=Decimal("100.00"), usa_berco=True)
        self.assertTrue(services.berco_disponivel(self.hoje, self.amanha))

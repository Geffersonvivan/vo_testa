from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import Funcionario, ModuloContratado, Pessoa
from apps.nucleo.modulos import Modulo

from . import services
from .models import Atribuicao, TrocaTurno, Turno

Usuario = get_user_model()


class EscalaBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="chefe", password="senha-forte-123")
        self.turno = Turno.objects.create(nome="Manhã", setor="recepcao",
                                          inicio=time(7, 0), fim=time(15, 0))
        self.f1 = self._func("Ana")
        self.f2 = self._func("Bruno")
        self.hoje = timezone.localdate()

    def _func(self, nome):
        p = Pessoa.objects.create(nome=nome)
        return Funcionario.objects.create(pessoa=p, cargo="Recepção")


class AtribuicaoTests(EscalaBase):
    def test_atribuir_e_unicidade(self):
        services.atribuir(self.turno, self.f1, self.hoje, self.op)
        self.assertEqual(Atribuicao.objects.count(), 1)
        with self.assertRaises(ValidationError):
            services.atribuir(self.turno, self.f1, self.hoje, self.op)  # duplicado

    def test_nao_escala_ausente(self):
        services.registrar_ausencia(self.f1, "folga", self.hoje, self.hoje, self.op)
        with self.assertRaises(ValidationError):
            services.atribuir(self.turno, self.f1, self.hoje, self.op)

    def test_grade_organiza_por_turno_e_dia(self):
        services.atribuir(self.turno, self.f1, self.hoje, self.op)
        inicio = services.inicio_da_semana(self.hoje)
        grade = services.grade_semana(inicio)
        self.assertEqual(len(grade["dias"]), 7)
        linha = grade["linhas"][0]
        nomes = [a.funcionario.pessoa.nome for c in linha["celulas"] for a in c["atribs"]]
        self.assertIn("Ana", nomes)


class TrocaTests(EscalaBase):
    def test_troca_aprovada_reatribui(self):
        atrib = services.atribuir(self.turno, self.f1, self.hoje, self.op)
        troca = services.solicitar_troca(atrib, self.f2, "consulta")
        services.decidir_troca(troca, self.op, aprovar=True)
        atrib.refresh_from_db()
        self.assertEqual(atrib.funcionario, self.f2)
        self.assertEqual(troca.status, TrocaTurno.Status.APROVADA)

    def test_troca_recusada_mantem(self):
        atrib = services.atribuir(self.turno, self.f1, self.hoje, self.op)
        troca = services.solicitar_troca(atrib, self.f2)
        services.decidir_troca(troca, self.op, aprovar=False)
        atrib.refresh_from_db()
        self.assertEqual(atrib.funcionario, self.f1)

    def test_nao_troca_para_ausente(self):
        atrib = services.atribuir(self.turno, self.f1, self.hoje, self.op)
        services.registrar_ausencia(self.f2, "ferias", self.hoje, self.hoje, self.op)
        with self.assertRaises(ValidationError):
            services.solicitar_troca(atrib, self.f2)


class MinhaEscalaTests(EscalaBase):
    def test_minha_escala_filtra_pelo_usuario(self):
        self.f1.usuario = self.op
        self.f1.save()
        services.atribuir(self.turno, self.f1, self.hoje, self.op)
        services.atribuir(self.turno, self.f2, self.hoje, self.op)
        minha = services.minha_escala(self.op, self.hoje, self.hoje + timedelta(days=7))
        self.assertEqual(len(minha), 1)
        self.assertEqual(minha[0].funcionario, self.f1)


class PermissaoTests(EscalaBase):
    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.ESCALA).update(ativo=False)
        self.client.login(username="chefe", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("escala:grade")).status_code, 404)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("escala:grade")).status_code, 403)


class ResumoFuncionarioTests(EscalaBase):
    """resumo_funcionario: dias/horas trabalhados + ausências (usado no Histórico)."""

    def test_dias_horas_e_ausencias(self):
        services.atribuir(self.turno, self.f1, self.hoje, self.op)
        services.atribuir(self.turno, self.f1, self.hoje - timedelta(days=1), self.op)
        services.registrar_ausencia(
            self.f1, "folga", self.hoje - timedelta(days=3), self.hoje - timedelta(days=2), self.op
        )
        r = services.resumo_funcionario(self.f1, self.hoje - timedelta(days=30), self.hoje)
        self.assertEqual(r["dias_trabalhados"], 2)
        self.assertEqual(r["horas_trabalhadas"], 16.0)  # turno 07–15h = 8h × 2 dias
        self.assertEqual(r["dias_ausente"], 2)


class GeradorTests(TestCase):
    """Motor de escala: cobertura, interjornada 11h, DSR, domingo por sexo."""

    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="gestor", password="senha-forte-123")
        self.manha = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0), min_pessoas=1)
        self.tarde = Turno.objects.create(nome="Tarde", setor="recepcao",
                                           inicio=time(14, 30), fim=time(22, 0), min_pessoas=1)
        self.funcs = []
        for nome, sx in [("Ana", "F"), ("Bruno", "M"), ("Carla", "F")]:
            p = Pessoa.objects.create(nome=nome)
            self.funcs.append(Funcionario.objects.create(
                pessoa=p, cargo="Recepção", setor="Recepção", sexo=sx))
        self.inicio = services.inicio_da_semana()
        self.dias = [self.inicio + timedelta(days=n) for n in range(7)]

    def test_gera_cobertura_completa(self):
        services.gerar_semana(self.inicio, self.op)
        for t in (self.manha, self.tarde):
            for d in self.dias:
                tem = Atribuicao.objects.filter(turno=t, data=d).count()
                self.assertGreaterEqual(tem, t.min_pessoas, f"{t.nome} {d} descoberto")

    def test_nunca_tarde_seguido_de_manha(self):
        services.gerar_semana(self.inicio, self.op)
        for f in self.funcs:
            por_data = {a.data: a.turno_id for a in Atribuicao.objects.filter(funcionario=f)}
            for d in self.dias[:-1]:
                if por_data.get(d) == self.tarde.pk:
                    self.assertNotEqual(por_data.get(d + timedelta(days=1)), self.manha.pk,
                                        f"{f.pessoa.nome}: tarde→manhã viola interjornada")

    def test_todos_tem_folga_na_semana(self):
        services.gerar_semana(self.inicio, self.op)
        for f in self.funcs:
            dias_trab = Atribuicao.objects.filter(funcionario=f).values("data").distinct().count()
            self.assertLessEqual(dias_trab, 6, f"{f.pessoa.nome} sem folga (DSR)")

    def test_folga_domingo_por_sexo(self):
        # ♀ folga 2 de 4 domingos; ♂ folga 1 de 4 — em qualquer ciclo.
        mulher, homem = self.funcs[0], self.funcs[1]
        f_count = sum(services.folga_domingo(mulher, i) for i in range(4))
        m_count = sum(services.folga_domingo(homem, i) for i in range(4))
        self.assertEqual(f_count, 2)
        self.assertEqual(m_count, 1)

    def test_respeita_ausencia_na_geracao(self):
        services.registrar_ausencia(self.funcs[0], "ferias", self.dias[0], self.dias[6], self.op)
        services.gerar_semana(self.inicio, self.op)
        self.assertFalse(Atribuicao.objects.filter(funcionario=self.funcs[0]).exists())

    def test_validacao_acusa_cobertura_faltando(self):
        # 1 só funcionário para 2 turnos/dia → algum dia fica descoberto.
        Funcionario.objects.exclude(pk=self.funcs[0].pk).delete()
        services.gerar_semana(self.inicio, self.op)
        alertas = services.validar_semana(self.inicio)
        self.assertTrue(any(a["nivel"] == "perigo" for a in alertas))


class RemoverAtribuicaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="ch2", password="senha-forte-123")
        self.t = Turno.objects.create(nome="Manhã", setor="recepcao",
                                      inicio=time(7, 0), fim=time(15, 0))
        p = Pessoa.objects.create(nome="Zé")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção")
        self.hoje = timezone.localdate()
        self.a = services.atribuir(self.t, self.f, self.hoje, self.op)
        self.client.force_login(self.op)

    def test_remover_com_voltar_query_redireciona(self):
        # regressão: "voltar" = "?inicio=…" não pode virar NoReverseMatch
        resp = self.client.post(
            reverse("escala:remover_atribuicao", args=[self.a.pk]),
            {"voltar": "?inicio=2026-08-31"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/crm/escala/", resp.url)
        self.assertIn("inicio=2026-08-31", resp.url)
        self.assertFalse(Atribuicao.objects.filter(pk=self.a.pk).exists())


class EditorArrastoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="ed", password="senha-forte-123")
        self.manha = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0), min_pessoas=1)
        self.tarde = Turno.objects.create(nome="Tarde", setor="recepcao",
                                           inicio=time(14, 30), fim=time(22, 0), min_pessoas=1)
        p = Pessoa.objects.create(nome="Ana")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção", setor="Recepção", sexo="F")
        self.inicio = services.inicio_da_semana()
        self.client.force_login(self.op)

    def _post(self, **kw):
        kw.setdefault("inicio", self.inicio.strftime("%Y-%m-%d"))
        return self.client.post(reverse("escala:editar"), kw)

    def test_add_por_arrasto(self):
        r = self._post(acao="add", funcionario=self.f.pk, turno=self.manha.pk,
                       data=self.inicio.strftime("%Y-%m-%d"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Atribuicao.objects.filter(funcionario=self.f, turno=self.manha).exists())

    def test_mover_entre_turnos(self):
        a = services.atribuir(self.manha, self.f, self.inicio, self.op)
        r = self._post(acao="mover", atribuicao=a.pk, turno=self.tarde.pk,
                       data=self.inicio.strftime("%Y-%m-%d"))
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.turno, self.tarde)

    def test_remover_por_arrasto(self):
        a = services.atribuir(self.manha, self.f, self.inicio, self.op)
        r = self._post(acao="remover", atribuicao=a.pk)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Atribuicao.objects.filter(pk=a.pk).exists())

    def test_add_em_ausente_retorna_erro_json(self):
        services.registrar_ausencia(self.f, "ferias", self.inicio, self.inicio, self.op)
        r = self._post(acao="add", funcionario=self.f.pk, turno=self.manha.pk,
                       data=self.inicio.strftime("%Y-%m-%d"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("erro", r.json())

    def test_mover_para_ausente_bloqueia(self):
        a = services.atribuir(self.manha, self.f, self.inicio, self.op)
        d1 = self.inicio + timedelta(days=1)
        services.registrar_ausencia(self.f, "atestado", d1, d1, self.op)
        with self.assertRaises(ValidationError):
            services.mover(a, self.tarde, d1, self.op)


class RegrasAvancadasTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="rg", password="senha-forte-123")
        self.manha = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0), min_pessoas=1)
        self.tarde = Turno.objects.create(nome="Tarde", setor="recepcao",
                                           inicio=time(14, 30), fim=time(22, 0), min_pessoas=1)
        p = Pessoa.objects.create(nome="Ana")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção", setor="Recepção", sexo="F")
        self.inicio = services.inicio_da_semana()
        self.d0 = self.inicio
        self.d1 = self.inicio + timedelta(days=1)

    def test_conflito_interjornada_detecta(self):
        services.atribuir(self.tarde, self.f, self.d0, self.op)   # 14:30–22:00
        self.assertTrue(services.conflito_interjornada(self.f, self.manha, self.d1))  # 07:00 = 9h

    def test_analise_marca_violacao_no_chip(self):
        services.atribuir(self.tarde, self.f, self.d0, self.op)
        a_manha = services.atribuir(self.manha, self.f, self.d1, self.op)
        analise = services.analisar_semana(self.inicio)
        self.assertIn(a_manha.pk, analise["violacoes"])
        self.assertIn("interjornada <11h", analise["bloqueios"])

    def test_publicar_barra_com_violacao_e_libera_com_justificativa(self):
        services.atribuir(self.tarde, self.f, self.d0, self.op)
        services.atribuir(self.manha, self.f, self.d1, self.op)   # interjornada
        with self.assertRaises(ValidationError):
            services.publicar_semana(self.inicio, None, self.op)  # sem justificativa
        pub = services.publicar_semana(self.inicio, None, self.op, "ciente, emergência")
        self.assertTrue(pub.forcado)

    def test_publicar_semana_limpa(self):
        self.tarde.ativo = False       # só a Manhã (mín 1) nesta semana
        self.tarde.save()
        p2 = Pessoa.objects.create(nome="Bia")
        f2 = Funcionario.objects.create(pessoa=p2, cargo="Recepção", setor="Recepção", sexo="F")
        for i in range(6):             # f cobre seg–sáb, f2 cobre domingo → 7/7
            services.atribuir(self.manha, self.f, self.inicio + timedelta(days=i), self.op)
        services.atribuir(self.manha, f2, self.inicio + timedelta(days=6), self.op)
        pub = services.publicar_semana(self.inicio, None, self.op)
        self.assertFalse(pub.forcado)

    def test_editar_pede_confirmacao_e_forca(self):
        self.client.force_login(self.op)
        services.atribuir(self.tarde, self.f, self.d0, self.op)
        base = {"inicio": self.inicio.strftime("%Y-%m-%d"), "acao": "add",
                "funcionario": self.f.pk, "turno": self.manha.pk,
                "data": self.d1.strftime("%Y-%m-%d")}
        r = self.client.post(reverse("escala:editar"), base)
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirmar", r.json())
        r2 = self.client.post(reverse("escala:editar"), {**base, "forcar": "1"})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(Atribuicao.objects.filter(funcionario=self.f, turno=self.manha, data=self.d1).exists())


class PrepararEscalaSeedTests(TestCase):
    def test_setor_do_cargo_e_sexo_do_nome(self):
        from apps.escala.management.commands.preparar_escala import setor_do_cargo, sexo_do_nome
        self.assertEqual(setor_do_cargo("Recepcionista"), "Recepção")
        self.assertEqual(setor_do_cargo("Camareira"), "Governança")
        self.assertEqual(setor_do_cargo("Cozinheiro"), "Cozinha/Restaurante")
        self.assertEqual(setor_do_cargo("Piloto"), "")            # não reconhecido
        self.assertEqual(sexo_do_nome("Marta Kuhn")[0], "F")      # termina em a
        self.assertEqual(sexo_do_nome("Pedro Boff")[0], "M")
        self.assertEqual(sexo_do_nome("Ivone Santos")[0], "F")    # exceção
        self.assertTrue(sexo_do_nome("Rosana")[1])                # ambíguo (regra do 'a')
        self.assertFalse(sexo_do_nome("Ivone")[1])                # exceção = confiável

    def test_comando_preenche_blanks(self):
        from django.core.management import call_command

        from apps.nucleo.models import Funcionario, Pessoa
        f = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Bruno Lima"),
                                       cargo="Recepcionista")
        call_command("preparar_escala")
        f.refresh_from_db()
        self.assertEqual(f.setor, "Recepção")
        self.assertEqual(f.sexo, "M")


class HoraExtraTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="he", password="senha-forte-123")
        self.manha = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0), min_pessoas=1)
        p = Pessoa.objects.create(nome="Gefferson")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção", setor="Recepção",
                                            sexo="M", regime_horas="extra")
        self.inicio = services.inicio_da_semana()

    def test_total_calculado(self):
        from apps.escala.models import HoraExtra
        he = HoraExtra(funcionario=self.f, data=self.inicio, inicio=time(18, 0), fim=time(22, 0))
        self.assertEqual(he.total_minutos, 240)
        self.assertEqual(he.total_txt, "4h00")
        he2 = HoraExtra(funcionario=self.f, data=self.inicio, inicio=time(22, 0), fim=time(2, 0))
        self.assertEqual(he2.total_txt, "4h00")   # cruzou a meia-noite

    def test_service_valida_total_positivo(self):
        with self.assertRaises(ValidationError):
            services.adicionar_hora_extra(self.f, self.inicio, time(20, 0), time(20, 0), "extra", self.op)

    def test_endpoint_add_e_remover(self):
        from apps.escala.models import HoraExtra
        self.client.force_login(self.op)
        semana = self.inicio.strftime("%Y-%m-%d")
        r = self.client.post(reverse("escala:editar"), {
            "inicio": semana, "acao": "he_add", "funcionario": self.f.pk,
            "data": semana, "he_inicio": "18:00", "he_fim": "22:00", "tipo": "extra",
        })
        self.assertEqual(r.status_code, 200)
        he = HoraExtra.objects.get(funcionario=self.f)
        self.assertEqual(he.total_txt, "4h00")
        self.assertEqual(he.tipo, "extra")
        r = self.client.post(reverse("escala:editar"), {
            "inicio": semana, "acao": "he_remover", "hora_extra": he.pk,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(HoraExtra.objects.exists())

    def test_hora_extra_entra_na_interjornada(self):
        # turno manhã no dia D e D+1, + hora extra 20-23 no dia D → D(23h)→D+1(07h)=8h
        d0, d1 = self.inicio, self.inicio + timedelta(days=1)
        services.atribuir(self.manha, self.f, d0, self.op)
        a1 = services.atribuir(self.manha, self.f, d1, self.op)
        # sem hora extra: sem violação de interjornada
        an = services.analisar_semana(self.inicio)
        self.assertNotIn(a1.pk, an["violacoes"])
        services.adicionar_hora_extra(self.f, d0, time(20, 0), time(23, 0), "extra", self.op)
        an = services.analisar_semana(self.inicio)
        self.assertIn(a1.pk, an["violacoes"])
        self.assertIn("interjornada <11h", an["bloqueios"])


class FeriadoCompTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="fc", password="senha-forte-123")
        self.turno = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0), min_pessoas=1)
        p = Pessoa.objects.create(nome="Gefferson")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção", setor="Recepção",
                                            sexo="M", compensacao_feriado="folga")
        self.inicio = services.inicio_da_semana()

    def test_definir_compensacao(self):
        a = services.atribuir(self.turno, self.f, self.inicio, self.op)
        services.definir_compensacao_feriado(a, "dobro")
        a.refresh_from_db()
        self.assertEqual(a.compensacao_feriado, "dobro")
        with self.assertRaises(ValidationError):
            services.definir_compensacao_feriado(a, "xyz")

    def test_endpoint_feriado_comp(self):
        a = services.atribuir(self.turno, self.f, self.inicio, self.op)
        self.client.force_login(self.op)
        r = self.client.post(reverse("escala:editar"), {
            "inicio": self.inicio.strftime("%Y-%m-%d"), "acao": "feriado_comp",
            "atribuicao": a.pk, "valor": "dobro",
        })
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.compensacao_feriado, "dobro")

    def test_feriados_no_periodo(self):
        from apps.escala.models import Feriado
        Feriado.objects.create(data=self.inicio, nome="Teste")
        fer = services.feriados_no_periodo(self.inicio, self.inicio + timedelta(days=6))
        self.assertIn(self.inicio, fer)


class RelatorioColaboradorTests(TestCase):
    def setUp(self):
        from datetime import date
        self.op = Usuario.objects.create_superuser(username="rel", password="senha-forte-123")
        self.turno = Turno.objects.create(nome="Manhã", setor="recepcao",
                                           inicio=time(7, 0), fim=time(15, 0))  # 8h
        p = Pessoa.objects.create(nome="Gefferson")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Recepção",
                                            compensacao_feriado="dobro")
        self.ini = date(2026, 3, 1)
        self.fim = date(2026, 3, 31)

    def test_agrega(self):
        from datetime import date

        from apps.escala.models import Feriado
        services.atribuir(self.turno, self.f, date(2026, 3, 2), self.op)   # 8h
        services.atribuir(self.turno, self.f, date(2026, 3, 3), self.op)   # 8h
        Feriado.objects.create(data=date(2026, 3, 3), nome="Feriado")
        services.adicionar_hora_extra(self.f, date(2026, 3, 2), time(18, 0), time(22, 0), "extra", self.op)
        services.adicionar_hora_extra(self.f, date(2026, 3, 4), time(19, 0), time(21, 0), "banco", self.op)
        services.registrar_ausencia(self.f, "folga", date(2026, 3, 10), date(2026, 3, 10), self.op)

        d = services.relatorio_colaborador(self.f, self.ini, self.fim)
        self.assertEqual(d["dias_trabalhados"], 2)
        self.assertEqual(d["horas_normais_txt"], "16h00")
        self.assertEqual(d["extra_txt"], "4h00")
        self.assertEqual(d["banco_txt"], "2h00")
        self.assertEqual(len(d["feriados_trabalhados"]), 1)
        self.assertEqual(d["feriados_trabalhados"][0]["compensacao"], "Pagamento em dobro")
        self.assertEqual(d["dias_ausente"], 1)

    def test_view_e_csv(self):
        self.client.force_login(self.op)
        r = self.client.get(reverse("escala:relatorio"), {"funcionario": self.f.pk, "mes": 3, "ano": 2026})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gefferson")
        c = self.client.get(reverse("escala:relatorio"),
                            {"funcionario": self.f.pk, "mes": 3, "ano": 2026, "export": "csv"})
        self.assertEqual(c["Content-Type"].split(";")[0], "text/csv")

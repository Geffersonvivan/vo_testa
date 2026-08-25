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

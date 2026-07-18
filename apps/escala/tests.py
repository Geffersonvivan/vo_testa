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

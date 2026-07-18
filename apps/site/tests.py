from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.site.forms import DadosHospedeForm, validar_cpf
from apps.site.models import (
    CategoriaQuarto,
    Hospede,
    Quarto,
    Reserva,
    Temporada,
)

CPF_VALIDO = '111.444.777-35'


def criar_quarto(nome='Cabine', capacidade=2, preco='400.00'):
    cat, _ = CategoriaQuarto.objects.get_or_create(nome='Suíte')
    return Quarto.objects.create(
        nome=nome, categoria=cat, descricao='x', descricao_curta='x',
        capacidade=capacidade, metragem=20, preco_base=Decimal(preco),
        status='disponivel',
    )


def criar_reserva(quarto, ci, co, status='confirmada', expira_em=None):
    h = Hospede.objects.create(
        nome='Fulano Teste', email=f'{status}{ci}@ex.com',
        telefone='4999', cpf=None,
    )
    r = Reserva(
        hospede=h, quarto=quarto, data_checkin=ci, data_checkout=co,
        num_hospedes=1, preco_noite=quarto.preco_base, status=status,
    )
    if expira_em is not None:
        r.expira_em = expira_em
    r.save()
    return r


class ModeloReservaTests(TestCase):
    def setUp(self):
        self.quarto = criar_quarto()
        self.ci = date.today() + timedelta(days=10)
        self.co = self.ci + timedelta(days=3)

    def test_codigo_e_token_gerados(self):
        r = criar_reserva(self.quarto, self.ci, self.co)
        self.assertTrue(r.codigo.startswith('VT-'))
        self.assertIsNotNone(r.token)

    def test_expira_em_definido_para_aguardando(self):
        r = criar_reserva(self.quarto, self.ci, self.co, status='aguardando')
        self.assertIsNotNone(r.expira_em)

    def test_confirmada_nao_define_expira(self):
        r = criar_reserva(self.quarto, self.ci, self.co, status='confirmada')
        self.assertIsNone(r.expira_em)

    def test_quarto_indisponivel_com_conflito(self):
        criar_reserva(self.quarto, self.ci, self.co, status='confirmada')
        meio = self.ci + timedelta(days=1)
        self.assertFalse(Reserva.quarto_disponivel(self.quarto, meio, meio + timedelta(days=2)))

    def test_quarto_disponivel_sem_sobreposicao(self):
        criar_reserva(self.quarto, self.ci, self.co, status='confirmada')
        depois = self.co + timedelta(days=1)
        self.assertTrue(Reserva.quarto_disponivel(self.quarto, depois, depois + timedelta(days=2)))

    def test_aguardando_expirada_libera_quarto(self):
        passado = timezone.now() - timedelta(minutes=1)
        criar_reserva(self.quarto, self.ci, self.co, status='aguardando', expira_em=passado)
        self.assertTrue(Reserva.quarto_disponivel(self.quarto, self.ci, self.co))

    def test_aguardando_ativa_bloqueia_quarto(self):
        futuro = timezone.now() + timedelta(minutes=20)
        criar_reserva(self.quarto, self.ci, self.co, status='aguardando', expira_em=futuro)
        self.assertFalse(Reserva.quarto_disponivel(self.quarto, self.ci, self.co))

    def test_preco_por_temporada(self):
        Temporada.objects.create(
            nome='Alta', tipo='alta', data_inicio=self.ci - timedelta(days=1),
            data_fim=self.co + timedelta(days=1), multiplicador=Decimal('1.50'),
        )
        preco = Reserva.calcular_preco_noite(self.quarto, self.ci)
        self.assertEqual(preco, Decimal('600.00'))  # 400 * 1.5


class CpfTests(TestCase):
    def test_cpf_valido(self):
        self.assertEqual(validar_cpf(CPF_VALIDO), '11144477735')

    def test_cpf_invalido_digitos(self):
        form = DadosHospedeForm(data={
            'nome': 'X', 'email': 'a@a.com', 'telefone': '49991438813', 'cpf': '123.456.789-00',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('cpf', form.errors)

    def test_cpf_repetido_invalido(self):
        form = DadosHospedeForm(data={
            'nome': 'X', 'email': 'a@a.com', 'telefone': '49991438813', 'cpf': '111.111.111-11',
        })
        self.assertFalse(form.is_valid())


class FluxoReservaViewTests(TestCase):
    def setUp(self):
        # Rate-limit do site usa LocMemCache (persiste entre testes do processo).
        from django.core.cache import cache
        cache.clear()
        # Fonte da verdade no CRM: um tipo com 1 quarto físico; o card do site aponta pra ele.
        from apps.nucleo.models import UH, TipoUH
        self.tipo = TipoUH.objects.create(nome='Suíte', tarifa_base=Decimal('400.00'))
        UH.objects.create(numero='S1', tipo=self.tipo)
        self.quarto = criar_quarto()
        self.quarto.tipo_uh = self.tipo
        self.quarto.save(update_fields=['tipo_uh'])
        self.ci = (date.today() + timedelta(days=10)).strftime('%Y-%m-%d')
        self.co = (date.today() + timedelta(days=13)).strftime('%Y-%m-%d')

    def _post_finalizar(self, **over):
        dados = {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Maria Teste',
            'email': 'maria@ex.com', 'telefone': '49991438813', 'cpf': CPF_VALIDO,
            'observacoes': '',
        }
        dados.update(over)
        return self.client.post(reverse('core:finalizar_reserva'), dados)

    def test_passo1_datas_ok(self):
        self.assertEqual(self.client.get(reverse('core:reservar')).status_code, 200)

    def test_passo2_lista_quartos(self):
        resp = self.client.get(reverse('core:reservar'), {
            'checkin': self.ci, 'checkout': self.co, 'hospedes': 2,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.quarto.nome)

    def test_finalizar_cria_reserva_no_site_e_no_crm(self):
        from apps.pagamentos.models import Cobranca
        from apps.reservas.models import Reserva as CrmReserva
        resp = self._post_finalizar()
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.status, 'aguardando')
        self.assertIn(str(reserva.token), resp['Location'])
        # A integração: criou a reserva real no CRM (pré-reserva, canal site).
        self.assertIsNotNone(reserva.crm_reserva_id)
        crm = CrmReserva.objects.get(pk=reserva.crm_reserva_id)
        self.assertEqual(crm.status, CrmReserva.Status.PRE_RESERVA)
        self.assertEqual(crm.canal, CrmReserva.Canal.SITE)
        self.assertEqual(crm.uh.tipo, self.tipo)
        # Cobrança de sinal (Pix) ligada ao recibo do site.
        self.assertTrue(reserva.pagamento_id)
        cob = Cobranca.objects.get(token=reserva.pagamento_id)
        self.assertEqual(cob.finalidade, Cobranca.Finalidade.SINAL)
        self.assertEqual(cob.reserva_id, crm.pk)

    def test_confirmada_oferece_pagar_agora(self):
        self._post_finalizar()
        reserva = Reserva.objects.get()
        resp = self.client.get(reverse('core:reserva_confirmada', args=[reserva.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pagar agora')

    def test_resumo_mostra_formas_de_pagamento(self):
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Maria Teste',
            'email': 'maria@ex.com', 'telefone': '49991438813',
            'cpf': CPF_VALIDO, 'observacoes': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Forma de pagamento')
        self.assertContains(resp, 'value="pix"')
        self.assertContains(resp, 'value="cartao"')
        self.assertContains(resp, 'value="boleto"')

    def test_finalizar_com_cartao_cria_cobranca_cartao(self):
        from apps.pagamentos.models import Cobranca
        resp = self._post_finalizar(metodo_pagamento='cartao')
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.metodo_pagamento, 'cartao')
        self.assertEqual(reserva.desconto_percentual, 0)
        cob = Cobranca.objects.get(token=reserva.pagamento_id)
        self.assertEqual(cob.metodo, Cobranca.Metodo.CARTAO)
        self.assertEqual(cob.valor, reserva.valor_total)

    def test_mesmo_cpf_reutiliza_hospede_e_avanca(self):
        """CPF já cadastrado não bloqueia Continuar — reutiliza o hóspede."""
        from apps.site.models import Hospede
        Hospede.objects.create(
            nome='Gefferson Antigo', email='outro@ex.com',
            telefone='49990000000', cpf='111.444.777-35',
        )
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Gefferson Novo',
            'email': 'geffersonvivan@gmail.com', 'telefone': '49991438813',
            'cpf': '11144477735', 'observacoes': 'Teste',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'já existe')
        self.assertContains(resp, 'Confirmar Reserva')  # passo 4
        self.assertEqual(Hospede.objects.filter(cpf='111.444.777-35').count(), 1)

        # Finalizar atualiza o cadastro existente (mesmo CPF).
        resp = self._post_finalizar(
            nome='Gefferson Novo', email='geffersonvivan@gmail.com',
            telefone='49991438813', cpf='11144477735',
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Hospede.objects.count(), 1)
        h = Hospede.objects.get(cpf='111.444.777-35')
        self.assertEqual(h.email, 'geffersonvivan@gmail.com')
        self.assertEqual(h.nome, 'Gefferson Novo')

    def test_email_e_cpf_em_cadastros_diferentes_unifica(self):
        """Bug real: e-mail num hóspede (CPF lixo) e CPF noutro — Continuar unifica."""
        legado = Hospede.objects.create(
            nome='Legado Email', email='geffersonvivan@gmail.com',
            telefone='49990000000', cpf='vivan',
        )
        por_cpf = Hospede.objects.create(
            nome='Por CPF', email='typo@ex.com',
            telefone='49991111111', cpf='111.444.777-35',
        )
        # Reserva antiga no legado deve migrar para o do CPF.
        ci = date.today() + timedelta(days=40)
        Reserva.objects.create(
            hospede=legado, quarto=self.quarto,
            data_checkin=ci, data_checkout=ci + timedelta(days=2),
            num_hospedes=1, preco_noite=self.quarto.preco_base,
            status='confirmada',
        )
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Gefferson Vivan',
            'email': 'geffersonvivan@gmail.com', 'telefone': '49991438813',
            'cpf': '11144477735', 'observacoes': 'teste 02',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'já existe')
        self.assertContains(resp, 'Confirmar Reserva')
        # Unificação do legado (e-mail) acontece na validação do Continuar.
        self.assertFalse(Hospede.objects.filter(pk=legado.pk).exists())
        self.assertEqual(Reserva.objects.filter(hospede=por_cpf).count(), 1)
        self.assertEqual(Hospede.objects.filter(cpf='111.444.777-35').count(), 1)

        # Finalizar grava o e-mail correto no cadastro do CPF.
        form = DadosHospedeForm(
            data={
                'nome': 'Gefferson Vivan', 'email': 'geffersonvivan@gmail.com',
                'telefone': '49991438813', 'cpf': '11144477735', 'observacoes': '',
            },
            instance=por_cpf,
        )
        self.assertTrue(form.is_valid(), form.errors)
        h = form.save()
        self.assertEqual(h.email, 'geffersonvivan@gmail.com')
        self.assertEqual(h.pk, por_cpf.pk)

    def test_finalizar_envia_email_de_confirmacao(self):
        from django.core import mail
        self._post_finalizar()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('maria@ex.com', mail.outbox[0].to)
        self.assertIn('Reserva', mail.outbox[0].subject)
        reserva = Reserva.objects.get()
        self.assertIn(f'/reserva/{reserva.token}/', mail.outbox[0].body)
        html = mail.outbox[0].alternatives[0][0]
        self.assertTrue(
            'Ver reserva' in html or 'Ver minha reserva' in html,
            html[:200],
        )
        self.assertIn('cid:email-hero', html)

    def test_confirmacao_por_token_ok(self):
        self._post_finalizar()
        reserva = Reserva.objects.get()
        resp = self.client.get(reverse('core:reserva_confirmada', args=[reserva.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reserva.codigo)

    def test_finalizar_bloqueia_conflito(self):
        # Só há 1 quarto físico do tipo → a 2ª reserva no mesmo período é barrada pelo CRM.
        self._post_finalizar()
        resp = self._post_finalizar(email='outro@ex.com')
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(resp.status_code, 302)

    def test_endpoint_buscar_hospede_removido(self):
        # S1: o endpoint que vazava CPF por email não existe mais.
        resp = self.client.get('/reservar/hospede/', {'email': 'maria@ex.com'})
        self.assertEqual(resp.status_code, 404)

    def test_dia_na_pousada_no_fluxo_reservar(self):
        from apps.nucleo.models import UH, TipoUH
        from apps.reservas.models import Reserva as CrmReserva
        from apps.site.models import CategoriaQuarto
        tipo = TipoUH.objects.get(nome='Dia na Pousada')
        self.assertEqual(tipo.modalidade, 'day_use')
        self.assertTrue(UH.objects.filter(tipo=tipo).exists())
        cat, _ = CategoriaQuarto.objects.get_or_create(nome='Dia na Pousada')
        quarto, _ = Quarto.objects.get_or_create(
            tipo_uh=tipo,
            defaults={
                'nome': 'Dia na Pousada', 'categoria': cat,
                'descricao': 'x', 'descricao_curta': 'x',
                'capacidade': 10, 'metragem': 0, 'preco_base': tipo.tarifa_base,
                'status': 'disponivel', 'destaque': True,
            },
        )
        ci = (date.today() + timedelta(days=15)).strftime('%Y-%m-%d')
        resp = self.client.get(reverse('core:reservar'), {
            'checkin': ci, 'hospedes': 2, 'modalidade': 'day_use',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dia na Pousada')
        co = (date.today() + timedelta(days=16)).strftime('%Y-%m-%d')
        resp = self.client.post(reverse('core:finalizar_reserva'), {
            'quarto_id': quarto.id, 'checkin': ci, 'checkout': co,
            'hospedes': 2, 'modalidade': 'day_use', 'metodo_pagamento': 'pix',
            'nome': 'Day User', 'email': 'day@ex.com', 'telefone': '49991438813',
            'cpf': CPF_VALIDO, 'observacoes': '',
        })
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.latest('id')
        crm = CrmReserva.objects.get(pk=reserva.crm_reserva_id)
        self.assertEqual(crm.uh.tipo.modalidade, 'day_use')


class EventosEHomeTests(TestCase):
    def test_home_tem_secoes_eventos_e_dia(self):
        resp = self.client.get(reverse('core:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="eventos"')
        self.assertContains(resp, 'id="dia-pousada"')
        self.assertContains(resp, 'Dia na Pousada')

    def test_proposta_evento_cria_oportunidade(self):
        from apps.comercial.models import Oportunidade
        r = self.client.post(reverse('core:pedir_proposta'), {
            'nome': 'Empresa XPTO',
            'telefone': '4999887766',
            'email': 'evento@xpto.com',
            'tipo_interesse': 'evento',
            'hospedes': '30',
            'mensagem': 'Confraternização de fim de ano',
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('proposta=ok', r['Location'])
        self.assertIn('#eventos', r['Location'])
        op = Oportunidade.objects.get(pessoa__email='evento@xpto.com')
        self.assertEqual(op.tipo_interesse, 'evento')
        self.assertIn('Evento', op.titulo)

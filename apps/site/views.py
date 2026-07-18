import logging
from decimal import Decimal

from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

logger = logging.getLogger(__name__)

from apps.site.forms import (
    BuscaDisponibilidadeForm,
    DadosHospedeForm,
    PropostaSiteForm,
    encontrar_hospede,
)
from apps.site.models import (
    ConfiguracaoSite,
    Depoimento,
    Experiencia,
    FotoGaleria,
    Hospede,
    Quarto,
    Reserva,
    Temporada,
)


def _is_htmx(request):
    return request.headers.get('HX-Request') == 'true'


def _limite_excedido(request, escopo, limite, janela_seg):
    """Rate limit simples por IP via cache. True se passou do limite na janela.

    Obs.: em produção use um cache compartilhado (Redis); o LocMemCache é por processo.
    """
    ip = request.META.get('REMOTE_ADDR', 'desconhecido')
    chave = f'ratelimit:{escopo}:{ip}'
    cache.add(chave, 0, janela_seg)
    try:
        atual = cache.incr(chave)
    except ValueError:
        cache.set(chave, 1, janela_seg)
        atual = 1
    return atual > limite


def _usuario_sistema():
    """Usuário de sistema para atribuir reservas vindas do site (auditoria)."""
    from django.contrib.auth import get_user_model
    U = get_user_model()
    user, criado = U.objects.get_or_create(
        username="_site", defaults={"is_active": True, "first_name": "Site"}
    )
    if criado:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def home(request):
    config = ConfiguracaoSite.load()
    quartos = Quarto.objects.filter(
        status='disponivel', destaque=True, tipo_uh__isnull=False,
        tipo_uh__modalidade='hospedagem',
    ).select_related('categoria')[:6]
    dia_pousada = Quarto.objects.filter(
        status='disponivel', tipo_uh__modalidade='day_use',
    ).select_related('categoria', 'tipo_uh').first()
    experiencias = Experiencia.objects.filter(destaque=True)
    depoimentos = Depoimento.objects.filter(destaque=True)[:6]
    galeria = FotoGaleria.objects.all()[:12]
    galeria_faixa = FotoGaleria.objects.all()[:6]

    # Rascunho após erro de validação (PRG) — preenche o form de volta uma vez.
    proposta = {}
    if request.GET.get('proposta') == 'erro':
        proposta = request.session.pop('proposta_rascunho', {}) or {}

    context = {
        'config': config,
        'quartos': quartos,
        'dia_pousada': dia_pousada,
        'experiencias': experiencias,
        'depoimentos': depoimentos,
        'galeria': galeria,
        'galeria_faixa': galeria_faixa,
        'proposta_form': PropostaSiteForm(),
        'proposta': proposta,
    }
    return render(request, 'site/home.html', context)


def pedir_proposta(request):
    """Formulário #contato / #eventos → Comercial. Degrada se módulo off."""
    if request.method != 'POST':
        return redirect(reverse('core:home') + '#contato')
    ancora = '#eventos' if request.POST.get('tipo_interesse') == 'evento' else '#contato'

    def _voltar(flag):
        # Query string antes do hash — senão o browser descarta o ?proposta=
        return redirect(reverse('core:home') + f'?proposta={flag}' + ancora)

    if _limite_excedido(request, 'proposta', 8, 3600):
        messages.error(request, 'Muitas tentativas. Tente novamente mais tarde.')
        return _voltar('erro')
    form = PropostaSiteForm(request.POST)
    if not form.is_valid():
        erros = []
        for campo, lista in form.errors.items():
            for err in lista:
                erros.append(str(err))
        messages.error(
            request,
            ' · '.join(erros) if erros else 'Confira os dados do formulário.',
        )
        # Guarda o que veio no POST para reexibir (redirect limpa os inputs).
        request.session['proposta_rascunho'] = {
            chave: request.POST.get(chave, '')
            for chave in (
                'nome', 'telefone', 'email', 'tipo_interesse',
                'checkin', 'checkout', 'hospedes', 'mensagem',
            )
        }
        return _voltar('erro')
    dados = form.cleaned_data
    request.session.pop('proposta_rascunho', None)
    try:
        from apps.comercial import services as comercial
        op = comercial.capturar_lead_site(
            nome=dados['nome'],
            email=dados.get('email') or '',
            telefone=dados.get('telefone') or '',
            mensagem=dados.get('mensagem') or '',
            checkin=dados.get('checkin'),
            checkout=dados.get('checkout'),
            hospedes=dados.get('hospedes') or 2,
            tipo_interesse=dados.get('tipo_interesse') or 'hospedagem',
        )
    except Exception:
        logger.exception('Falha ao capturar lead do site')
        messages.error(
            request,
            'Não foi possível registrar o pedido agora. Tente de novo ou fale pelo WhatsApp.',
        )
        return _voltar('erro')
    if op is None:
        messages.warning(
            request,
            'Recebemos sua mensagem, mas o funil comercial está temporariamente indisponível. '
            'Retornaremos pelo WhatsApp ou e-mail.',
        )
        return _voltar('aviso')
    messages.success(
        request,
        'Recebemos seu pedido! Em breve entraremos em contato pelo WhatsApp ou e-mail.',
    )
    return _voltar('ok')


# --------------------------------------------------------------------------- #
# Reservas — helpers
# --------------------------------------------------------------------------- #

def _temporada_de(data):
    """Temporada vigente na data (a de maior multiplicador, se sobrepostas)."""
    return Temporada.objects.filter(
        data_inicio__lte=data, data_fim__gte=data,
    ).order_by('-multiplicador').first()


def _buscar_quartos(checkin, checkout, hospedes, modalidade=""):
    """Tipos disponíveis — disponibilidade e preço vêm do CRM.
    `modalidade`: '' | 'hospedagem' | 'day_use'."""
    from apps.reservas import services as reservas

    noites = (checkout - checkin).days
    qs = Quarto.objects.filter(
        status='disponivel', tipo_uh__isnull=False, capacidade__gte=hospedes,
    ).select_related('categoria', 'tipo_uh')
    if modalidade in ('hospedagem', 'day_use'):
        qs = qs.filter(tipo_uh__modalidade=modalidade)
    quartos = list(qs)
    resultados = []
    for quarto in quartos:
        disponivel = reservas.tipo_disponivel(quarto.tipo_uh, checkin, checkout)
        preco_noite = reservas.diaria_media(quarto.tipo_uh, checkin, checkout)
        day = getattr(quarto.tipo_uh, 'modalidade', '') == 'day_use'
        resultados.append({
            'quarto': quarto,
            'disponivel': disponivel,
            'preco_base': quarto.preco_base,
            'temporada': _temporada_de(checkin),
            'tem_ajuste': preco_noite != quarto.preco_base,
            'preco_noite': preco_noite,
            'noites': noites,
            'total': preco_noite * noites,
            'eh_day_use': day,
            'unidade_preco': 'dia' if day else 'noite',
        })
    resultados.sort(key=lambda r: (not r['disponivel'], not r['eh_day_use'], r['quarto'].ordem))
    return resultados


def _resumo_preco(quarto, checkin, checkout, metodo='pix'):
    """Resumo de valores da reserva (com desconto Pix quando aplicável)."""
    from apps.reservas import services as reservas
    config = ConfiguracaoSite.load()
    noites = (checkout - checkin).days
    temporada = _temporada_de(checkin)
    preco_noite = reservas.diaria_media(quarto.tipo_uh, checkin, checkout)
    subtotal = preco_noite * noites
    desconto_pct = Decimal(config.desconto_pix) if metodo == 'pix' else Decimal('0')
    desconto_valor = subtotal * desconto_pct / 100
    day = getattr(quarto.tipo_uh, 'modalidade', '') == 'day_use'
    return {
        'noites': noites,
        'temporada': temporada,
        'preco_base': quarto.preco_base,
        'preco_noite': preco_noite,
        'subtotal': subtotal,
        'metodo': metodo,
        'desconto_pct': desconto_pct,
        'desconto_valor': desconto_valor,
        'total': subtotal - desconto_valor,
        'eh_day_use': day,
        'unidade_preco': 'dia' if day else 'noite',
    }


def _url_busca(checkin, checkout, hospedes, modalidade=''):
    url = (
        f"{reverse('core:reservar')}"
        f"?checkin={checkin:%Y-%m-%d}&checkout={checkout:%Y-%m-%d}&hospedes={hospedes}"
    )
    if modalidade:
        url += f"&modalidade={modalidade}"
    return url


def redirect_busca(checkin, checkout, hospedes, modalidade=''):
    return redirect(_url_busca(checkin, checkout, hospedes, modalidade))


def _modalidade_do_quarto(quarto):
    if quarto.tipo_uh_id and getattr(quarto.tipo_uh, 'modalidade', None) == 'day_use':
        return 'day_use'
    return 'hospedagem'


# --------------------------------------------------------------------------- #
# Reservas — passos do fluxo
# --------------------------------------------------------------------------- #

def reservar(request):
    """Passo 1 (datas) e Passo 2 (quartos / Dia na Pousada disponíveis)."""
    modalidade = request.GET.get('modalidade', '') or ''
    tem_busca = bool(request.GET.get('checkin'))
    if tem_busca:
        form = BuscaDisponibilidadeForm(request.GET)
    else:
        form = BuscaDisponibilidadeForm(initial={'modalidade': modalidade})

    resultados = None
    busca = None
    passo = 1
    num_disponiveis = 0

    if tem_busca and form.is_valid():
        checkin = form.cleaned_data['checkin']
        checkout = form.cleaned_data['checkout']
        hospedes = form.cleaned_data['hospedes']
        modalidade = form.cleaned_data.get('modalidade') or ''
        resultados = _buscar_quartos(checkin, checkout, hospedes, modalidade)
        num_disponiveis = sum(1 for r in resultados if r['disponivel'])
        busca = {
            'checkin': checkin, 'checkout': checkout, 'hospedes': hospedes,
            'noites': (checkout - checkin).days,
            'modalidade': modalidade,
            'eh_day_use': modalidade == 'day_use',
        }
        passo = 2

    context = {
        'form': form, 'resultados': resultados, 'busca': busca,
        'passo': passo, 'num_disponiveis': num_disponiveis,
        'modalidade': modalidade,
        'eh_day_use': modalidade == 'day_use',
    }
    if passo == 2:
        return render(request, 'site/reservas/quartos.html', context)
    return render(request, 'site/reservas/datas.html', context)


def info_datas(request):
    """Fragmento HTMX (passo 1): resumo da seleção de datas (noites + temporada)."""
    form = BuscaDisponibilidadeForm(request.GET)
    context = {'busca': None, 'temporada': None, 'noites': 0}
    if form.is_valid():
        checkin = form.cleaned_data['checkin']
        checkout = form.cleaned_data['checkout']
        context = {
            'busca': {
                'checkin': checkin,
                'checkout': checkout,
                'hospedes': form.cleaned_data['hospedes'],
            },
            'temporada': _temporada_de(checkin),
            'noites': (checkout - checkin).days,
        }
    return render(request, 'site/reservas/partials/info_datas.html', context)


def selecionar_quarto(request, quarto_id):
    """Passo 3 — dados do hóspede para o quarto / Dia na Pousada escolhido."""
    quarto = get_object_or_404(
        Quarto.objects.select_related('tipo_uh'), pk=quarto_id, status='disponivel',
    )
    form = BuscaDisponibilidadeForm(request.GET or None)

    if not (request.GET and form.is_valid()):
        messages.error(request, 'Selecione datas válidas para continuar a reserva.')
        return redirect('core:reservar')

    checkin = form.cleaned_data['checkin']
    checkout = form.cleaned_data['checkout']
    hospedes = form.cleaned_data['hospedes']
    modalidade = form.cleaned_data.get('modalidade') or _modalidade_do_quarto(quarto)

    from apps.reservas import services as reservas
    if hospedes > quarto.capacidade:
        messages.error(request, 'Esta opção não comporta o número de pessoas.')
        return redirect_busca(checkin, checkout, hospedes, modalidade)
    if not reservas.tipo_disponivel(quarto.tipo_uh, checkin, checkout):
        messages.error(request, 'Esta opção não está mais disponível nessas datas.')
        return redirect_busca(checkin, checkout, hospedes, modalidade)

    context = {
        'passo': 3,
        'quarto': quarto,
        'busca': {
            'checkin': checkin, 'checkout': checkout, 'hospedes': hospedes,
            'modalidade': modalidade,
        },
        'resumo': _resumo_preco(quarto, checkin, checkout),
        'dados_form': DadosHospedeForm(),
        'config': ConfiguracaoSite.load(),
        'eh_day_use': _modalidade_do_quarto(quarto) == 'day_use',
        'modalidade': modalidade,
    }
    return render(request, 'site/reservas/dados.html', context)


def resumo_reserva(request):
    """Passo 4 — revisão da reserva antes de confirmar (sem persistir ainda)."""
    if request.method != 'POST':
        return redirect('core:reservar')

    quarto = get_object_or_404(
        Quarto.objects.select_related('tipo_uh'),
        pk=request.POST.get('quarto_id'), status='disponivel',
    )
    modalidade = request.POST.get('modalidade') or _modalidade_do_quarto(quarto)
    busca_form = BuscaDisponibilidadeForm({
        'checkin': request.POST.get('checkin'),
        'checkout': request.POST.get('checkout'),
        'hospedes': request.POST.get('hospedes'),
        'modalidade': modalidade,
    })
    hospede_existente = encontrar_hospede(
        email=request.POST.get('email', ''),
        cpf=request.POST.get('cpf', ''),
    )
    dados_form = DadosHospedeForm(request.POST, instance=hospede_existente)
    metodo = request.POST.get('metodo_pagamento', 'pix')

    # Validação: se algo falhar, volta ao passo 3 mostrando os erros.
    if not busca_form.is_valid() or not dados_form.is_valid():
        context = {
            'passo': 3,
            'quarto': quarto,
            'busca': busca_form.cleaned_data or {},
            'resumo': None,
            'dados_form': dados_form,
            'config': ConfiguracaoSite.load(),
            'eh_day_use': _modalidade_do_quarto(quarto) == 'day_use',
            'modalidade': modalidade,
        }
        if busca_form.is_valid():
            context['busca'] = busca_form.cleaned_data
            context['resumo'] = _resumo_preco(
                quarto, busca_form.cleaned_data['checkin'],
                busca_form.cleaned_data['checkout'], metodo,
            )
        return render(request, 'site/reservas/dados.html', context)

    checkin = busca_form.cleaned_data['checkin']
    checkout = busca_form.cleaned_data['checkout']
    hospedes = busca_form.cleaned_data['hospedes']

    from apps.reservas import services as reservas
    if hospedes > quarto.capacidade or not reservas.tipo_disponivel(quarto.tipo_uh, checkin, checkout):
        messages.error(request, 'Esta opção não está mais disponível nessas datas.')
        return redirect_busca(checkin, checkout, hospedes, modalidade)

    context = {
        'passo': 4,
        'quarto': quarto,
        'busca': {
            'checkin': checkin, 'checkout': checkout, 'hospedes': hospedes,
            'modalidade': modalidade,
        },
        'resumo': _resumo_preco(quarto, checkin, checkout, metodo),
        'dados': dados_form.cleaned_data,
        'metodo': metodo,
        'config': ConfiguracaoSite.load(),
        'eh_day_use': _modalidade_do_quarto(quarto) == 'day_use',
        'modalidade': modalidade,
    }
    return render(request, 'site/reservas/resumo.html', context)


@transaction.atomic
def finalizar_reserva(request):
    """Cria a reserva (status aguardando pagamento) após revalidar tudo. Vem do passo 4."""
    if request.method != 'POST':
        return redirect('core:reservar')

    # Anti-spam: no máximo 8 reservas por IP por hora.
    if _limite_excedido(request, 'reserva', limite=8, janela_seg=3600):
        messages.error(request, 'Muitas reservas em pouco tempo. Tente novamente mais tarde.')
        return redirect('core:reservar')

    quarto = get_object_or_404(
        Quarto.objects.select_related('tipo_uh'), pk=request.POST.get('quarto_id'),
    )
    modalidade = request.POST.get('modalidade') or _modalidade_do_quarto(quarto)
    busca_form = BuscaDisponibilidadeForm({
        'checkin': request.POST.get('checkin'),
        'checkout': request.POST.get('checkout'),
        'hospedes': request.POST.get('hospedes'),
        'modalidade': modalidade,
    })
    hospede_existente = encontrar_hospede(
        email=request.POST.get('email', ''),
        cpf=request.POST.get('cpf', ''),
    )
    dados_form = DadosHospedeForm(request.POST, instance=hospede_existente)
    metodo = request.POST.get('metodo_pagamento', 'pix')

    if not busca_form.is_valid() or not dados_form.is_valid():
        messages.error(request, 'Não foi possível concluir a reserva. Revise seus dados.')
        return redirect('core:reservar')

    checkin = busca_form.cleaned_data['checkin']
    checkout = busca_form.cleaned_data['checkout']
    hospedes = busca_form.cleaned_data['hospedes']

    from django.core.exceptions import ValidationError as VErr

    from apps.reservas import services as reservas

    if hospedes > quarto.capacidade:
        messages.error(request, 'Esta opção não comporta o número de pessoas.')
        return redirect_busca(checkin, checkout, hospedes, modalidade)

    hospede = dados_form.save()  # registro do hóspede no canal (site)

    # Cria o hóspede e a PRÉ-RESERVA no CRM — fonte da verdade (aloca UH física,
    # bloqueia overbooking pela constraint). O preço também vem do CRM.
    pessoa = reservas.obter_ou_criar_hospede(
        nome=hospede.nome, email=hospede.email, telefone=hospede.telefone,
        documento=getattr(hospede, 'cpf', '') or '',
    )
    rotulo = 'Dia na Pousada' if modalidade == 'day_use' else 'Reserva'
    try:
        crm_reserva = reservas.criar_reserva_site(
            tipo_uh=quarto.tipo_uh, checkin=checkin, checkout=checkout,
            hospede=pessoa, usuario=_usuario_sistema(),
            adultos=hospedes, criancas=0,
            observacoes=f'{rotulo} pelo site — {hospede.nome}',
        )
    except VErr as erro:
        messages.error(request, ' '.join(erro.messages))
        return redirect_busca(checkin, checkout, hospedes, modalidade)

    config = ConfiguracaoSite.load()
    desconto = Decimal(config.desconto_pix) if metodo == 'pix' else Decimal('0')
    reserva = Reserva.objects.create(
        hospede=hospede,
        quarto=quarto,
        data_checkin=checkin,
        data_checkout=checkout,
        num_hospedes=hospedes,
        preco_noite=crm_reserva.valor_diaria,
        desconto_percentual=desconto,
        metodo_pagamento=metodo,
        status='aguardando',
        crm_reserva_id=crm_reserva.pk,
    )
    # Cobrança de sinal/pagamento online (Pix) — degrada se Pagamentos off ou gateway falhar.
    cobranca = _criar_cobranca_site(reserva, pessoa)
    if cobranca:
        reserva.pagamento_id = str(cobranca.token)
        reserva.save(update_fields=['pagamento_id', 'atualizado_em'])
    from apps.site.emails import enviar_confirmacao
    enviar_confirmacao(reserva)  # e-mail ao hóspede (não quebra o fluxo se falhar)
    return redirect('core:reserva_confirmada', token=reserva.token)


def _criar_cobranca_site(reserva, pessoa):
    """Cria cobrança no módulo Pagamentos (método escolhido no site)."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo
    if not modulo_ativo(Modulo.PAGAMENTOS):
        return None
    from django.core.exceptions import ValidationError as VErr
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import criar_cobranca
    metodo = reserva.metodo_pagamento if reserva.metodo_pagamento in (
        'pix', 'cartao', 'boleto', 'link',
    ) else 'pix'
    try:
        return criar_cobranca(
            _usuario_sistema(),
            valor=reserva.valor_total,
            metodo=metodo,
            descricao=f'Sinal site {reserva.codigo}',
            finalidade=Cobranca.Finalidade.SINAL,
            pagador=pessoa,
            reserva_id=reserva.crm_reserva_id,
        )
    except VErr:
        return None


def lab(request):
    """Hub oculto (não listado) com os protótipos de inovação para avaliação interna."""
    return render(request, 'site/lab.html')


def reserva_confirmada(request, token):
    """Passo 5 — confirmação (URL usa token aleatório, não o código previsível)."""
    reserva = get_object_or_404(
        Reserva.objects.select_related('hospede', 'quarto'), token=token
    )
    cobranca = None
    if reserva.pagamento_id:
        try:
            from apps.pagamentos.models import Cobranca
            cobranca = Cobranca.objects.filter(token=reserva.pagamento_id).first()
        except Exception:
            cobranca = None
    return render(request, 'site/reservas/confirmada.html', {
        'passo': 5,
        'reserva': reserva,
        'config': ConfiguracaoSite.load(),
        'cobranca': cobranca,
    })

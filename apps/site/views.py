import logging
from decimal import Decimal
from types import SimpleNamespace

from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
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
    VitrineQuarto,
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
    from apps.reservas import services as reservas
    # Vitrine por unidade: os 9 melhores quartos (grid 3×3), destaque primeiro.
    vitrines = _vitrines_publicadas().order_by('-destaque', 'ordem', 'uh__numero')[:9]
    quartos = [_card_de_uh(v, reservas.tarifa_base_unidade(v.uh)) for v in vitrines]
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


def quartos_todos(request):
    """Página com TODOS os quartos (venda por unidade) — a partir do "Ver todos"."""
    from apps.reservas import services as reservas
    vitrines = _vitrines_publicadas().order_by('ordem', 'uh__numero')
    quartos = [_card_de_uh(v, reservas.tarifa_base_unidade(v.uh)) for v in vitrines]
    return render(request, 'site/quartos_todos.html', {
        'config': ConfiguracaoSite.load(),
        'quartos': quartos,
    })


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


def _qualidades_uh(uh):
    """Diferenciais do quarto para os selos do card (a partir dos campos do CRM)."""
    q = []
    if uh.vista_lago:
        q.append('Vista para o lago')
    if uh.varanda:
        q.append('Varanda')
    if uh.ar_condicionado:
        q.append('Ar-condicionado')
    if uh.aceita_pet:
        q.append('Aceita pet')
    if uh.tipo_cama:
        q.append(uh.get_tipo_cama_display())
    if uh.pcd:
        q.append('Acessível (PCD)')
    return q


def _card_de_uh(vitrine, preco=None):
    """Card de vitrine de um quarto físico (UH) — nome temático, qualidades e mídia.
    Exposto no template com a mesma cara de um `Quarto`, mas por unidade."""
    uh = vitrine.uh
    nome = uh.nome_tematico or f'Quarto {uh.numero}'
    return SimpleNamespace(
        id=uh.pk, uh_id=uh.pk, numero=uh.numero,
        nome=nome,
        descricao_curta=vitrine.descricao_curta or nome,
        descricao=vitrine.descricao or uh.diferenciais,
        categoria=SimpleNamespace(nome=uh.tipo.nome),
        capacidade=uh.tipo.capacidade,
        metragem=vitrine.metragem or 0,
        nota_avaliacao=vitrine.nota_avaliacao,
        foto_principal=vitrine.foto_principal,
        tour_360_url=vitrine.tour_360_url,
        qualidades=_qualidades_uh(uh),
        preco_base=preco if preco is not None else Decimal('0'),
    )


def _vitrines_publicadas():
    """VitrineQuarto publicadas de quartos de hospedagem ativos (com o UH e o tipo)."""
    from apps.nucleo.models import TipoUH, UH
    return (
        VitrineQuarto.objects.filter(
            publicar=True, uh__status=UH.Status.ATIVA,
            uh__tipo__modalidade=TipoUH.Modalidade.HOSPEDAGEM,
        )
        .select_related('uh', 'uh__tipo')
    )


def _buscar_unidades(checkin, checkout, hospedes):
    """Disponibilidade e preço POR QUARTO (venda por unidade), formato do template."""
    from apps.reservas import services as reservas
    noites = (checkout - checkin).days
    vitrines = _vitrines_publicadas().filter(
        uh__tipo__capacidade__gte=hospedes,
    ).order_by('ordem', 'uh__numero')
    resultados = []
    for v in vitrines:
        disponivel = reservas.uh_disponivel(v.uh, checkin, checkout)
        base = reservas.tarifa_base_unidade(v.uh)
        preco_noite = reservas.diaria_media_unidade(v.uh, checkin, checkout)
        resultados.append({
            'quarto': _card_de_uh(v, base),
            'eh_unidade': True,
            'disponivel': disponivel,
            'preco_base': base,
            'temporada': _temporada_de(checkin),
            'tem_ajuste': preco_noite != base,
            'preco_noite': preco_noite,
            'noites': noites,
            'total': preco_noite * noites,
            'eh_day_use': False,
            'unidade_preco': 'noite',
        })
    resultados.sort(key=lambda r: (not r['disponivel'], r['quarto'].numero))
    return resultados


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


def _resumo_preco_unidade(uh, checkin, checkout, metodo='pix'):
    """Resumo de valores de um quarto específico (venda por unidade)."""
    from apps.reservas import services as reservas
    config = ConfiguracaoSite.load()
    noites = (checkout - checkin).days
    temporada = _temporada_de(checkin)
    preco_noite = reservas.diaria_media_unidade(uh, checkin, checkout)
    subtotal = preco_noite * noites
    desconto_pct = Decimal(config.desconto_pix) if metodo == 'pix' else Decimal('0')
    desconto_valor = subtotal * desconto_pct / 100
    return {
        'noites': noites,
        'temporada': temporada,
        'preco_base': reservas.tarifa_base_unidade(uh),
        'preco_noite': preco_noite,
        'subtotal': subtotal,
        'metodo': metodo,
        'desconto_pct': desconto_pct,
        'desconto_valor': desconto_valor,
        'total': subtotal - desconto_valor,
        'eh_day_use': False,
        'unidade_preco': 'noite',
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
    # Quarto pré-escolhido no card (deep-link): carrega até as datas e então pula
    # direto para aquele quarto, se estiver livre.
    uh_id = request.GET.get('uh', '') or ''
    quarto_escolhido = ''
    if uh_id:
        from apps.nucleo.models import UH
        _u = UH.objects.filter(pk=uh_id).first()
        if _u:
            quarto_escolhido = _u.nome_tematico or f'Quarto {_u.numero}'
        else:
            uh_id = ''
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
        # Deep-link de quarto: com datas válidas, vai direto ao quarto escolhido.
        if uh_id and modalidade != 'day_use':
            from apps.nucleo.models import UH
            from apps.reservas import services as reservas
            uh = UH.objects.filter(pk=uh_id, status=UH.Status.ATIVA).first()
            if uh and reservas.uh_disponivel(uh, checkin, checkout):
                destino = reverse('core:selecionar_unidade', args=[uh.pk])
                return redirect(
                    f"{destino}?checkin={checkin:%Y-%m-%d}"
                    f"&checkout={checkout:%Y-%m-%d}&hospedes={hospedes}"
                )
            if uh:
                messages.info(
                    request,
                    f'{uh.nome_tematico or "O quarto escolhido"} não está livre nessas '
                    'datas — veja as opções disponíveis abaixo.'
                )
        if modalidade == 'day_use':
            resultados = _buscar_quartos(checkin, checkout, hospedes, modalidade)
        else:
            resultados = _buscar_unidades(checkin, checkout, hospedes)
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
        'modalidade': modalidade, 'uh_id': uh_id,
        'quarto_escolhido': quarto_escolhido,
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


def _vitrine_ou_404(uh):
    """VitrineQuarto publicada do quarto, ou 404 (quarto sem vitrine não se reserva)."""
    from django.http import Http404
    v = VitrineQuarto.objects.filter(uh=uh, publicar=True).select_related(
        'uh', 'uh__tipo').first()
    if v is None:
        raise Http404('Quarto indisponível.')
    return v


def selecionar_unidade(request, uh_id):
    """Passo 3 — dados do hóspede para o QUARTO específico escolhido (venda por unidade)."""
    from apps.nucleo.models import UH
    from apps.reservas import services as reservas

    uh = get_object_or_404(UH, pk=uh_id, status=UH.Status.ATIVA)
    vitrine = _vitrine_ou_404(uh)
    form = BuscaDisponibilidadeForm(request.GET or None)
    if not (request.GET and form.is_valid()):
        messages.error(request, 'Selecione datas válidas para continuar a reserva.')
        return redirect('core:reservar')

    checkin = form.cleaned_data['checkin']
    checkout = form.cleaned_data['checkout']
    hospedes = form.cleaned_data['hospedes']

    if hospedes > uh.tipo.capacidade:
        messages.error(request, 'Este quarto não comporta o número de pessoas.')
        return redirect_busca(checkin, checkout, hospedes)
    if not reservas.uh_disponivel(uh, checkin, checkout):
        messages.error(request, 'Este quarto não está mais disponível nessas datas.')
        return redirect_busca(checkin, checkout, hospedes)

    context = {
        'passo': 3,
        'quarto': _card_de_uh(vitrine, reservas.tarifa_base_unidade(uh)),
        'uh_id': uh.pk,
        'busca': {'checkin': checkin, 'checkout': checkout, 'hospedes': hospedes,
                  'modalidade': 'hospedagem'},
        'resumo': _resumo_preco_unidade(uh, checkin, checkout),
        'dados_form': DadosHospedeForm(),
        'config': ConfiguracaoSite.load(),
        'eh_day_use': False,
        'modalidade': 'hospedagem',
    }
    return render(request, 'site/reservas/dados.html', context)


def _resumo_reserva_unidade(request):
    """Passo 4 (venda por unidade) — revisão da reserva de um quarto específico."""
    from apps.nucleo.models import UH
    from apps.reservas import services as reservas

    uh = get_object_or_404(UH, pk=request.POST.get('uh_id'), status=UH.Status.ATIVA)
    vitrine = _vitrine_ou_404(uh)
    card = _card_de_uh(vitrine, reservas.tarifa_base_unidade(uh))
    busca_form = BuscaDisponibilidadeForm({
        'checkin': request.POST.get('checkin'),
        'checkout': request.POST.get('checkout'),
        'hospedes': request.POST.get('hospedes'),
        'modalidade': 'hospedagem',
    })
    hospede_existente = encontrar_hospede(
        email=request.POST.get('email', ''), cpf=request.POST.get('cpf', ''),
    )
    dados_form = DadosHospedeForm(request.POST, instance=hospede_existente)
    metodo = request.POST.get('metodo_pagamento', 'pix')

    if not busca_form.is_valid() or not dados_form.is_valid():
        context = {
            'passo': 3, 'quarto': card, 'uh_id': uh.pk,
            'busca': busca_form.cleaned_data or {}, 'resumo': None,
            'dados_form': dados_form, 'config': ConfiguracaoSite.load(),
            'eh_day_use': False, 'modalidade': 'hospedagem',
        }
        if busca_form.is_valid():
            context['busca'] = busca_form.cleaned_data
            context['resumo'] = _resumo_preco_unidade(
                uh, busca_form.cleaned_data['checkin'],
                busca_form.cleaned_data['checkout'], metodo,
            )
        return render(request, 'site/reservas/dados.html', context)

    checkin = busca_form.cleaned_data['checkin']
    checkout = busca_form.cleaned_data['checkout']
    hospedes = busca_form.cleaned_data['hospedes']

    if hospedes > uh.tipo.capacidade or not reservas.uh_disponivel(uh, checkin, checkout):
        messages.error(request, 'Este quarto não está mais disponível nessas datas.')
        return redirect_busca(checkin, checkout, hospedes)

    return render(request, 'site/reservas/resumo.html', {
        'passo': 4, 'quarto': card, 'uh_id': uh.pk,
        'busca': {'checkin': checkin, 'checkout': checkout, 'hospedes': hospedes,
                  'modalidade': 'hospedagem'},
        'resumo': _resumo_preco_unidade(uh, checkin, checkout, metodo),
        'dados': dados_form.cleaned_data, 'metodo': metodo,
        'config': ConfiguracaoSite.load(), 'eh_day_use': False,
        'modalidade': 'hospedagem',
    })


def resumo_reserva(request):
    """Passo 4 — revisão da reserva antes de confirmar (sem persistir ainda)."""
    if request.method != 'POST':
        return redirect('core:reservar')

    # Venda por unidade: quando vem `uh_id`, a reserva é de um quarto específico.
    if request.POST.get('uh_id'):
        return _resumo_reserva_unidade(request)

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

    # Venda por unidade: reserva um quarto específico (não "qualquer do tipo").
    if request.POST.get('uh_id'):
        return _finalizar_reserva_unidade(request)

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


def _quarto_recibo(uh):
    """site.Quarto usado como recibo do canal para a reserva por unidade (a fonte da
    verdade é o CRM). Reaproveita o card por tipo; degrada para qualquer um."""
    return (
        Quarto.objects.filter(tipo_uh=uh.tipo).first()
        or Quarto.objects.filter(tipo_uh__modalidade='hospedagem').first()
        or Quarto.objects.first()
    )


@transaction.atomic
def _finalizar_reserva_unidade(request):
    """Cria a reserva de um quarto ESPECÍFICO (venda por unidade). Vem do passo 4."""
    from django.core.exceptions import ValidationError as VErr

    from apps.nucleo.models import UH
    from apps.reservas import services as reservas

    uh = get_object_or_404(UH, pk=request.POST.get('uh_id'), status=UH.Status.ATIVA)
    busca_form = BuscaDisponibilidadeForm({
        'checkin': request.POST.get('checkin'),
        'checkout': request.POST.get('checkout'),
        'hospedes': request.POST.get('hospedes'),
        'modalidade': 'hospedagem',
    })
    hospede_existente = encontrar_hospede(
        email=request.POST.get('email', ''), cpf=request.POST.get('cpf', ''),
    )
    dados_form = DadosHospedeForm(request.POST, instance=hospede_existente)
    metodo = request.POST.get('metodo_pagamento', 'pix')

    if not busca_form.is_valid() or not dados_form.is_valid():
        messages.error(request, 'Não foi possível concluir a reserva. Revise seus dados.')
        return redirect('core:reservar')

    checkin = busca_form.cleaned_data['checkin']
    checkout = busca_form.cleaned_data['checkout']
    hospedes = busca_form.cleaned_data['hospedes']

    if hospedes > uh.tipo.capacidade:
        messages.error(request, 'Este quarto não comporta o número de pessoas.')
        return redirect_busca(checkin, checkout, hospedes)

    hospede = dados_form.save()
    pessoa = reservas.obter_ou_criar_hospede(
        nome=hospede.nome, email=hospede.email, telefone=hospede.telefone,
        documento=getattr(hospede, 'cpf', '') or '',
    )
    nome_quarto = uh.nome_tematico or f'Quarto {uh.numero}'
    try:
        crm_reserva = reservas.criar_reserva_site_unidade(
            uh=uh, checkin=checkin, checkout=checkout,
            hospede=pessoa, usuario=_usuario_sistema(),
            adultos=hospedes, criancas=0,
            observacoes=f'Reserva pelo site — {nome_quarto} — {hospede.nome}',
        )
    except VErr as erro:
        messages.error(request, ' '.join(erro.messages))
        return redirect_busca(checkin, checkout, hospedes)

    config = ConfiguracaoSite.load()
    desconto = Decimal(config.desconto_pix) if metodo == 'pix' else Decimal('0')
    reserva = Reserva.objects.create(
        hospede=hospede, quarto=_quarto_recibo(uh),
        data_checkin=checkin, data_checkout=checkout, num_hospedes=hospedes,
        preco_noite=crm_reserva.valor_diaria, desconto_percentual=desconto,
        metodo_pagamento=metodo, status='aguardando', crm_reserva_id=crm_reserva.pk,
    )
    cobranca = _criar_cobranca_site(reserva, pessoa)
    if cobranca:
        reserva.pagamento_id = str(cobranca.token)
        reserva.save(update_fields=['pagamento_id', 'atualizado_em'])
    from apps.site.emails import enviar_confirmacao
    enviar_confirmacao(reserva)
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


def minha_reserva(request):
    """Acesso do hóspede à própria reserva — sem senha, por sobrenome + código.

    O código (VT-…) é previsível, então o sobrenome é o 2º fator: só leva ao
    recibo quem acerta os dois. Em caso de erro, mensagem genérica (não revela
    se o código existe)."""
    erro = None
    sobrenome = codigo = ''
    if request.method == 'POST':
        sobrenome = (request.POST.get('sobrenome') or '').strip()
        codigo = (request.POST.get('codigo') or '').strip().upper()
        if sobrenome and codigo:
            reserva = (
                Reserva.objects.select_related('hospede')
                .filter(codigo__iexact=codigo).first()
            )
            if reserva and sobrenome.lower() in (reserva.hospede.nome or '').lower():
                return redirect('core:minha_reserva_detalhe', token=reserva.token)
        erro = ('Não encontramos uma reserva com esse sobrenome e código. '
                'Confira e tente novamente.')
    return render(request, 'site/reservas/minha_reserva.html', {
        'erro': erro, 'sobrenome': sobrenome, 'codigo': codigo,
        'config': ConfiguracaoSite.load(),
    })


def minha_reserva_detalhe(request, token):
    """Área do hóspede — a reserva no visual dark (acesso pelo token, o segredo).

    Mesma proposta do login «Minha reserva»: código, status, datas, quarto,
    valores e pagamento se pendente. Separada do recibo do fluxo de compra."""
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
    return render(request, 'site/reservas/minha_reserva_detalhe.html', {
        'reserva': reserva, 'cobranca': cobranca,
        'config': ConfiguracaoSite.load(),
    })


# ─────────────────────────────── SEO / robôs ───────────────────────────────────

def robots_txt(request):
    """Guia os robôs: só o site público é indexável; o CRM interno fica de fora."""
    linhas = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /crm/",
        "Disallow: /hospede/",
        "Disallow: /api/",
        "Disallow: /reserva/",
        "Disallow: /minha-reserva/",
        "Disallow: /reservar/resumo/",
        "Disallow: /lab/",
        "",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(linhas), content_type="text/plain")


def llms_txt(request):
    """Resumo do site para IAs de busca (padrão llms.txt)."""
    base = request.build_absolute_uri("/").rstrip("/")
    conteudo = f"""# Pousada Vô Testa

> Pousada à beira do Lago de Itá, em Itá/SC (Alto Uruguai catarinense) — hospedagem,
> day use com piscina e mirantes, pesca esportiva e eventos. Reserva direta pelo site,
> com disponibilidade e preço em tempo real.

## Reservar
- [Reservar online]({base}/reservar/): escolha datas e tipo de quarto; reserva direta, sem comissão de OTA.
- [Minha reserva]({base}/minha-reserva/): o hóspede acompanha a própria reserva.

## Sobre
- Localização: Itá, Santa Catarina — Lago de Itá (Rio Uruguai).
- Acomodações: quartos Padrão e Intermediário, Cabanas, e "Dia na Pousada" (day use).
- Estrutura: piscina, mirantes e acesso ao lago para pesca e passeios náuticos.

## Contato
- [Pedir proposta / eventos]({base}/#contato)
"""
    return HttpResponse(conteudo, content_type="text/plain; charset=utf-8")

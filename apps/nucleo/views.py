from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AbrirCaixaForm,
    AgenciaForm,
    ConfiguracaoUHForm,
    ContaPagarReceberForm,
    EntradaLogbookForm,
    EstornoForm,
    FecharCaixaForm,
    FornecedorForm,
    FuncionarioForm,
    HospedeForm,
    LancamentoFinanceiroForm,
    MovimentoCaixaForm,
    PessoaForm,
    PosicaoCamaFormSet,
    TemporadaForm,
    TipoUHForm,
    UHForm,
)
from .models import (
    UH,
    ContaPagarReceber,
    EntradaLogbook,
    Hospede,
    LancamentoFinanceiro,
    ModuloContratado,
    MovimentoCaixa,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    estornar_movimento,
)
from .modulos import APRESENTACAO
from .areas import Area, areas_catalogo
from .permissoes import eh_gerente, requer_area, requer_gerencia

# ---------- Dashboard ----------


@login_required
def dashboard(request):
    from django.urls import NoReverseMatch, reverse

    from .modulos import Modulo

    modulos = ModuloContratado.objects.filter(ativo=True)
    if not request.user.is_superuser:
        modulos = modulos.filter(usuarios=request.user)
    modulos = sorted(
        modulos, key=lambda m: APRESENTACAO.get(m.codigo, {}).get("ordem", 999)
    )

    def _url(apres):
        nome = apres.get("url_name")
        if not nome:
            return None
        try:
            return reverse(nome)
        except NoReverseMatch:
            return None

    grupos: dict[str, list] = {}
    for m in modulos:
        apres = APRESENTACAO.get(m.codigo, {})
        grupos.setdefault(apres.get("grupo", "Outros"), []).append(
            {"nome": m.get_codigo_display(), "url": _url(apres)}
        )
    grupos_modulos = [
        {"titulo": titulo, "itens": itens} for titulo, itens in grupos.items()
    ]

    # Visão geral montada conforme o acesso do usuário — nada de outras áreas.
    hoje = timezone.localdate()
    tem_reservas = request.user.pode_acessar(Modulo.RESERVAS)
    tem_estoque = request.user.pode_acessar(Modulo.ESTOQUE)
    tem_financeiro = request.user.pode_area(Area.FINANCEIRO)
    tem_logbook = request.user.pode_area(Area.LOGBOOK)
    # Gráficos de decisão são de gestão — atendente não vê.
    tem_graficos = eh_gerente(request.user)

    indicadores: dict = {}
    atencao: list = []
    graficos: dict = {}
    resumo_reservas = None
    corredor = None
    recados_turno: list = []

    if tem_financeiro:
        contas_vencidas = ContaPagarReceber.objects.filter(
            status=ContaPagarReceber.Status.ABERTA, vencimento__lt=hoje
        ).count()
        indicadores["caixas_abertos"] = SessaoCaixa.objects.filter(
            status=SessaoCaixa.Status.ABERTA
        ).count()
        indicadores["contas_vencidas"] = contas_vencidas
        if contas_vencidas:
            atencao.append({
                "nivel": "alerta",
                "rotulo": f"{contas_vencidas} conta{'s' if contas_vencidas > 1 else ''} vencida{'s' if contas_vencidas > 1 else ''}",
                "detalhe": "a pagar/receber em atraso",
                "url": reverse("contas") + "?situacao=abertas",
            })
        if tem_graficos:
            mix = (
                MovimentoCaixa.objects.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
                .values("forma_pagamento__nome")
                .annotate(t=Sum("valor"))
                .order_by("-t")
            )
            if mix:
                graficos["pagamento"] = {
                    "labels": [m["forma_pagamento__nome"] or "—" for m in mix],
                    "valores": [float(m["t"]) for m in mix],
                }

    if tem_reservas:
        from apps.reservas.models import Reserva
        from apps.reservas.services import (
            dados_graficos,
            mapa_quartos_hoje,
            resumo_do_dia,
        )

        indicadores["uhs_ativas"] = UH.objects.filter(
            status=UH.Status.ATIVA
        ).exclude(tipo__modalidade="day_use").count()
        indicadores["total_uhs"] = UH.objects.count()
        resumo_reservas = resumo_do_dia()
        corredor = mapa_quartos_hoje(
            ler_limpeza=request.user.pode_acessar(Modulo.GOVERNANCA),
        )
        pendentes = Reserva.objects.filter(status=Reserva.Status.PRE_RESERVA).count()
        if pendentes:
            atencao.append({
                "nivel": "aviso",
                "rotulo": f"{pendentes} pré-reserva{'s' if pendentes > 1 else ''} aguardando confirmação",
                "detalhe": "confirme o sinal ou cancele",
                "url": reverse("reservas:lista") + "?status=pre_reserva",
            })
        # Saídas vencidas — o atendente finaliza (cobra e/ou fecha).
        from apps.reservas.services import saidas_vencidas

        vencidas = saidas_vencidas()
        n_saldo = len(vencidas["com_saldo"])
        n_quit = len(vencidas["quitadas"])
        if n_saldo:
            atencao.append({
                "nivel": "alerta",
                "rotulo": (
                    f"{n_saldo} saída{'s' if n_saldo > 1 else ''} vencida"
                    f"{'s' if n_saldo > 1 else ''} com saldo em aberto — "
                    f"R$ {vencidas['total_aberto']} a receber"
                ),
                "detalhe": "cobre no caixa e finalize o check-out",
                "url": reverse("reservas:lista") + "?saida=vencida_saldo",
            })
        if n_quit:
            atencao.append({
                "nivel": "aviso",
                "rotulo": (
                    f"{n_quit} saída{'s' if n_quit > 1 else ''} vencida"
                    f"{'s' if n_quit > 1 else ''} já quitada"
                    f"{'s' if n_quit > 1 else ''} — confirmar saída"
                ),
                "detalhe": "conta zerada, só finalizar o check-out",
                "url": reverse("reservas:lista") + "?saida=vencida_quitada",
            })
        if tem_graficos:
            graficos.update(dados_graficos())

    if tem_estoque:
        from .models import produtos_abaixo_minimo

        minimo = produtos_abaixo_minimo()
        indicadores["estoque_minimo"] = minimo
        if minimo:
            atencao.append({
                "nivel": "aviso",
                "rotulo": f"{minimo} produto{'s' if minimo > 1 else ''} no estoque mínimo",
                "detalhe": "repor antes de faltar",
                "url": reverse("estoque:posicao") + "?alerta=1",
            })

    if tem_logbook:
        indicadores["logbook_hoje"] = EntradaLogbook.objects.filter(
            criado_em__date=hoje
        ).count()
        recados_turno = list(EntradaLogbook.objects.select_related("autor")[:6])

    return render(
        request,
        "nucleo/dashboard.html",
        {
            "grupos_modulos": grupos_modulos,
            "indicadores": indicadores,
            "resumo_reservas": resumo_reservas,
            "corredor": corredor,
            "atencao": atencao,
            "graficos": graficos,
            "recados_turno": recados_turno,
            "tem_reservas": tem_reservas,
            "tem_financeiro": tem_financeiro,
            "tem_logbook": tem_logbook,
        },
    )


# ---------- Central de Módulos (gestão) ----------


@requer_gerencia
def modulos_central(request):
    """Catálogo dos módulos: funcionando / em construção / disponível, com
    dependências e ativação — a base do modelo 'contratado por módulo'."""
    from django.urls import NoReverseMatch, reverse

    from .modulos import DEPENDENCIAS, Modulo

    if request.method == "POST":
        codigo = request.POST.get("codigo", "")
        acao = request.POST.get("acao", "")
        if codigo in Modulo.values:
            _alternar_modulo(request, codigo, acao)
        return redirect("modulos_central")

    ativos = set(
        ModuloContratado.objects.filter(ativo=True).values_list("codigo", flat=True)
    )
    # dependentes reversos: quem depende de X
    dependentes: dict[str, list[str]] = {}
    for cod, deps in DEPENDENCIAS.items():
        for dep in deps:
            dependentes.setdefault(dep, []).append(cod)

    def tem_tela(apres):
        nome = apres.get("url_name")
        if not nome:
            return False
        try:
            reverse(nome)
            return True
        except NoReverseMatch:
            return False

    grupos: dict[str, list] = {}
    total_ativos = 0
    for codigo, apres in sorted(
        APRESENTACAO.items(), key=lambda kv: kv[1].get("ordem", 999)
    ):
        ativo = codigo in ativos
        if ativo:
            total_ativos += 1
        if ativo and tem_tela(apres):
            status = "funcionando"
        elif ativo:
            status = "construcao"
        else:
            status = "disponivel"
        bloqueia = [
            Modulo(c).label for c in dependentes.get(codigo, []) if c in ativos
        ]
        grupos.setdefault(apres.get("grupo", "Outros"), []).append({
            "codigo": codigo,
            "nome": Modulo(codigo).label,
            "descricao": apres.get("descricao", ""),
            "status": status,
            "ativo": ativo,
            "dependencias": [Modulo(c).label for c in DEPENDENCIAS.get(codigo, [])],
            "bloqueia_desativar": bloqueia,
        })

    return render(
        request,
        "nucleo/modulos_central.html",
        {
            "grupos": [
                {"titulo": t, "itens": itens} for t, itens in grupos.items()
            ],
            "total_ativos": total_ativos,
            "total": len(APRESENTACAO),
        },
    )


def _alternar_modulo(request, codigo, acao):
    from .modulos import DEPENDENCIAS, Modulo

    modulo, _ = ModuloContratado.objects.get_or_create(codigo=codigo)
    label = Modulo(codigo).label
    if acao == "ativar":
        modulo.ativo = True
        modulo.desativado_em = None
        try:
            modulo.full_clean()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return
        modulo.save()
        messages.success(request, f"Módulo {label} ativado.")
    elif acao == "desativar":
        ativos = set(
            ModuloContratado.objects.filter(ativo=True)
            .exclude(codigo=codigo)
            .values_list("codigo", flat=True)
        )
        dependentes = [
            Modulo(c).label
            for c, deps in DEPENDENCIAS.items()
            if codigo in deps and c in ativos
        ]
        if dependentes:
            messages.error(
                request,
                f"Não dá para desativar {label}: {', '.join(dependentes)} "
                "depende(m) dele.",
            )
            return
        modulo.ativo = False
        modulo.desativado_em = timezone.now()
        modulo.save()
        messages.success(request, f"Módulo {label} desativado.")


# ---------- Cadastros: pessoas ----------


PAPEL_FILTROS = {
    "hospedes": ("Hóspedes", Q(hospede__isnull=False)),
    "agencias": ("Agências/Empresas", Q(agencia__isnull=False)),
    "fornecedores": ("Fornecedores", Q(fornecedor__isnull=False)),
    "funcionarios": ("Funcionários", Q(funcionario__isnull=False)),
    "avulsos": (
        "Clientes avulsos",
        Q(hospede__isnull=True, agencia__isnull=True,
          fornecedor__isnull=True, funcionario__isnull=True),
    ),
}


@requer_area(Area.PESSOAS)
def pessoas(request):
    busca = request.GET.get("q", "").strip()
    papel = request.GET.get("papel", "")

    base = Pessoa.objects.all()
    if busca:
        base = base.filter(
            Q(nome__icontains=busca)
            | Q(documento__icontains=busca)
            | Q(email__icontains=busca)
        )

    # Contadores por papel respeitam a busca atual.
    filtros = [{"chave": "", "rotulo": "Todos", "total": base.count()}]
    for chave, (rotulo, condicao) in PAPEL_FILTROS.items():
        filtros.append(
            {"chave": chave, "rotulo": rotulo, "total": base.filter(condicao).count()}
        )

    lista = base
    if papel in PAPEL_FILTROS:
        lista = lista.filter(PAPEL_FILTROS[papel][1])

    return render(
        request,
        "nucleo/pessoas.html",
        {"pessoas": lista, "busca": busca, "papel": papel, "filtros": filtros},
    )


@login_required
def busca_global(request):
    """Busca da paleta de comandos: hóspedes, reservas e produtos."""
    from django.urls import reverse

    from .modulos import Modulo

    q = request.GET.get("q", "").strip()
    resultados = []
    if len(q) >= 2:
        for pessoa in Pessoa.objects.filter(
            Q(nome__icontains=q) | Q(documento__icontains=q)
        )[:5]:
            papeis = ", ".join(pessoa.papeis) or "Cliente avulso"
            resultados.append({
                "rotulo": pessoa.nome, "tipo": papeis,
                "url": reverse("pessoa_editar", args=[pessoa.pk]),
            })
        if request.user.pode_acessar(Modulo.RESERVAS):
            from apps.reservas.models import Reserva

            for r in Reserva.objects.select_related("hospede", "uh").filter(
                Q(hospede__nome__icontains=q) | Q(uh__numero__icontains=q)
            )[:5]:
                resultados.append({
                    "rotulo": f"Reserva #{r.pk} — {r.hospede.nome}",
                    "tipo": f"{r.uh.numero} · {r.get_status_display()}",
                    "url": reverse("reservas:detalhe", args=[r.pk]),
                })
        if request.user.pode_acessar(Modulo.ESTOQUE):
            from apps.nucleo.models import Produto

            for p in Produto.objects.filter(
                Q(nome__icontains=q) | Q(codigo_barras__icontains=q)
            )[:5]:
                resultados.append({
                    "rotulo": p.nome, "tipo": "Produto",
                    "url": reverse("estoque:produto_editar", args=[p.pk]),
                })
    return JsonResponse({"resultados": resultados})


@login_required
@require_POST
def pessoa_nova_rapida(request):
    """
    Cadastro rápido de hóspede sem sair da tela (ex.: dentro do modal de reserva).
    Só o nome é obrigatório; o resto da ficha se completa depois em Cadastros.
    Devolve JSON {id, nome} para o campo de seleção incluir e marcar a pessoa.
    """
    nome = request.POST.get("nome", "").strip()
    if not nome:
        return JsonResponse({"erro": "Informe o nome do hóspede."}, status=400)
    pessoa = Pessoa.objects.create(
        nome=nome,
        documento=request.POST.get("documento", "").strip(),
        telefone=request.POST.get("telefone", "").strip(),
        email=request.POST.get("email", "").strip(),
    )
    Hospede.objects.create(pessoa=pessoa)
    return JsonResponse({"id": pessoa.pk, "nome": pessoa.nome})


def _form_especializacao(request, form_cls, instancia, prefixo, marcado):
    """Instancia o sub-form da especialização só quando o papel está marcado."""
    if not marcado:
        return form_cls(prefix=prefixo, instance=instancia)
    return form_cls(request.POST, prefix=prefixo, instance=instancia)


@requer_area(Area.PESSOAS)
def pessoa_form(request, pk=None):
    pessoa = get_object_or_404(Pessoa, pk=pk) if pk else None
    hospede = getattr(pessoa, "hospede", None)
    agencia = getattr(pessoa, "agencia", None)
    funcionario = getattr(pessoa, "funcionario", None)
    fornecedor = getattr(pessoa, "fornecedor", None)

    if request.method == "POST":
        form = PessoaForm(request.POST, instance=pessoa)
        eh_hospede = "eh_hospede" in request.POST
        eh_agencia = "eh_agencia" in request.POST
        eh_funcionario = "eh_funcionario" in request.POST
        eh_fornecedor = "eh_fornecedor" in request.POST
        form_hospede = _form_especializacao(
            request, HospedeForm, hospede, "hospede", eh_hospede
        )
        form_agencia = _form_especializacao(
            request, AgenciaForm, agencia, "agencia", eh_agencia
        )
        form_funcionario = _form_especializacao(
            request, FuncionarioForm, funcionario, "funcionario", eh_funcionario
        )
        form_fornecedor = _form_especializacao(
            request, FornecedorForm, fornecedor, "fornecedor", eh_fornecedor
        )
        subforms_ok = (
            (not eh_hospede or form_hospede.is_valid())
            and (not eh_agencia or form_agencia.is_valid())
            and (not eh_funcionario or form_funcionario.is_valid())
            and (not eh_fornecedor or form_fornecedor.is_valid())
        )
        if form.is_valid() and subforms_ok:
            pessoa = form.save()
            for marcado, subform, existente in [
                (eh_hospede, form_hospede, hospede),
                (eh_agencia, form_agencia, agencia),
                (eh_funcionario, form_funcionario, funcionario),
                (eh_fornecedor, form_fornecedor, fornecedor),
            ]:
                if marcado:
                    obj = subform.save(commit=False)
                    obj.pessoa = pessoa
                    obj.save()
                elif existente:
                    existente.delete()
            messages.success(request, f"Cadastro de {pessoa.nome} salvo.")
            return redirect("pessoas")
    else:
        form = PessoaForm(instance=pessoa)
        form_hospede = HospedeForm(prefix="hospede", instance=hospede)
        form_agencia = AgenciaForm(prefix="agencia", instance=agencia)
        form_funcionario = FuncionarioForm(prefix="funcionario", instance=funcionario)
        form_fornecedor = FornecedorForm(prefix="fornecedor", instance=fornecedor)
        eh_hospede = hospede is not None
        eh_agencia = agencia is not None
        eh_funcionario = funcionario is not None
        eh_fornecedor = fornecedor is not None

    return render(
        request,
        "nucleo/pessoa_form.html",
        {
            "form": form,
            "pessoa": pessoa,
            "form_hospede": form_hospede,
            "form_agencia": form_agencia,
            "form_funcionario": form_funcionario,
            "form_fornecedor": form_fornecedor,
            "eh_hospede": eh_hospede,
            "eh_agencia": eh_agencia,
            "eh_funcionario": eh_funcionario,
            "eh_fornecedor": eh_fornecedor,
        },
    )


# ---------- Cadastros: estrutura (tipos de UH e UHs) ----------


@requer_area(Area.QUARTOS)
def estrutura(request):
    from apps.reservas.services import tarifa_minima_do_tipo

    from .estrutura import faixa_do_tipo

    tipos = list(TipoUH.objects.prefetch_related("uhs__posicoes_cama", "uhs__config"))
    for tipo in tipos:
        tipo.tarifa_min = tarifa_minima_do_tipo(tipo)
        tipo.faixa_lotacao = faixa_do_tipo(tipo)
    return render(
        request,
        "nucleo/estrutura.html",
        {
            "tipos": tipos,
            "uhs": UH.objects.select_related("tipo").prefetch_related(
                "posicoes_cama", "config"
            ),
        },
    )


@requer_area(Area.QUARTOS)
def tipo_uh_form(request, pk=None):
    tipo = get_object_or_404(TipoUH, pk=pk) if pk else None
    form = TipoUHForm(request.POST or None, instance=tipo)
    if request.method == "POST" and form.is_valid():
        tipo = form.save()
        messages.success(request, f"Tipo de quarto “{tipo.nome}” salvo.")
        return redirect("estrutura")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Tipo de quarto", "voltar": "estrutura"},
    )


@requer_area(Area.QUARTOS)
def uh_form(request, pk=None):
    from .estrutura import capacidade, descricao_camas
    from .models import ConfiguracaoUH

    uh = get_object_or_404(UH, pk=pk) if pk else None
    config = None
    if uh is not None:
        config, _ = ConfiguracaoUH.objects.get_or_create(uh=uh)

    form = UHForm(request.POST or None, instance=uh)
    config_form = ConfiguracaoUHForm(request.POST or None, instance=config)
    formset = PosicaoCamaFormSet(request.POST or None, instance=uh)

    if request.method == "POST":
        # Quarto novo: grava o UH primeiro para ter instância às posições/config.
        if form.is_valid():
            uh = form.save()
            config, _ = ConfiguracaoUH.objects.get_or_create(uh=uh)
            config_form = ConfiguracaoUHForm(request.POST, instance=config)
            formset = PosicaoCamaFormSet(request.POST, instance=uh)
            if config_form.is_valid() and formset.is_valid():
                config_form.save()
                formset.save()
                messages.success(request, f"Quarto {uh.numero} salvo.")
                return redirect("estrutura")

    contexto = {
        "form": form,
        "config_form": config_form,
        "formset": formset,
        "uh": uh,
        "titulo": "Quarto",
        "voltar": "estrutura",
    }
    if uh is not None:
        contexto["capacidade"] = capacidade(uh)
        contexto["descricao_camas"] = descricao_camas(uh)
    return render(request, "nucleo/uh_form.html", contexto)


# ---------- Cadastros: temporadas ----------


@requer_area(Area.TEMPORADAS)
def temporadas(request):
    return render(
        request, "nucleo/temporadas.html", {"temporadas": Temporada.objects.all()}
    )


@requer_area(Area.TEMPORADAS)
def temporada_form(request, pk=None):
    temporada = get_object_or_404(Temporada, pk=pk) if pk else None
    form = TemporadaForm(request.POST or None, instance=temporada)
    if request.method == "POST" and form.is_valid():
        temporada = form.save()
        messages.success(request, f"Temporada “{temporada.nome}” salva.")
        return redirect("temporadas")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Temporada", "voltar": "temporadas"},
    )


# ---------- Caixa ----------


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa(request):
    sessao = SessaoCaixa.objects.filter(
        operador=request.user, status=SessaoCaixa.Status.ABERTA
    ).first()
    form_abrir = AbrirCaixaForm(usuario=request.user)
    form_movimento = MovimentoCaixaForm()
    form_fechar = FecharCaixaForm()
    return render(
        request,
        "nucleo/caixa.html",
        {
            "sessao": sessao,
            "form_abrir": form_abrir,
            "form_movimento": form_movimento,
            "form_fechar": form_fechar,
            "eh_gerente": eh_gerente(request.user),
        },
    )


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_abrir(request):
    if request.method != "POST":
        return redirect("caixa")
    form = AbrirCaixaForm(request.POST, usuario=request.user)
    if form.is_valid():
        try:
            SessaoCaixa.objects.create(
                operador=request.user,
                modulo=form.cleaned_data["modulo"],
                fundo_troco=form.cleaned_data["fundo_troco"],
            )
            messages.success(request, "Caixa aberto. Bom trabalho!")
        except IntegrityError:
            messages.error(request, "Você já tem um caixa aberto neste módulo.")
    else:
        messages.error(request, "Não foi possível abrir o caixa. Confira os dados.")
    return redirect("caixa")


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_movimento(request):
    if request.method != "POST":
        return redirect("caixa")
    sessao = get_object_or_404(
        SessaoCaixa, operador=request.user, status=SessaoCaixa.Status.ABERTA
    )
    form = MovimentoCaixaForm(request.POST)
    if form.is_valid():
        movimento = form.save(commit=False)
        movimento.sessao = sessao
        movimento.criado_por = request.user
        try:
            movimento.save()
            messages.success(
                request,
                f"{movimento.get_tipo_display()} de R$ {movimento.valor} registrado.",
            )
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        erros = "; ".join(
            f"{campo}: {' '.join(msgs)}" for campo, msgs in form.errors.items()
        )
        messages.error(request, f"Movimento não registrado — {erros}")
    return redirect("caixa")


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_fechar(request):
    if request.method != "POST":
        return redirect("caixa")
    sessao = get_object_or_404(
        SessaoCaixa, operador=request.user, status=SessaoCaixa.Status.ABERTA
    )
    form = FecharCaixaForm(request.POST)
    if form.is_valid():
        sessao.observacoes_fechamento = form.cleaned_data["observacoes"]
        sessao.fechar(form.cleaned_data["valor_contado"], request.user)
        if sessao.diferenca == Decimal("0.00"):
            messages.success(request, "Caixa fechado sem diferença. 🎉")
        else:
            messages.warning(
                request,
                f"Caixa fechado com diferença de R$ {sessao.diferenca}. "
                "A gerência pode revisar na lista de sessões.",
            )
        return redirect("caixa_sessao", pk=sessao.pk)
    messages.error(request, "Informe o valor contado para fechar o caixa.")
    return redirect("caixa")


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_sessoes(request):
    """Histórico de sessões: gerência vê todas; operador, só as suas."""
    sessoes = SessaoCaixa.objects.select_related("operador")
    if not eh_gerente(request.user):
        sessoes = sessoes.filter(operador=request.user)
    return render(request, "nucleo/caixa_sessoes.html", {"sessoes": sessoes})


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_sessao(request, pk):
    sessao = get_object_or_404(SessaoCaixa.objects.select_related("operador"), pk=pk)
    if sessao.operador != request.user and not eh_gerente(request.user):
        raise PermissionDenied
    return render(
        request,
        "nucleo/caixa_sessao.html",
        {
            "sessao": sessao,
            "movimentos": sessao.movimentos.select_related("forma_pagamento"),
            "eh_gerente": eh_gerente(request.user),
            "form_estorno": EstornoForm(),
        },
    )


@requer_gerencia
def caixa_reabrir(request, pk):
    if request.method != "POST":
        return redirect("caixa_sessao", pk=pk)
    sessao = get_object_or_404(SessaoCaixa, pk=pk)
    try:
        sessao.reabrir(request.user, request.POST.get("motivo", ""))
        messages.success(request, "Sessão reaberta — operação auditada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("caixa_sessao", pk=pk)


@requer_gerencia
def estorno(request, movimento_pk):
    movimento = get_object_or_404(
        MovimentoCaixa.objects.select_related("sessao"), pk=movimento_pk
    )
    if request.method != "POST":
        return redirect("caixa_sessao", pk=movimento.sessao_id)
    form = EstornoForm(request.POST)
    if form.is_valid():
        try:
            estornar_movimento(
                movimento,
                movimento.sessao,
                request.user,
                form.cleaned_data["motivo"],
                form.cleaned_data["valor"],
            )
            messages.success(request, "Estorno registrado — operação auditada.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        messages.error(request, "Informe valor e motivo do estorno.")
    return redirect("caixa_sessao", pk=movimento.sessao_id)


# ---------- Financeiro: lançamentos e contas ----------


@requer_area(Area.FINANCEIRO)
def lancamentos(request):
    lista = LancamentoFinanceiro.objects.select_related("categoria")
    tipo = request.GET.get("tipo", "")
    if tipo in ("receita", "despesa"):
        lista = lista.filter(tipo=tipo)
    totais = {
        "receitas": lista.filter(tipo="receita").aggregate(t=Sum("valor"))["t"] or 0,
        "despesas": lista.filter(tipo="despesa").aggregate(t=Sum("valor"))["t"] or 0,
    }
    return render(
        request,
        "nucleo/lancamentos.html",
        {"lancamentos": lista[:200], "tipo": tipo, "totais": totais},
    )


@requer_area(Area.FINANCEIRO)
def lancamento_form(request):
    form = LancamentoFinanceiroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lancamento = form.save(commit=False)
        lancamento.criado_por = request.user
        lancamento.save()
        messages.success(request, "Lançamento registrado.")
        return redirect("lancamentos")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Lançamento financeiro", "voltar": "lancamentos"},
    )


@requer_area(Area.FINANCEIRO)
def contas(request):
    lista = ContaPagarReceber.objects.select_related("pessoa", "categoria")
    situacao = request.GET.get("situacao", "abertas")
    if situacao == "abertas":
        lista = lista.filter(status=ContaPagarReceber.Status.ABERTA)
    return render(
        request, "nucleo/contas.html", {"contas": lista, "situacao": situacao}
    )


@requer_area(Area.FINANCEIRO)
def conta_form(request):
    form = ContaPagarReceberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Conta registrada.")
        return redirect("contas")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Conta a pagar/receber", "voltar": "contas"},
    )


@login_required
def conta_baixar(request, pk):
    if request.method != "POST":
        return redirect("contas")
    conta = get_object_or_404(ContaPagarReceber, pk=pk)
    try:
        conta.baixar(request.user)
        messages.success(request, f"Conta “{conta.descricao}” baixada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("contas")


# ---------- Logbook ----------


@requer_area(Area.LOGBOOK)
def logbook(request):
    if request.method == "POST":
        form = EntradaLogbookForm(request.POST)
        if form.is_valid():
            entrada = form.save(commit=False)
            entrada.autor = request.user
            entrada.save()
            messages.success(request, "Ocorrência registrada no logbook.")
            return redirect("logbook")
    else:
        form = EntradaLogbookForm()
    return render(
        request,
        "nucleo/logbook.html",
        {"entradas": EntradaLogbook.objects.select_related("autor")[:100], "form": form},
    )


# ---------- Equipe & Acessos (gestão de usuários e permissões) ----------

from django.contrib.auth import get_user_model  # noqa: E402

Usuario = get_user_model()


def _usuarios_gerenciaveis():
    """Usuários reais (exclui os de sistema: _portal, _site, etc.)."""
    return Usuario.objects.exclude(username__startswith="_").order_by(
        "-is_active", "first_name", "username"
    )


@requer_area(Area.EQUIPE)
def equipe(request):
    usuarios = []
    for u in _usuarios_gerenciaveis():
        usuarios.append({
            "obj": u,
            "gerente": u.is_superuser or u.is_staff,
            "n_modulos": u.modulos.count(),
            "n_areas": len(u.areas or []),
        })
    return render(request, "nucleo/equipe.html", {"usuarios": usuarios})


@requer_area(Area.EQUIPE)
def equipe_nova(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        nome = (request.POST.get("first_name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        senha = request.POST.get("password") or ""
        if not username or not senha:
            messages.error(request, "Usuário e senha são obrigatórios.")
        elif Usuario.objects.filter(username=username).exists():
            messages.error(request, "Já existe um usuário com esse login.")
        elif len(senha) < 8:
            messages.error(request, "A senha deve ter ao menos 8 caracteres.")
        else:
            u = Usuario.objects.create_user(
                username=username, first_name=nome, email=email, password=senha
            )
            messages.success(request, f"Usuário “{u}” criado. Defina os acessos.")
            return redirect("equipe_editar", pk=u.pk)
    return render(request, "nucleo/equipe_form.html", {"modo": "novo"})


@requer_area(Area.EQUIPE)
def equipe_editar(request, pk):
    u = get_object_or_404(_usuarios_gerenciaveis(), pk=pk)
    modulos_ativos_qs = ModuloContratado.objects.filter(ativo=True).order_by("codigo")

    if request.method == "POST":
        # Trava de segurança: não rebaixar/desativar a si mesmo.
        proprio = u.pk == request.user.pk
        # Módulos
        marcados = set(request.POST.getlist("modulos"))
        u.modulos.set(modulos_ativos_qs.filter(codigo__in=marcados))
        # Áreas-core
        codigos_areas = {c for c, _ in areas_catalogo()}
        u.areas = [a for a in request.POST.getlist("areas") if a in codigos_areas]
        # Gerência e ativo (não em si mesmo)
        if not proprio:
            u.is_staff = request.POST.get("gerente") == "on"
            u.is_active = request.POST.get("ativo") == "on"
        # Senha (opcional)
        nova = request.POST.get("password") or ""
        if nova:
            if len(nova) < 8:
                messages.error(request, "A nova senha deve ter ao menos 8 caracteres.")
                return redirect("equipe_editar", pk=u.pk)
            u.set_password(nova)
        u.save()
        messages.success(request, f"Acessos de “{u}” atualizados.")
        return redirect("equipe")

    modulos = [
        {"codigo": m.codigo, "nome": m.get_codigo_display(),
         "tem": u.modulos.filter(pk=m.pk).exists()}
        for m in modulos_ativos_qs
    ]
    areas = [
        {"codigo": c, "nome": rot, "tem": c in (u.areas or [])}
        for c, rot in areas_catalogo()
    ]
    return render(request, "nucleo/equipe_form.html", {
        "modo": "editar", "u": u, "modulos": modulos, "areas": areas,
        "proprio": u.pk == request.user.pk,
        "gerente": u.is_superuser or u.is_staff,
    })

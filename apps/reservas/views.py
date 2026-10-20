from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, FormaPagamento, Pessoa, Temporada, TipoUH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .forms import (
    AcompanhanteForm,
    CancelamentoForm,
    FichaFNRHFormSet,
    GrupoForm,
    LancamentoContaForm,
    RecebimentoForm,
    ReservaForm,
    TransferenciaForm,
)
from .models import ColchoesExtra, GrupoReserva, Reserva

DIAS_MAPA = 14


# ---------- Mapa de reservas ----------


@requer_modulo(Modulo.RESERVAS)
def mapa(request):
    hoje = timezone.localdate()
    try:
        inicio = timezone.datetime.strptime(
            request.GET.get("inicio", ""), "%Y-%m-%d"
        ).date()
    except ValueError:
        inicio = hoje - timedelta(days=2)
    dias = [
        {
            "data": inicio + timedelta(days=n),
            "fim_de_semana": (inicio + timedelta(days=n)).weekday() >= 5,
            "hoje": inicio + timedelta(days=n) == hoje,
        }
        for n in range(DIAS_MAPA)
    ]
    fim = dias[-1]["data"] + timedelta(days=1)

    # Faixa de meses acima dos dias (modelo Desbravador: Julho | Agosto)
    from django.utils.formats import date_format

    meses = []
    for d in dias:
        rotulo = date_format(d["data"], "F/Y")
        if meses and meses[-1]["rotulo"] == rotulo:
            meses[-1]["span"] += 1
        else:
            meses.append({"rotulo": rotulo, "span": 1})

    reservas = (
        Reserva.objects.filter(
            status__in=Reserva.STATUS_ATIVOS,
            checkin__lt=fim,
            checkout__gt=inicio,
        )
        .select_related("hospede", "uh")
        .order_by("checkin")
    )
    por_uh: dict[int, list] = {}
    for r in reservas:
        por_uh.setdefault(r.uh_id, []).append(r)

    from apps.nucleo.models import modulo_ativo

    ultimo_dia = dias[-1]["data"]

    # Bloqueio de Manutenção POR DATAS → mapa (uh_id, dia) → motivo. Assim o quarto
    # fica indisponível só no período, e o atendente não reserva por cima.
    bloqueio_dia: dict[tuple, str] = {}
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao.services import bloqueios as _bloqueios
        for b in _bloqueios(inicio, ultimo_dia):
            d = max(b["inicio"], inicio)
            ate = min(b["fim"] or ultimo_dia, ultimo_dia)
            while d <= ate:
                bloqueio_dia[(b["uh_id"], d)] = b["motivo"]
                d += timedelta(days=1)

    # Limpeza é estado de HOJE (giro de quarto), não de datas futuras: overlay só
    # na coluna de hoje. {uh_id: 'suja'|'em_limpeza'} via Governança.
    limpeza_hoje: dict[int, str] = {}
    if modulo_ativo(Modulo.GOVERNANCA):
        from apps.governanca.services import status_por_uh
        limpeza_hoje = {
            uh_id: cod for uh_id, cod in status_por_uh().items()
            if cod in ("suja", "em_limpeza")
        }

    def linha_da_uh(uh):
        celulas = []
        dia_atual = inicio
        fila = por_uh.get(uh.pk, [])
        indice = 0
        while dia_atual < fim:
            reserva = None
            if indice < len(fila):
                r = fila[indice]
                if r.checkin <= dia_atual:
                    reserva = r
            if reserva:
                span = (min(reserva.checkout, fim) - dia_atual).days
                celulas.append({"reserva": reserva, "span": span})
                dia_atual += timedelta(days=span)
                indice += 1
            else:
                limp = limpeza_hoje.get(uh.pk) if dia_atual == hoje else None
                celulas.append(
                    {
                        "dia": dia_atual,
                        "fim_de_semana": dia_atual.weekday() >= 5,
                        "hoje": dia_atual == hoje,
                        "bloqueio": bloqueio_dia.get((uh.pk, dia_atual)),
                        "limpeza": limp,
                    }
                )
                dia_atual += timedelta(days=1)
        return {
            "uh": uh,
            "celulas": celulas,
            # Bloqueio manual do quarto inteiro (UH.status), sem janela de datas.
            "bloqueada": uh.status == UH.Status.BLOQUEADA,
        }

    # Agrupado por ALA (localização oficial), com disponibilidade por dia no
    # cabeçalho do grupo (modelo Desbravador: contagem de livres por data).
    from apps.nucleo.alas import ORDEM_ALAS

    uhs = list(UH.objects.select_related("tipo").exclude(status=UH.Status.INATIVA))
    por_ala: dict[str, dict] = {}
    for uh in uhs:  # a lista vem ordenada por número; agrupa mantendo a ordem
        chave = uh.ala or "Dia na Pousada"          # day use não tem ala
        por_ala.setdefault(chave, {"titulo": chave, "uhs": []})["uhs"].append(uh)
    # Ordem oficial das alas; "Dia na Pousada" (day use) por último.
    ordem = {nome: i for i, nome in enumerate(ORDEM_ALAS)}
    grupos = sorted(por_ala.values(), key=lambda g: ordem.get(g["titulo"], 99))

    manual_ids = {u.pk for u in uhs if u.status == UH.Status.BLOQUEADA}
    for grupo in grupos:
        ids = {u.pk for u in grupo["uhs"]}
        manual = ids & manual_ids                    # bloqueio do quarto inteiro
        disponibilidade = []
        for d in dias:
            dt = d["data"]
            reservadas = {
                r.uh_id
                for r in reservas
                if r.uh_id in ids and r.checkin <= dt < r.checkout
            }
            bloqueadas = {u for u in ids if (u, dt) in bloqueio_dia}   # manutenção por data
            indisponiveis = manual | reservadas | bloqueadas          # sem contar 2x
            livres = len(ids) - len(indisponiveis)
            disponibilidade.append({**d, "livres": livres})
        grupo["disponibilidade"] = disponibilidade
        grupo["linhas"] = [linha_da_uh(u) for u in grupo["uhs"]]

    return render(
        request,
        "reservas/mapa.html",
        {
            "grupos": grupos,
            "dias": dias,
            "meses": meses,
            "anterior": inicio - timedelta(days=7),
            "proximo": inicio + timedelta(days=7),
        },
    )


# ---------- Mapa de quartos (situação ao vivo) ----------


@requer_modulo(Modulo.RESERVAS)
def mapa_quartos(request):
    ctx = services.mapa_quartos_hoje(
        ler_limpeza=request.user.pode_acessar(Modulo.GOVERNANCA),
    )
    return render(request, "reservas/mapa_quartos.html", ctx)


# ---------- Lista e criação ----------


@requer_modulo(Modulo.RESERVAS)
def lista(request):
    reservas = Reserva.objects.select_related("hospede", "uh")
    status = request.GET.get("status", "")
    busca = request.GET.get("q", "").strip()
    saida = request.GET.get("saida", "")
    if status:
        reservas = reservas.filter(status=status)
    if busca:
        reservas = reservas.filter(
            Q(hospede__nome__icontains=busca) | Q(uh__numero__icontains=busca)
        )
    # Atalhos do painel "Precisa de atenção": saídas atrasadas por situação de conta.
    if saida in ("vencida_saldo", "vencida_quitada"):
        v = services.saidas_vencidas()
        alvo = v["com_saldo"] if saida == "vencida_saldo" else v["quitadas"]
        reservas = reservas.filter(pk__in=[r.pk for r in alvo])
    return render(
        request,
        "reservas/lista.html",
        {
            "reservas": reservas[:200],
            "status": status,
            "busca": busca,
            "saida": saida,
            "status_choices": Reserva.Status.choices,
        },
    )


@requer_modulo(Modulo.RESERVAS)
def nova(request):
    """
    Criação de reserva. Pelo mapa/lista abre em modal (HTMX): o form parcial
    é trocado dentro do diálogo; ao salvar, HX-Redirect leva ao detalhe.
    Acesso direto à URL continua servindo a página completa.
    """
    em_modal = request.headers.get("HX-Request") == "true"
    template = (
        "reservas/partials/form_modal.html" if em_modal else "reservas/reserva_form.html"
    )

    inicial = {}
    for campo in ("uh", "checkin", "checkout"):
        if request.GET.get(campo):
            inicial[campo] = request.GET[campo]

    form = ReservaForm(request.POST or None, initial=inicial)
    contexto = {
        "form": form,
        "hospedes_data": pessoas_agrupadas(),
        "titulares_data": pessoas_agrupadas(
            Pessoa.objects.filter(ativo=True, agencia__isnull=False)
        ),
    }
    if request.method == "POST" and form.is_valid():
        from apps.reservas import precos

        reserva = form.save(commit=False)
        reserva.criado_por = request.user
        reserva.criancas = form.cleaned_data.get("criancas", 0)
        # Diária sugerida pela motor de tarifa (Manual §2 — pessoa adicional, single,
        # criança 6-15 meia, não-reembolsável). A gerência pode sobrepor.
        sugerida = precos.cotacao(
            uh=reserva.uh, checkin=reserva.checkin, checkout=reserva.checkout,
            adultos=reserva.adultos, criancas_0_5=reserva.criancas_0_5,
            criancas_6_15=reserva.criancas_6_15,
            nao_reembolsavel=reserva.nao_reembolsavel,
        )["media_noite"]
        if not form.cleaned_data.get("valor_diaria"):
            reserva.valor_diaria = sugerida
        elif reserva.valor_diaria != sugerida and not eh_gerente(request.user):
            form.add_error(
                "valor_diaria",
                f"Alterar a diária (tarifa vigente: R$ {sugerida}) exige gerência.",
            )
            return render(request, template, contexto)
        # Orçamento é só cotação; reserva de verdade respeita a disponibilidade
        # (reserva ativa OU bloqueio de manutenção por datas — a constraint só pega
        # reserva×reserva, então validamos aqui também).
        if "orcamento" not in request.POST and not services.uh_disponivel(
            reserva.uh, reserva.checkin, reserva.checkout
        ):
            form.add_error(
                None,
                f"O quarto {reserva.uh.numero} não está disponível nesse período "
                "(reserva ativa ou bloqueio de manutenção).",
            )
            return render(request, template, contexto)
        if "orcamento" in request.POST:
            reserva.status = Reserva.Status.ORCAMENTO
        try:
            with transaction.atomic():
                # Trava global de colchões extra por noite (orçamento não consome pool).
                # O lock no pool serializa reservas concorrentes na mesma noite.
                if reserva.status != Reserva.Status.ORCAMENTO:
                    ColchoesExtra.atual()
                    ColchoesExtra.objects.select_for_update().first()
                    conf = services.conferir_arranjo(
                        reserva.uh, casais=reserva.casais, solteiros=reserva.solteiros,
                        usa_sofa_cama=reserva.usa_sofa_cama, adultos=reserva.adultos,
                        criancas=reserva.criancas, checkin=reserva.checkin,
                        checkout=reserva.checkout,
                    )
                    if conf["erros"]:
                        for erro in conf["erros"]:
                            form.add_error(None, erro)
                        return render(request, template, contexto)
                    for aviso in conf["avisos"]:
                        messages.warning(request, aviso)
                    # Berço (grátis, recurso global): bloqueia se não há livre na noite.
                    if reserva.usa_berco and not services.berco_disponivel(
                        reserva.checkin, reserva.checkout
                    ):
                        form.add_error(
                            None, "Não há berço disponível em alguma noite do período.")
                        return render(request, template, contexto)
                reserva.save()
        except IntegrityError:
            form.add_error(
                None,
                f"O quarto {reserva.uh.numero} já tem reserva ativa nesse período "
                "(reserva em dobro bloqueada).",
            )
            return render(request, template, contexto)
        messages.success(request, f"{reserva} criada.")
        if em_modal:
            resposta = HttpResponse(status=204)
            resposta["HX-Redirect"] = reverse("reservas:detalhe", args=[reserva.pk])
            return resposta
        return redirect("reservas:detalhe", pk=reserva.pk)
    return render(request, template, contexto)


@requer_modulo(Modulo.RESERVAS)
def tarifa_preview(request):
    """Diária vigente e temporada do período — mostrado ao vivo no modal."""
    try:
        uh = UH.objects.select_related("tipo").get(pk=request.GET.get("uh"))
        checkin = timezone.datetime.strptime(
            request.GET.get("checkin", ""), "%Y-%m-%d"
        ).date()
        checkout = timezone.datetime.strptime(
            request.GET.get("checkout", ""), "%Y-%m-%d"
        ).date()
    except (UH.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"erro": "dados incompletos"})
    if checkout <= checkin:
        return JsonResponse({"erro": "período inválido"})

    from apps.reservas import precos

    rotulos = dict(Temporada.Classificacao.choices)
    vistas, temporadas = set(), []
    dia = checkin
    while dia < checkout:
        classificacao = services.classificacao_do_dia(dia)
        if classificacao and classificacao not in vistas:
            vistas.add(classificacao)
            temporadas.append(rotulos.get(classificacao, classificacao))
        dia += timedelta(days=1)
    temporada = " + ".join(temporadas) if temporadas else "Tarifa base (fora de temporada)"
    noites = (checkout - checkin).days

    # Arranjo de camas + status do pool de colchões extra (ao vivo no modal).
    def _int(nome, padrao=None):
        try:
            return int(request.GET[nome])
        except (KeyError, ValueError, TypeError):
            return padrao

    def _bool(nome, padrao=True):
        v = request.GET.get(nome)
        return padrao if v is None else v in ("1", "true", "on")

    adultos = _int("adultos", 2)
    criancas_0_5 = _int("criancas_0_5", 0)
    criancas_6_15 = _int("criancas_6_15", 0)
    criancas = criancas_0_5 + criancas_6_15
    cobra_iss = _bool("cobra_iss", True)
    cobra_taxa_turismo = _bool("cobra_taxa_turismo", True)
    nao_reembolsavel = _bool("nao_reembolsavel", False)

    # Preço itemizado pela motor de tarifa (Manual §2 + taxas).
    cot = precos.cotacao(
        uh=uh, checkin=checkin, checkout=checkout, adultos=adultos,
        criancas_0_5=criancas_0_5, criancas_6_15=criancas_6_15,
        cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo,
        nao_reembolsavel=nao_reembolsavel)
    diaria = cot["media_noite"]

    casais_in, solteiros_in = _int("casais"), _int("solteiros")
    sofa_in = request.GET.get("sofa") in ("1", "true", "on")
    casais, solteiros, usa_sofa = services._resolver_arranjo(
        uh, casais=casais_in, solteiros=solteiros_in,
        usa_sofa_cama=(sofa_in if (casais_in is not None or solteiros_in is not None) else None),
        adultos=adultos, criancas=criancas,
    )
    conf = services.conferir_arranjo(
        uh, casais=casais, solteiros=solteiros, usa_sofa_cama=usa_sofa,
        adultos=adultos, criancas=criancas, checkin=checkin, checkout=checkout)
    if conf["erros"]:
        colchoes_status, colchoes_msg = "bloqueio", conf["erros"][0]
    elif conf["avisos"]:
        colchoes_status, colchoes_msg = "aviso", conf["avisos"][0]
    elif conf["extra"]:
        colchoes_status = "ok"
        colchoes_msg = f"{conf['extra']} colchão(ões) extra neste arranjo — há disponível."
    else:
        colchoes_status = "ok"
        colchoes_msg = "Arranjo dentro da base do quarto (não usa colchão extra)."

    return JsonResponse(
        {
            "diaria": f"{diaria:.2f}",
            "temporada": temporada,
            "noites": noites,
            "hospedagem": f"{cot['hospedagem']:.2f}",
            "iss": f"{cot['iss']:.2f}",
            "iss_aliquota": f"{cot['iss_aliquota']:.1f}",
            "taxa_turismo": f"{cot['taxa_turismo']:.2f}",
            "total": f"{cot['total']:.2f}",
            "feriado_ou_alta": bool(temporadas),
            "arranjo": {"casais": casais, "solteiros": solteiros, "sofa": usa_sofa},
            "colchoes_extra": conf["extra"],
            "colchoes_status": colchoes_status,
            "colchoes_msg": colchoes_msg,
        }
    )


# ---------- Detalhe e transições ----------


@requer_modulo(Modulo.RESERVAS)
def detalhe(request, pk):
    reserva = get_object_or_404(
        Reserva.objects.select_related("hospede", "uh", "uh__tipo"), pk=pk
    )
    conta = getattr(reserva, "conta", None)
    quartos_livres = []
    if reserva.ativa:
        quartos_livres = list(
            services.uhs_disponiveis(reserva.checkin, reserva.checkout)
            .exclude(pk=reserva.uh_id)
            .select_related("tipo")
        )

    from apps.nucleo.models import modulo_ativo

    aviso_checkin = None
    if reserva.status in (Reserva.Status.CONFIRMADA, Reserva.Status.PRE_RESERVA):
        if modulo_ativo(Modulo.GOVERNANCA):
            from apps.governanca.services import uh_pronta_para_checkin

            if not uh_pronta_para_checkin(reserva.uh):
                aviso_checkin = (
                    f"O quarto {reserva.uh.numero} não está limpo/inspecionado."
                )

    # Prévia da política de cancelamento (quanto reteria/devolveria agora).
    politica_cancel = None
    if reserva.ativa:
        from apps.reservas import cancelamento
        politica_cancel = cancelamento.resumo_cancelamento(reserva)

    return render(
        request,
        "reservas/reserva_detalhe.html",
        {
            "reserva": reserva,
            "conta": conta,
            "form_cancelamento": CancelamentoForm(),
            "form_transferencia": TransferenciaForm(),
            "form_recebimento": RecebimentoForm(),
            "form_lancamento": LancamentoContaForm(),
            "form_acompanhante": AcompanhanteForm(),
            "quartos_livres": quartos_livres,
            "politica_cancel": politica_cancel,
            "eh_gerente": eh_gerente(request.user),
            "aviso_checkin": aviso_checkin,
            "fnrh_pronta": reserva.fnrh_pronta,
            "fnrh_total": reserva.total_hospedes,
            "fnrh_completas": sum(1 for f in reserva.fichas_fnrh.all() if f.completa),
        },
    )


@requer_modulo(Modulo.RESERVAS)
def trocar_quarto(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    novo = UH.objects.filter(pk=request.POST.get("novo_uh")).first()
    ok, msg = False, "Selecione um quarto de destino."
    if novo:
        try:
            services.trocar_quarto(reserva, novo, request.user,
                                   request.POST.get("motivo", ""))
            ok = True
            msg = f"Reserva movida para {novo.numero}. A conta foi junto."
        except ValidationError as erro:
            msg = " ".join(erro.messages)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": ok, "erro": None if ok else msg})
    (messages.success if ok else messages.error)(request, msg)
    return redirect("reservas:detalhe", pk=pk)


def _acao_reserva(request, pk, acao):
    """Executa uma transição de estado e volta ao detalhe com mensagem."""
    reserva = get_object_or_404(Reserva, pk=pk)
    try:
        acao(reserva)
    except (ValidationError, IntegrityError) as erro:
        mensagens = (
            erro.messages if isinstance(erro, ValidationError) else [str(erro)]
        )
        messages.error(request, " ".join(mensagens))
    return redirect("reservas:detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def confirmar(request, pk):
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        reserva.confirmar(request.user)
        messages.success(request, "Reserva confirmada.")

    return _acao_reserva(request, pk, acao)


@requer_modulo(Modulo.RESERVAS)
def fazer_checkin(request, pk):
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        reserva.fazer_checkin(request.user)
        # Push à FNRH Digital (best-effort; não trava o check-in se a API falhar).
        services.enviar_fnrh(reserva)
        messages.success(
            request,
            "Entrada registrada — conta do quarto aberta com as diárias lançadas.",
        )

    return _acao_reserva(request, pk, acao)


@requer_modulo(Modulo.RESERVAS)
def fazer_checkout(request, pk):
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        reserva.fazer_checkout(request.user)
        messages.success(request, "Saída concluída. Boa viagem ao hóspede!")

    return _acao_reserva(request, pk, acao)


@requer_modulo(Modulo.RESERVAS)
def cancelar(request, pk):
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = CancelamentoForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Informe o motivo do cancelamento.")
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        from apps.nucleo.models import registrar_auditoria
        from apps.reservas import cancelamento

        resumo = cancelamento.resumo_cancelamento(reserva)
        nota = _nota_politica(resumo)
        reserva.cancelar(request.user, f"{form.cleaned_data['motivo']} — {nota}")
        registrar_auditoria(request.user, "politica_cancelamento", reserva, {
            "cenario": resumo["cenario"],
            "retido": str(resumo["cobranca"]),
            "devolver": str(resumo["devolver"]),
            "pago": str(resumo["pago"]),
        })
        messages.success(request, f"Reserva cancelada. {nota}")

    return _acao_reserva(request, pk, acao)


def _nota_politica(resumo) -> str:
    """Frase da política p/ o motivo/auditoria/mensagem (retém × devolve)."""
    devolver = resumo["devolver"]
    if resumo["cenario"] == "em_hospedagem":
        return (f"Saída antecipada: cobrar {resumo['dias_consumidos']} diária(s) usada(s) "
                f"+ {resumo['retencao_pct'].normalize()}% de retenção. Devolver R$ {devolver}.")
    if resumo["dentro_arrependimento"]:
        return f"Dentro do prazo de arrependimento — devolver 100% (R$ {devolver})."
    return (f"Fora do prazo: reter {resumo['retencao_pct'].normalize()}% "
            f"(R$ {resumo['retencao_valor']}). Devolver R$ {devolver}.")


@requer_modulo(Modulo.RESERVAS)
def transferir(request, pk):
    """Reagenda a reserva para novas datas (1ª opção de cancelamento)."""
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = TransferenciaForm(request.POST)
    if not form.is_valid():
        erros = "; ".join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f"Datas inválidas: {erros}")
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        services.transferir_datas(
            reserva, form.cleaned_data["checkin"], form.cleaned_data["checkout"],
            request.user)
        messages.success(
            request,
            f"Reserva reagendada para {form.cleaned_data['checkin']:%d/%m/%Y}–"
            f"{form.cleaned_data['checkout']:%d/%m/%Y} (diária recalculada).")

    return _acao_reserva(request, pk, acao)


@requer_modulo(Modulo.RESERVAS)
def no_show(request, pk):
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)

    def acao(reserva):
        reserva.marcar_no_show(request.user)
        messages.success(request, "Não comparecimento registrado.")

    return _acao_reserva(request, pk, acao)


# ---------- Conta, pagamentos, adiantamentos ----------


@requer_modulo(Modulo.RESERVAS)
def lancamento_novo(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = LancamentoContaForm(request.POST)
    if form.is_valid():
        # S-A2: desconto no folio só com gerência — evita recepcionista zerar o saldo e
        # liberar check-out sem receber (skimming). Débitos normais seguem liberados.
        if form.cleaned_data["tipo"] == "desconto" and not eh_gerente(request.user):
            messages.error(request, "Lançar desconto exige permissão de gerência.")
            return redirect("reservas:detalhe", pk=pk)
        try:
            services.lancar_na_conta(
                reserva.conta,
                form.cleaned_data["tipo"],
                form.cleaned_data["natureza"],
                form.cleaned_data["descricao"],
                form.cleaned_data["valor"],
                request.user,
            )
            messages.success(request, "Lançamento adicionado à conta.")
        except (ValidationError, Reserva.conta.RelatedObjectDoesNotExist) as erro:
            texto = (
                " ".join(erro.messages)
                if isinstance(erro, ValidationError)
                else "A conta abre na entrada (check-in)."
            )
            messages.error(request, texto)
    else:
        messages.error(request, "Confira os campos do lançamento (natureza é obrigatória).")
    return redirect("reservas:detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def pagamento_novo(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = RecebimentoForm(request.POST)
    if form.is_valid():
        try:
            services.receber_pagamento(
                reserva.conta,
                request.user,
                form.cleaned_data["forma"],
                form.cleaned_data["valor"],
                form.cleaned_data["parcelas"],
                form.cleaned_data.get("observacao", ""),
                autorizacao=form.cleaned_data.get("autorizacao", ""),
            )
            messages.success(request, "Pagamento recebido no seu caixa.")
        except (ValidationError, Reserva.conta.RelatedObjectDoesNotExist) as erro:
            texto = (
                " ".join(erro.messages)
                if isinstance(erro, ValidationError)
                else "A conta abre na entrada (check-in)."
            )
            messages.error(request, texto)
    else:
        messages.error(request, "Confira forma e valor do pagamento.")
    return redirect("reservas:detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def adiantamento_novo(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = RecebimentoForm(request.POST)
    if form.is_valid():
        try:
            services.receber_adiantamento(
                reserva,
                request.user,
                form.cleaned_data["forma"],
                form.cleaned_data["valor"],
                form.cleaned_data["parcelas"],
                autorizacao=form.cleaned_data.get("autorizacao", ""),
            )
            messages.success(request, "Adiantamento recebido no seu caixa.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        messages.error(request, "Confira forma e valor do adiantamento.")
    return redirect("reservas:detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def acompanhante_novo(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    form = AcompanhanteForm(request.POST)
    if form.is_valid():
        acompanhante = form.save(commit=False)
        acompanhante.reserva = reserva
        acompanhante.save()
        messages.success(request, f"Acompanhante {acompanhante.nome} incluído.")
    else:
        messages.error(request, "Informe o nome do acompanhante.")
    return redirect("reservas:detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def fnrh(request, pk):
    """Recepção: preenche/edita a FNRH de todos os hóspedes da reserva."""
    reserva = get_object_or_404(Reserva, pk=pk)
    services.garantir_fichas_fnrh(reserva)
    queryset = reserva.fichas_fnrh.all()

    if request.method == "POST":
        formset = FichaFNRHFormSet(request.POST, queryset=queryset)
        if formset.is_valid():
            fichas = formset.save()
            services.marcar_fichas_preenchidas(
                fichas or queryset, origem="recepcao", usuario=request.user
            )
            if reserva.fnrh_pronta:
                messages.success(request, "FNRH completa — check-in liberado.")
            else:
                messages.success(
                    request, "Fichas salvas. Ainda falta completar alguma."
                )
            return redirect("reservas:detalhe", pk=pk)
        messages.error(request, "Revise os campos destacados.")
    else:
        formset = FichaFNRHFormSet(queryset=queryset)

    fichas = list(reserva.fichas_fnrh.all())
    return render(request, "reservas/fnrh.html", {
        "reserva": reserva,
        "formset": formset,
        "modo": "recepcao",
        "fnrh_total": len(fichas),
        "fnrh_completas": sum(1 for f in fichas if f.completa),
        "fnrh_pronta": reserva.fnrh_pronta,
    })


@requer_modulo(Modulo.RESERVAS)
def fnrh_reenviar(request, pk):
    """Reenvia a reserva à FNRH Digital (após corrigir dados ou queda da API)."""
    if request.method != "POST":
        return redirect("reservas:detalhe", pk=pk)
    reserva = get_object_or_404(Reserva, pk=pk)
    if services.enviar_fnrh(reserva):
        messages.success(request, "Reserva enviada à FNRH Digital.")
    else:
        messages.error(request, f"Falha no envio à FNRH: {reserva.fnrh_erro}")
    return redirect("reservas:detalhe", pk=pk)


MESES_PT = [
    (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
    (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
    (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
]


@requer_modulo(Modulo.RESERVAS)
@requer_gerencia
def painel_colchoes(request):
    """Painel de colchões extra: usados × livres por noite num período (gerência).
    Fecha o ciclo do estoque de colchões (docs/Reservas/PLANO_ESTOQUE_COLCHOES.md §5)."""
    hoje = timezone.localdate()
    try:
        dias = int(request.GET.get("dias", 14))
    except (TypeError, ValueError):
        dias = 14
    dias = min(60, max(1, dias))
    try:
        inicio = timezone.datetime.strptime(request.GET["inicio"], "%Y-%m-%d").date()
    except (KeyError, ValueError, TypeError):
        inicio = hoje
    fim = inicio + timedelta(days=dias - 1)
    dados = services.painel_colchoes(inicio, fim)
    return render(request, "reservas/painel_colchoes.html", {
        "painel": dados,
        "inicio": inicio,
        "fim": fim,
        "dias": dias,
    })


@requer_gerencia
def boh(request):
    """Boletim de Ocupação Hoteleira (Embratur) — agregado mensal da FNRH.
    Página com os quadros + exportação CSV (?formato=csv)."""
    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano", hoje.year))
        mes = int(request.GET.get("mes", hoje.month))
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month
    mes = min(12, max(1, mes))
    dados = services.boh_mensal(ano, mes)

    if request.GET.get("formato") == "csv":
        return _boh_csv(dados)

    return render(request, "reservas/boh.html", {
        "boh": dados,
        "meses": MESES_PT,
        "anos": range(hoje.year, hoje.year - 4, -1),
        "ano": ano, "mes": mes,
    })


def _boh_csv(dados):
    import csv

    from apps.nucleo.export import sanitizar_celula
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = (
        f'attachment; filename="BOH_{dados["ano"]}_{dados["mes"]:02d}.csv"'
    )
    resp.write("﻿")  # BOM: Excel abre com acentos corretos
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Boletim de Ocupação Hoteleira", f'{dados["mes"]:02d}/{dados["ano"]}'])
    w.writerow(["Pousada Vô Testa — Itá/SC"])
    w.writerow([])
    w.writerow(["Indicador", "Valor"])
    w.writerow(["Total de hóspedes (entradas)", dados["total_hospedes"]])
    w.writerow(["Chegadas (reservas)", dados["total_chegadas"]])
    w.writerow(["UH-noites disponíveis", dados["uh_noites_disponiveis"]])
    w.writerow(["UH-noites ocupadas", dados["uh_noites_ocupadas"]])
    w.writerow(["Taxa de ocupação (%)", dados["taxa_ocupacao"]])
    w.writerow(["Permanência média (noites)", dados["permanencia_media"]])

    def bloco(titulo, itens):
        w.writerow([])
        w.writerow([titulo, "Hóspedes"])
        for nome, n in itens:
            # procedência/cidade vem do cadastro → neutraliza formula-injection no Excel.
            w.writerow([sanitizar_celula(nome), n])
        if not itens:
            w.writerow(["(sem dados)", 0])

    bloco("Procedência nacional (UF)", dados["nacional"])
    bloco("Procedência internacional (país)", dados["internacional"])
    bloco("Motivo da viagem", dados["motivo"])
    bloco("Meio de transporte", dados["transporte"])
    bloco("Sexo", dados["sexo"])
    return resp


# ---------- Reserva de grupo (reserva-mãe + filhas por quarto) ----------


@requer_modulo(Modulo.RESERVAS)
def grupos(request):
    grupos_qs = GrupoReserva.objects.select_related("titular").prefetch_related("filhas")
    return render(request, "reservas/grupos.html", {"grupos": grupos_qs[:200]})


@requer_modulo(Modulo.RESERVAS)
def grupo_novo(request):
    """Cria o bloco inteiro num modal só: titular + período + vários quartos.
    Cada quarto marcado vira uma filha (hóspede = titular; a recepção ajusta depois).
    """
    em_modal = request.headers.get("HX-Request") == "true"
    template = (
        "reservas/partials/grupo_form_modal.html" if em_modal
        else "reservas/grupo_form.html"
    )
    form = GrupoForm(request.POST or None)
    contexto = {
        "form": form,
        "titulares_data": pessoas_agrupadas(),
        "quartos": (
            UH.objects.filter(status=UH.Status.ATIVA)
            .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
            .select_related("tipo").order_by("numero")
        ),
    }
    if request.method == "POST":
        titular = Pessoa.objects.filter(pk=request.POST.get("titular") or None).first()
        uh_ids = request.POST.getlist("quartos")
        valido = form.is_valid()
        if not titular:
            form.add_error(None, "Escolha o titular (quem paga o folio).")
            valido = False
        if not uh_ids:
            form.add_error(None, "Marque ao menos um quarto para o grupo.")
            valido = False
        if valido:
            grupo = services.criar_grupo(
                rotulo=form.cleaned_data["rotulo"], titular=titular,
                checkin=form.cleaned_data["checkin"], checkout=form.cleaned_data["checkout"],
                faturamento=form.cleaned_data["faturamento"], canal=form.cleaned_data["canal"],
                observacoes=form.cleaned_data.get("observacoes", ""), usuario=request.user,
            )
            adultos = int(request.POST.get("adultos") or 2)
            criancas = int(request.POST.get("criancas") or 0)
            adicionados, conflitos = [], []
            for uh in UH.objects.filter(pk__in=uh_ids):
                try:
                    services.adicionar_quarto(
                        grupo, uh=uh, hospede=titular, usuario=request.user,
                        adultos=adultos, criancas=criancas,
                    )
                    adicionados.append(uh.numero)
                except ValidationError as erro:
                    conflitos.append(f"{uh.numero}: {' '.join(erro.messages)}")
            if adicionados:
                messages.success(
                    request,
                    f"Grupo “{grupo.rotulo}” criado com {len(adicionados)} quarto(s): "
                    f"{', '.join(adicionados)}.",
                )
            for c in conflitos:
                messages.error(request, c)
            if em_modal:
                resposta = HttpResponse(status=204)
                resposta["HX-Redirect"] = reverse("reservas:grupo_detalhe", args=[grupo.pk])
                return resposta
            return redirect("reservas:grupo_detalhe", pk=grupo.pk)
    return render(request, template, contexto)


@requer_modulo(Modulo.RESERVAS)
def grupo_detalhe(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    resumo = services.total_grupo(grupo)
    ocupados = set(
        grupo.filhas.filter(status__in=Reserva.STATUS_ATIVOS).values_list("uh_id", flat=True)
    )
    livres = [
        uh for uh in services.uhs_disponiveis(grupo.checkin, grupo.checkout)
        .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE).select_related("tipo")
        if uh.pk not in ocupados
    ]
    return render(
        request,
        "reservas/grupo_detalhe.html",
        {
            "grupo": grupo,
            "resumo": resumo,
            "quartos_livres": livres,
            "hospedes_data": pessoas_agrupadas(),
            "formas": FormaPagamento.objects.filter(ativo=True),
            "eh_gerente": eh_gerente(request.user),
        },
    )


def _grupo_redirect(pk):
    return redirect("reservas:grupo_detalhe", pk=pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_adicionar_quarto(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method != "POST":
        return _grupo_redirect(pk)
    uh = get_object_or_404(UH, pk=request.POST.get("uh") or 0)
    hospede = Pessoa.objects.filter(pk=request.POST.get("hospede") or None).first()
    if not hospede:
        messages.error(request, "Escolha o hóspede do quarto.")
        return _grupo_redirect(pk)
    try:
        services.adicionar_quarto(
            grupo, uh=uh, hospede=hospede, usuario=request.user,
            adultos=int(request.POST.get("adultos") or 2),
            criancas=int(request.POST.get("criancas") or 0),
        )
        messages.success(request, f"Quarto {uh.numero} adicionado ao grupo.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_confirmar(request, pk):
    if request.method == "POST":
        services.confirmar_grupo(pk, request.user)
        messages.success(request, "Grupo confirmado.")
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_checkin(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method == "POST":
        r = services.checkin_grupo(grupo, request.user)
        if r["entrou"]:
            messages.success(request, f"Check-in feito: {', '.join(r['entrou'])}.")
        for p in r["pendentes"]:
            messages.error(request, p)
        if not r["entrou"] and not r["pendentes"]:
            messages.info(request, "Nenhum quarto confirmado pronto para entrar.")
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_cancelar(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_grupo(grupo, request.user, request.POST.get("motivo", "").strip())
            messages.success(request, "Grupo cancelado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_remover_quarto(request, pk, reserva_pk):
    if request.method == "POST":
        reserva = get_object_or_404(Reserva, pk=reserva_pk, grupo_id=pk)
        try:
            services.remover_do_grupo(
                reserva, request.user, request.POST.get("motivo", "").strip()
            )
            messages.success(request, f"Quarto {reserva.uh.numero} removido do grupo.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_receber_folio(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method == "POST":
        form = RecebimentoForm(request.POST)
        if form.is_valid():
            try:
                services.receber_folio_grupo(
                    grupo, request.user, form.cleaned_data["forma"],
                    form.cleaned_data["valor"], form.cleaned_data.get("parcelas", 1),
                    form.cleaned_data.get("observacao", ""),
                    autorizacao=form.cleaned_data.get("autorizacao", ""),
                )
                messages.success(request, "Recebimento do folio registrado.")
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
        else:
            messages.error(request, "Confira forma e valor.")
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_encerrar(request, pk):
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method == "POST":
        try:
            services.encerrar_grupo(grupo, request.user)
            messages.success(request, "Grupo encerrado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return _grupo_redirect(pk)


@requer_modulo(Modulo.RESERVAS)
def grupo_sinal(request, pk):
    """Gera o sinal único do grupo (folio-mãe) no módulo Pagamentos."""
    grupo = get_object_or_404(GrupoReserva, pk=pk)
    if request.method != "POST":
        return _grupo_redirect(pk)
    if not request.user.pode_acessar(Modulo.PAGAMENTOS):
        messages.error(request, "Módulo Pagamentos não está disponível.")
        return _grupo_redirect(pk)
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import criar_cobranca
    try:
        valor = request.POST.get("valor", "").replace(".", "").replace(",", ".")
        cobranca = criar_cobranca(
            request.user, valor=valor, metodo=request.POST.get("metodo", Cobranca.Metodo.PIX),
            descricao=f"Sinal do grupo {grupo.rotulo}",
            finalidade=Cobranca.Finalidade.SINAL, pagador=grupo.titular, grupo_id=grupo.pk,
        )
        messages.success(request, "Sinal do grupo gerado.")
        return redirect("pagamentos:detalhe", pk=cobranca.pk)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return _grupo_redirect(pk)

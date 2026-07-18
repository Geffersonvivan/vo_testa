from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, Temporada, TipoUH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .forms import (
    AcompanhanteForm,
    CancelamentoForm,
    LancamentoContaForm,
    RecebimentoForm,
    ReservaForm,
)
from .models import Reserva

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
                celulas.append(
                    {
                        "dia": dia_atual,
                        "fim_de_semana": dia_atual.weekday() >= 5,
                        "hoje": dia_atual == hoje,
                    }
                )
                dia_atual += timedelta(days=1)
        return {"uh": uh, "celulas": celulas}

    # Agrupado por tipo de UH, com disponibilidade por dia no cabeçalho do
    # grupo (modelo Desbravador: LX (9) + contagem de livres por data).
    uhs = list(UH.objects.select_related("tipo").exclude(status=UH.Status.INATIVA))
    por_tipo: dict[int, dict] = {}
    for uh in uhs:  # a lista vem ordenada por número; agrupa mantendo a ordem
        por_tipo.setdefault(
            uh.tipo.pk, {"tipo": uh.tipo, "uhs": []}
        )["uhs"].append(uh)
    grupos = list(por_tipo.values())

    for grupo in grupos:
        ids = {u.pk for u in grupo["uhs"]}
        disponibilidade = []
        for d in dias:
            ocupadas = sum(
                1
                for r in reservas
                if r.uh_id in ids and r.checkin <= d["data"] < r.checkout
            )
            livres = len(ids) - ocupadas
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
    if status:
        reservas = reservas.filter(status=status)
    if busca:
        reservas = reservas.filter(
            Q(hospede__nome__icontains=busca) | Q(uh__numero__icontains=busca)
        )
    return render(
        request,
        "reservas/lista.html",
        {
            "reservas": reservas[:200],
            "status": status,
            "busca": busca,
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
        reserva = form.save(commit=False)
        reserva.criado_por = request.user
        sugerida = services.diaria_media(
            reserva.uh.tipo, reserva.checkin, reserva.checkout
        )
        if not form.cleaned_data.get("valor_diaria"):
            reserva.valor_diaria = sugerida
        elif reserva.valor_diaria != sugerida and not eh_gerente(request.user):
            form.add_error(
                "valor_diaria",
                f"Alterar a diária (tarifa vigente: R$ {sugerida}) exige gerência.",
            )
            return render(request, template, contexto)
        if "orcamento" in request.POST:
            reserva.status = Reserva.Status.ORCAMENTO
        try:
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

    diaria = services.diaria_media(uh.tipo, checkin, checkout)
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
    return JsonResponse(
        {
            "diaria": f"{diaria:.2f}",
            "temporada": temporada,
            "noites": noites,
            "total": f"{diaria * noites:.2f}",
            "feriado_ou_alta": bool(temporadas),
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
    frigobar_pendente = False
    if reserva.status in (Reserva.Status.CONFIRMADA, Reserva.Status.PRE_RESERVA):
        if modulo_ativo(Modulo.GOVERNANCA):
            from apps.governanca.services import uh_pronta_para_checkin

            if not uh_pronta_para_checkin(reserva.uh):
                aviso_checkin = (
                    f"O quarto {reserva.uh.numero} não está limpo/inspecionado."
                )
    if (
        reserva.status == Reserva.Status.HOSPEDADA
        and conta
        and modulo_ativo(Modulo.FRIGOBAR)
    ):
        from django.conf import settings as dj_settings

        from apps.frigobar.services import conferencia_checkout_feita

        if getattr(dj_settings, "FRIGOBAR_BLOQUEAR_CHECKOUT", True):
            frigobar_pendente = not conferencia_checkout_feita(conta=conta)

    return render(
        request,
        "reservas/reserva_detalhe.html",
        {
            "reserva": reserva,
            "conta": conta,
            "form_cancelamento": CancelamentoForm(),
            "form_recebimento": RecebimentoForm(),
            "form_lancamento": LancamentoContaForm(),
            "form_acompanhante": AcompanhanteForm(),
            "quartos_livres": quartos_livres,
            "eh_gerente": eh_gerente(request.user),
            "aviso_checkin": aviso_checkin,
            "frigobar_pendente": frigobar_pendente,
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
        reserva.cancelar(request.user, form.cleaned_data["motivo"])
        messages.success(request, "Reserva cancelada — motivo registrado.")

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

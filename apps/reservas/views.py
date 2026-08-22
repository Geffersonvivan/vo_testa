from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
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
)
from .models import GrupoReserva, Reserva

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

    # Agrupado por tipo de UH, com disponibilidade por dia no cabeçalho do
    # grupo (modelo Desbravador: LX (9) + contagem de livres por data).
    uhs = list(UH.objects.select_related("tipo").exclude(status=UH.Status.INATIVA))
    por_tipo: dict[int, dict] = {}
    for uh in uhs:  # a lista vem ordenada por número; agrupa mantendo a ordem
        por_tipo.setdefault(
            uh.tipo.pk, {"tipo": uh.tipo, "uhs": []}
        )["uhs"].append(uh)
    grupos = list(por_tipo.values())

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
    if reserva.status in (Reserva.Status.CONFIRMADA, Reserva.Status.PRE_RESERVA):
        if modulo_ativo(Modulo.GOVERNANCA):
            from apps.governanca.services import uh_pronta_para_checkin

            if not uh_pronta_para_checkin(reserva.uh):
                aviso_checkin = (
                    f"O quarto {reserva.uh.numero} não está limpo/inspecionado."
                )

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
            w.writerow([nome, n])
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

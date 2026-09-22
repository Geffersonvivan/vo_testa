"""Telas da conciliação (área Financeiro): painel + importar + conciliar + manual + fechamento."""
import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.nucleo.areas import Area
from apps.nucleo.periodos import periodo, selecao_periodo
from apps.nucleo.permissoes import requer_area

from . import services
from .models import ExtratoBancario, LancamentoExtrato, LoteCartao, TransacaoCartao


@never_cache
@requer_area(Area.FINANCEIRO)
def painel(request):
    pendentes_ext = (LancamentoExtrato.objects
                     .filter(status=LancamentoExtrato.Status.PENDENTE)
                     .select_related("extrato").order_by("data")[:100])
    pendentes_cartao = (TransacaoCartao.objects
                        .filter(status=TransacaoCartao.Status.PENDENTE)
                        .order_by("data_venda")[:100])
    return render(request, "conciliacao/painel.html", {
        "pos": services.posicao_conciliacao(),
        "pendentes_ext": pendentes_ext,
        "pendentes_cartao": pendentes_cartao,
        "extratos": ExtratoBancario.objects.all()[:8],
        "lotes": LoteCartao.objects.all()[:8],
        "atual": "conciliacao",
    })


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def importar_ofx(request):
    arquivo = request.FILES.get("arquivo")
    conta = (request.POST.get("conta") or "").strip()
    if not arquivo:
        messages.error(request, "Selecione um arquivo OFX.")
        return redirect("conciliacao:painel")
    try:
        r = services.importar_ofx(conteudo=arquivo.read(), conta=conta,
                                  arquivo_nome=arquivo.name, usuario=request.user)
        messages.success(
            request,
            f"Extrato importado: {r['novos']} novas linhas"
            + (f" ({r['ignorados']} já existiam)." if r["ignorados"] else "."))
    except Exception as e:  # noqa: BLE001 — mostra o erro ao operador
        messages.error(request, f"Falha ao importar OFX: {e}")
    return redirect("conciliacao:painel")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def importar_cartao(request):
    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        messages.error(request, "Selecione o CSV de vendas da SafraPay.")
        return redirect("conciliacao:painel")
    try:
        r = services.importar_cartao_csv(conteudo=arquivo.read(),
                                         arquivo_nome=arquivo.name, usuario=request.user)
        messages.success(request, f"Vendas importadas: {r['novos']} transações.")
    except Exception as e:  # noqa: BLE001
        messages.error(request, f"Falha ao importar CSV: {e}")
    return redirect("conciliacao:painel")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def conciliar(request):
    rb = services.conciliar_banco(usuario=request.user)
    rc = services.conciliar_cartao(usuario=request.user)
    messages.success(
        request,
        f"Conciliação concluída: {rb['conciliados']} do extrato e "
        f"{rc['conciliados']} de cartão casados automaticamente.")
    return redirect("conciliacao:painel")


# ── Conciliação manual ───────────────────────────────────────────────────────
@never_cache
@requer_area(Area.FINANCEIRO)
def manual(request):
    ext_pendentes = (LancamentoExtrato.objects
                     .filter(status=LancamentoExtrato.Status.PENDENTE)
                     .select_related("extrato").order_by("data")[:60])
    linhas_ext = [(l, services.candidatos_para_extrato(l)) for l in ext_pendentes]

    cartao_pendentes = (TransacaoCartao.objects
                        .filter(status=TransacaoCartao.Status.PENDENTE)
                        .order_by("data_venda")[:60])
    linhas_cartao = [(t, services.candidatos_para_cartao(t)) for t in cartao_pendentes]

    conciliados_ext = (LancamentoExtrato.objects
                       .filter(status=LancamentoExtrato.Status.CONCILIADO)
                       .select_related("extrato").order_by("-conciliado_em")[:30])
    conciliados_cartao = (TransacaoCartao.objects
                          .filter(status=TransacaoCartao.Status.CONCILIADO)
                          .order_by("-conciliado_em")[:30])

    return render(request, "conciliacao/manual.html", {
        "linhas_ext": linhas_ext,
        "linhas_cartao": linhas_cartao,
        "conciliados_ext": conciliados_ext,
        "conciliados_cartao": conciliados_cartao,
        "atual": "conciliacao",
    })


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def casar_extrato(request):
    lanc = get_object_or_404(LancamentoExtrato, pk=request.POST.get("lancamento"))
    escolha = (request.POST.get("escolha") or "").strip()
    if ":" not in escolha:
        messages.error(request, "Escolha um registro do CRM para casar.")
        return redirect("conciliacao:manual")
    origem, pk = escolha.split(":", 1)
    try:
        services.conciliar_manual_extrato(lancamento=lanc, origem=origem, pk=pk, usuario=request.user)
        messages.success(request, "Linha do extrato conciliada.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect("conciliacao:manual")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def ignorar_extrato(request):
    lanc = get_object_or_404(LancamentoExtrato, pk=request.POST.get("lancamento"))
    services.ignorar_extrato(lancamento=lanc, usuario=request.user)
    messages.success(request, "Linha marcada como ignorada.")
    return redirect("conciliacao:manual")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def desfazer_extrato(request):
    lanc = get_object_or_404(LancamentoExtrato, pk=request.POST.get("lancamento"))
    services.desfazer_extrato(lancamento=lanc, usuario=request.user)
    messages.success(request, "Conciliação desfeita — a linha voltou para pendente.")
    return redirect("conciliacao:manual")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def casar_cartao(request):
    t = get_object_or_404(TransacaoCartao, pk=request.POST.get("transacao"))
    escolha = (request.POST.get("escolha") or "").strip()
    mc_id = escolha.split(":", 1)[1] if ":" in escolha else escolha
    if not mc_id:
        messages.error(request, "Escolha o recebimento de caixa para casar.")
        return redirect("conciliacao:manual")
    try:
        services.conciliar_manual_cartao(transacao=t, mc_id=mc_id, usuario=request.user)
        messages.success(request, "Transação de cartão conciliada.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return redirect("conciliacao:manual")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def sem_venda_cartao(request):
    t = get_object_or_404(TransacaoCartao, pk=request.POST.get("transacao"))
    services.marcar_sem_venda_cartao(transacao=t, usuario=request.user)
    messages.success(request, "Transação marcada como sem venda no caixa.")
    return redirect("conciliacao:manual")


@never_cache
@requer_area(Area.FINANCEIRO)
@require_POST
def desfazer_cartao(request):
    t = get_object_or_404(TransacaoCartao, pk=request.POST.get("transacao"))
    services.desfazer_cartao(transacao=t, usuario=request.user)
    messages.success(request, "Conciliação de cartão desfeita.")
    return redirect("conciliacao:manual")


# ── Relatório de fechamento (mês/ano ou período) ─────────────────────────────
@never_cache
@requer_area(Area.FINANCEIRO)
def fechamento(request):
    inicio, fim, rotulo = periodo(request)
    dados = services.fechamento(inicio, fim)
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="fechamento_conciliacao_{inicio}_{fim}.csv"')
        resp.write("﻿")  # BOM p/ Excel abrir com acentos
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Fechamento de conciliação", rotulo])
        w.writerow([])
        for rot, val in dados["kpis"]:
            w.writerow([rot, val])
        return resp
    return render(request, "conciliacao/fechamento.html", {
        "dados": dados, "inicio": inicio, "fim": fim, "rotulo": rotulo,
        "atual": "conciliacao", **selecao_periodo(request),
    })

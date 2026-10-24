import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from apps.nucleo.export import resposta_csv, sanitizar_celula
from apps.nucleo.modulos import Modulo
from apps.nucleo.periodos import _mes_ano, selecao_periodo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo

from . import relatorios
from .models import ContaContabil, FechamentoMensal
from .services import plano_de_contas


def _periodo(request):
    mes, ano = _mes_ano(request)
    return ano, mes


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def painel(request):
    ano, mes = _periodo(request)
    dados_dre = relatorios.dre(ano, mes)
    fluxo = relatorios.fluxo_caixa(ano, mes)
    orf = relatorios.orfaos()
    totais = relatorios._totais_por_conta(ano, mes)
    contas = []
    for c in plano_de_contas():
        contas.append({"conta": c, "total": totais.get(c.classificacao, Decimal("0.00"))})
    fechamento = FechamentoMensal.objects.filter(ano=ano, mes=mes).first()
    from apps.nucleo.models.cadastros import folha_base
    folha = folha_base()

    # Receita futura contratada (reservas confirmadas ainda não hospedadas).
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.periodos import MESES_PT
    futura = {"total": Decimal("0.00"), "qtd": 0, "por_mes": []}
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import receita_contratada_futura
        futura = receita_contratada_futura()
        for linha in futura["por_mes"]:
            linha["rotulo"] = f"{MESES_PT[linha['mes']]}/{linha['ano']}"

    donut = [
        float(totais.get("3.1.01.03", Decimal("0.00"))),  # serviços
        float(totais.get("3.1.01.01", Decimal("0.00"))),  # mercadorias
    ]
    waterfall = {
        "labels": ["Rec. bruta", "(−) Deduções", "(−) Custos", "(−) Despesas", "Resultado"],
        "receita_bruta": float(dados_dre["receita_bruta"]),
        "receita_liquida": float(dados_dre["receita_liquida"]),
        "lucro_bruto": float(dados_dre["lucro_bruto"]),
        "resultado": float(dados_dre["resultado"]),
        "deducoes": float(dados_dre["receita_bruta"] - dados_dre["receita_liquida"]),
        "custos": float(dados_dre["receita_liquida"] - dados_dre["lucro_bruto"]),
        "despesas": float(dados_dre["lucro_bruto"] - dados_dre["resultado"]),
    }
    return render(request, "contabil/painel.html", {
        "ano": ano, "mes": mes, "dre": dados_dre, "fluxo": fluxo,
        "orfaos": orf, "contas": contas, "fechamento": fechamento,
        "donut": donut, "waterfall": waterfall, "folha_cadastro": folha,
        "futura": futura,
        **selecao_periodo(request),
    })


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def fechar(request):
    if request.method != "POST":
        return redirect(reverse("contabil:painel"))

    hoje = timezone.localdate()

    def _int(campo, padrao):
        try:
            return int(request.POST.get(campo) or padrao)
        except (TypeError, ValueError):
            return padrao

    ano = _int("ano", hoje.year)
    mes = _int("mes", hoje.month)

    def _dec(campo):
        try:
            return Decimal((request.POST.get(campo) or "0").replace(",", "."))
        except (InvalidOperation, AttributeError):
            return Decimal("0")

    fm, _ = FechamentoMensal.objects.get_or_create(ano=ano, mes=mes)
    fm.folha = _dec("folha")
    fm.encargos = _dec("encargos")
    fm.pro_labore = _dec("pro_labore")
    fm.das = _dec("das")
    fm.observacao = request.POST.get("observacao", "")[:200]
    fm.fechado_por = request.user
    fm.save()
    fm.aplicar()
    messages.success(request, f"Fechamento de {mes:02d}/{ano} aplicado à DRE.")
    return redirect(f"{reverse('contabil:painel')}?ano={ano}&mes={mes}#fechar")


@csrf_exempt
def cron_capturar(request):
    """
    Cron financeiro (a DRE se atualiza sozinha). Sem login: autenticado por token
    compartilhado (`CONTABIL_CRON_TOKEN`), para um agendador externo (GitHub Action /
    Railway cron / pinger) chamar. Idempotente — pode rodar quantas vezes quiser.
    Faz: (1) capturas automáticas do mês corrente (+ mês anterior nos primeiros dias,
    p/ fechar a competência que virou); (2) geração das contas recorrentes do mês
    corrente (contas fixas; não retroage).
    """
    token = getattr(settings, "CONTABIL_CRON_TOKEN", "")
    if not token:
        raise Http404("Cron de capturas desativado (sem CONTABIL_CRON_TOKEN).")
    fornecido = request.headers.get("X-Cron-Token") or request.GET.get("token", "")
    if not constant_time_compare(fornecido, token):
        return HttpResponseForbidden("token inválido")

    from apps.nucleo.models.financeiro import ContaRecorrente

    from .capturas import capturar_mes

    hoje = timezone.localdate()
    meses = [(hoje.year, hoje.month)]
    if hoje.day <= 5:  # começo do mês: finaliza a competência do mês anterior
        anterior = hoje.replace(day=1) - timedelta(days=1)
        meses.append((anterior.year, anterior.month))

    capturas = {}
    for ano, mes in meses:
        capturas[f"{ano:04d}-{mes:02d}"] = capturar_mes(ano, mes)

    # Contas fixas do mês corrente (idempotente). NÃO retroage — uma recorrência
    # não deve criar título de mês passado em que talvez nem existisse.
    recorrentes = 0
    for rec in ContaRecorrente.objects.filter(ativo=True):
        existia = rec.titulos.filter(
            competencia=f"{hoje.year:04d}-{hoje.month:02d}"
        ).exists()
        rec.gerar(hoje.year, hoje.month)
        if not existia:
            recorrentes += 1

    return JsonResponse({"ok": True, "capturas": capturas, "recorrentes_criadas": recorrentes})


EXPORTS = {"resumo", "lancamentos", "plano"}


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def export(request, tipo):
    if tipo not in EXPORTS:
        raise Http404("Export indisponível.")
    ano, mes = _periodo(request)
    resp = resposta_csv(f"contabil_{tipo}_{ano:04d}-{mes:02d}.csv")
    w = csv.writer(resp, delimiter=";")

    if tipo == "plano":
        w.writerow(["Codigo contador", "Classificacao", "Nome", "Grupo", "Tipo"])
        for c in plano_de_contas():
            w.writerow([sanitizar_celula(x) for x in (
                c.codigo_contador or "", c.classificacao, c.nome,
                c.get_grupo_display(), c.get_tipo_display())])
    elif tipo == "resumo":
        totais = relatorios._totais_por_conta(ano, mes)
        w.writerow(["Codigo contador", "Classificacao", "Nome", "Saldo do mes"])
        for c in plano_de_contas().filter(tipo=ContaContabil.Tipo.ANALITICA):
            w.writerow([sanitizar_celula(x) for x in (
                c.codigo_contador or "", c.classificacao, c.nome,
                totais.get(c.classificacao, Decimal("0.00")))])
    else:  # lancamentos
        from apps.nucleo.models.financeiro import LancamentoFinanceiro
        ini, fim = relatorios.periodo(ano, mes)
        w.writerow(["Data", "Historico", "Valor", "Conta contabil", "Centro", "Origem"])
        for lanc in LancamentoFinanceiro.objects.filter(data__range=(ini, fim)).order_by("data"):
            w.writerow([sanitizar_celula(x) for x in (
                lanc.data.isoformat(), lanc.descricao, lanc.valor,
                lanc.conta_contabil, lanc.centro, lanc.origem)])
    return resp

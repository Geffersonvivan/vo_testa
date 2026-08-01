import json

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.models import Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .gateways import get_gateway, status_credenciais
from .models import Cobranca, EventoPagamento


def _reservas_para_sinal(request):
    if not request.user.pode_acessar(Modulo.RESERVAS):
        return []
    from apps.reservas.services import pendentes_de_sinal
    return pendentes_de_sinal()


@never_cache
@requer_modulo(Modulo.PAGAMENTOS)
def painel(request):
    return render(request, "pagamentos/painel.html", {
        "cobrancas": Cobranca.objects.select_related("pagador")[:60],
        "pagadores": pessoas_agrupadas(),
        "metodos": Cobranca.Metodo.choices,
        "finalidades": Cobranca.Finalidade.choices,
        "reservas": _reservas_para_sinal(request),
        "conciliacao": services.conciliacao(),
        "safrapay": status_credenciais(),
    })


@never_cache
@requer_modulo(Modulo.PAGAMENTOS)
def conciliacao(request):
    """Recebimentos × banco: o que entrou, quanto o banco liquidou (líquido/taxa)
    e o que ainda falta cair na conta — base pra bater com o extrato."""
    from datetime import date, datetime

    def _data(param):
        v = (request.GET.get(param) or "").strip()
        try:
            return datetime.strptime(v, "%Y-%m-%d").date() if v else None
        except ValueError:
            return None

    hoje = timezone.localdate()
    inicio = _data("inicio") or hoje.replace(day=1)
    fim = _data("fim") or hoje
    metodo = request.GET.get("metodo", "")
    status = request.GET.get("status", Cobranca.Status.PAGO)
    liquidacao = request.GET.get("liquidacao", "")

    cobrancas, totais = services.recebimentos(
        inicio=inicio, fim=fim, metodo=metodo, status=status, liquidacao=liquidacao,
    )
    return render(request, "pagamentos/conciliacao.html", {
        "cobrancas": cobrancas, "totais": totais,
        "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "metodo": metodo, "status": status, "liquidacao": liquidacao,
        "metodos": Cobranca.Metodo.choices, "status_choices": Cobranca.Status.choices,
        "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def liquidar(request, pk):
    """Marca uma cobrança paga como liquidada no banco (conferência do extrato)."""
    cobranca = get_object_or_404(Cobranca, pk=pk)
    valor_liquido = (request.POST.get("valor_liquido") or "").replace(",", ".").strip() or None
    data_raw = (request.POST.get("data_liquidacao") or "").strip() or None
    from datetime import date
    data_liq = None
    if data_raw:
        try:
            data_liq = date.fromisoformat(data_raw)
        except ValueError:
            data_liq = None
    try:
        services.registrar_liquidacao(
            cobranca, valor_liquido=valor_liquido,
            data_liquidacao=data_liq or timezone.localdate(),
            id_liquidacao=(request.POST.get("id_liquidacao") or "").strip(),
            origem="conferencia_manual",
        )
        messages.success(request, "Cobrança marcada como liquidada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:conciliacao")


@never_cache
@requer_modulo(Modulo.PAGAMENTOS)
def safrapay(request):
    """Checklist das chaves Safrapay e próximos passos (sem expor segredos)."""
    return render(request, "pagamentos/safrapay.html", {
        "safrapay": status_credenciais(),
    })


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def safrapay_evidencias(request):
    """Gera cobranças sandbox (Pix/cartão/boleto) + JSON no formato API HML."""
    from django.http import HttpResponse

    from .homologacao import gerar_evidencias

    try:
        pacote = gerar_evidencias(request.user)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("pagamentos:safrapay")
    messages.success(
        request,
        f"Evidências geradas: cobranças "
        f"#{pacote['cobrancas_sandbox_crm'][0]['id']}, "
        f"#{pacote['cobrancas_sandbox_crm'][1]['id']}, "
        f"#{pacote['cobrancas_sandbox_crm'][2]['id']} "
        f"(Pix, cartão, boleto). JSON salvo em evidencias/safrapay/ — "
        f"coloque os prints em evidencias/safrapay/prints/.",
    )
    body = json.dumps(pacote, ensure_ascii=False, indent=2)
    resp = HttpResponse(body, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = (
        'attachment; filename="safrapay-evidencias-homologacao.json"'
    )
    return resp


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def criar(request):
    pagador = Pessoa.objects.filter(pk=request.POST.get("pagador") or None).first()
    try:
        cobranca = services.criar_cobranca(
            request.user,
            valor=request.POST.get("valor"),
            metodo=request.POST.get("metodo"),
            descricao=request.POST.get("descricao", "").strip(),
            finalidade=request.POST.get("finalidade") or Cobranca.Finalidade.AVULSO,
            pagador=pagador,
            reserva_id=request.POST.get("reserva_id") or None,
            parcelas=request.POST.get("parcelas") or 1,
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("pagamentos:painel")
    return redirect("pagamentos:detalhe", pk=cobranca.pk)


@requer_modulo(Modulo.PAGAMENTOS)
def detalhe(request, pk):
    cobranca = get_object_or_404(
        Cobranca.objects.select_related("pagador", "criado_por").prefetch_related("eventos"), pk=pk
    )
    return render(request, "pagamentos/detalhe.html", {
        "cobranca": cobranca, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def simular(request, pk):
    """Simula o webhook do gateway confirmando o pagamento (sandbox)."""
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.confirmar_pagamento(cobranca, request.user, origem="simulado")
        messages.success(request, "Pagamento confirmado (sandbox).")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


@requer_modulo(Modulo.PAGAMENTOS)
@require_POST
def cancelar(request, pk):
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.cancelar(cobranca, request.user)
        messages.success(request, "Cobrança cancelada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


@requer_gerencia
@require_POST
def estornar(request, pk):
    cobranca = get_object_or_404(Cobranca, pk=pk)
    try:
        services.estornar(cobranca, request.user)
        messages.success(request, "Cobrança estornada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("pagamentos:detalhe", pk=pk)


# ───────── Público (link de pagamento) + webhook do gateway ─────────

def pagar(request, token):
    """Página pública do link de pagamento (sem login)."""
    cobranca = get_object_or_404(Cobranca, token=token)
    sandbox = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado") == "simulado"
    return render(request, "pagamentos/pagar.html", {
        "cobranca": cobranca,
        "url_recibo_site": _url_recibo_site(cobranca),
        "sandbox": sandbox,
    })


@require_POST
def pagar_simular(request, token):
    """Botão 'já paguei' da página pública.

    Sandbox (gateway simulado): confirma direto. Gateway REAL: consulta o status
    verdadeiro no provedor e só confirma se estiver pago de fato — nunca confirma
    no escuro (o webhook não chega em localhost, daí a consulta ativa)."""
    cobranca = get_object_or_404(Cobranca, token=token)
    gateway = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado")
    if gateway == "simulado":
        try:
            services.confirmar_pagamento(cobranca, cobranca.criado_por, origem="link_publico")
        except ValidationError:
            pass
    elif cobranca.status == Cobranca.Status.PENDENTE:
        try:
            gw = get_gateway()
            info = gw.consultar_status(cobranca) if hasattr(gw, "consultar_status") else {}
            status_raw = info.get("status_raw")
            EventoPagamento.objects.create(
                cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
                origem="consulta", detalhe={"status_raw": status_raw},
            )
            if _status_pago(status_raw) is True:
                services.confirmar_pagamento(cobranca, cobranca.criado_por, origem="link_publico")
            else:
                messages.info(
                    request,
                    "Ainda não identificamos seu pagamento. Assim que o banco "
                    "confirmar, a reserva é atualizada automaticamente.",
                )
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    cobranca.refresh_from_db()
    # Sinal do site: leva o hóspede de volta ao recibo da reserva.
    destino = _url_recibo_site(cobranca)
    if destino and cobranca.status == Cobranca.Status.PAGO:
        return redirect(destino)
    return redirect("pagamentos:pagar", token=token)


def _url_recibo_site(cobranca):
    """URL da confirmação no site, se a cobrança for sinal de uma reserva do canal."""
    if cobranca.finalidade != Cobranca.Finalidade.SINAL:
        return None
    try:
        from django.urls import reverse
        from apps.site.models import Reserva as SiteReserva
    except Exception:
        return None
    recibo = None
    if cobranca.reserva_id:
        recibo = SiteReserva.objects.filter(crm_reserva_id=cobranca.reserva_id).first()
    if not recibo:
        recibo = SiteReserva.objects.filter(pagamento_id=str(cobranca.token)).first()
    if not recibo:
        return None
    return reverse("core:reserva_confirmada", args=[recibo.token])


# Mapa de status do webhook — alinhado à enum TransactionStatus da Aditum/SafraPay:
#   1=PreAuthorized · 2=Captured · 3=Denied · 4=Pending · 5=Canceled · 8=Paid
# Conservador por segurança: só confirmamos em estados inequívocos de pago
# (Captured/Paid). Negado/cancelado/desconhecido NÃO confirma (fail-safe) —
# fica pendente p/ conciliação. Confirmar o campo/valores exatos na homologação.
# Sandbox envia sem status → confirma (st = None).
_STATUS_PAGO = {
    "paid", "pago", "captured", "consolidated",
    "2", "8",
}
_STATUS_PENDENTE = {
    "pending", "pendente", "ordered", "created",
    "preauthorized", "pre_authorized", "authorized",
    "pendingpayment", "pending_payment",
    "1", "4",
}


def _status_pago(status_raw):
    """True = pago, False = pendente, None = desconhecido (fail-safe: não confirma)."""
    if status_raw is None or status_raw == "":
        return None
    st = str(status_raw).lower()
    if st in _STATUS_PAGO:
        return True
    if st in _STATUS_PENDENTE:
        return False
    return None


@csrf_exempt
@require_POST
def webhook(request):
    """Endpoint do gateway (simulado form ou JSON SafraPay). Idempotente."""
    gid, status_gw, body = _extrair_webhook(request)
    cobranca = Cobranca.objects.filter(gateway_id=gid).first() if gid else None
    if not cobranca:
        return _json({"erro": "cobrança não encontrada"}, 404)
    EventoPagamento.objects.create(
        cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
        origem="webhook", detalhe={"gateway_id": gid, "status": status_gw, "body": body},
    )
    # Notificação de liquidação (o dinheiro caiu na conta) pode vir junto do
    # pagamento ou num webhook próprio, depois. Se a cobrança já está paga,
    # registramos a liquidação e encerramos.
    liq = _extrair_liquidacao(body)
    if liq and cobranca.status == Cobranca.Status.PAGO:
        try:
            services.registrar_liquidacao(cobranca, origem="webhook", **liq)
        except ValidationError as erro:
            return _json({"erro": " ".join(erro.messages)}, 400)
        cobranca.refresh_from_db()
        return _json({"ok": True, "status": cobranca.status, "liquidado": cobranca.liquidado})

    st = str(status_gw).lower() if status_gw is not None else None
    if st in _STATUS_PENDENTE:
        return _json({"ok": True, "status": cobranca.status, "ignorado": "ainda pendente"})
    # Fail-safe: só confirma em status inequívoco de pago. "Sem status" confirma
    # apenas no sandbox (simulado não envia status); um webhook real sem status
    # reconhecido fica pendente p/ conciliação — nunca confirma no escuro.
    if st is None:
        if getattr(settings, "PAGAMENTOS_GATEWAY", "simulado") != "simulado":
            return _json({"ok": True, "status": cobranca.status, "ignorado": "status ausente (não confirma fora do sandbox)"})
    elif st not in _STATUS_PAGO:
        return _json({"ok": True, "status": cobranca.status, "ignorado": f"status={status_gw}"})
    try:
        services.confirmar_pagamento(cobranca, cobranca.criado_por, origem="webhook")
        # Pix liquida na hora: se a mesma notificação já traz os dados, registra.
        if liq:
            services.registrar_liquidacao(cobranca, origem="webhook", **liq)
    except ValidationError as erro:
        return _json({"erro": " ".join(erro.messages)}, 400)
    cobranca.refresh_from_db()
    return _json({"ok": True, "status": cobranca.status, "liquidado": cobranca.liquidado})


def _extrair_liquidacao(body):
    """Extrai dados de liquidação bancária do payload, se houver.

    Os nomes exatos dos campos do Safrapay/Aditum são confirmados na homologação
    (settlement/relatório de vendas). Aqui aceitamos os candidatos mais comuns e
    normalizamos valores em centavos → reais. Devolve dict pronto p/
    registrar_liquidacao, ou None se o payload não trouxer liquidação."""
    from datetime import date
    from decimal import Decimal, InvalidOperation

    if not isinstance(body, dict):
        return None
    charge = body.get("charge") if isinstance(body.get("charge"), dict) else {}
    txs = charge.get("transactions") if isinstance(charge.get("transactions"), list) else []
    tx0 = txs[0] if txs else {}
    fontes = [body, charge, tx0]

    def _busca(*chaves):
        for fonte in fontes:
            for ch in chaves:
                if isinstance(fonte, dict) and fonte.get(ch) not in (None, ""):
                    return fonte[ch]
        return None

    def _dinheiro(v):
        # Safrapay usa centavos inteiros (como no amount que enviamos). Regra:
        # inteiro ou string só-dígitos → centavos (÷100); com ponto → já em reais.
        if v is None:
            return None
        try:
            if isinstance(v, int) or (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
                return (Decimal(str(v)) / 100).quantize(Decimal("0.01"))
            return Decimal(str(v))
        except (InvalidOperation, ValueError):
            return None

    liquido = _dinheiro(_busca("netAmount", "settlementAmount", "liquidAmount", "valorLiquido"))
    taxa = _dinheiro(_busca("feeAmount", "mdrAmount", "fee", "taxa", "valorTaxa"))
    id_liq = _busca("settlementId", "batchId", "liquidationId", "idLiquidacao")
    data_raw = _busca("settlementDate", "liquidationDate", "paymentDate", "dataLiquidacao")

    if liquido is None and taxa is None and not id_liq and not data_raw:
        return None  # payload não fala de liquidação

    data_liq = None
    if data_raw:
        try:
            data_liq = date.fromisoformat(str(data_raw)[:10])
        except ValueError:
            data_liq = None
    return {
        "valor_liquido": liquido,
        "taxa": taxa,
        "data_liquidacao": data_liq,
        "id_liquidacao": str(id_liq) if id_liq else "",
    }


def _extrair_webhook(request):
    """Aceita form (sandbox) ou JSON SafraPay com charge.id / status."""
    gid = request.POST.get("gateway_id") or request.GET.get("gateway_id")
    status_gw = request.POST.get("status") or request.GET.get("status")
    body = {}
    ctype = request.content_type or ""
    if "json" in ctype:
        try:
            raw = (request.body or b"").strip()
        except Exception:
            raw = b""
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            charge = body.get("charge") if isinstance(body, dict) else None
            if not isinstance(charge, dict):
                charge = body if isinstance(body, dict) else {}
            gid = gid or str(
                charge.get("id") or body.get("gateway_id") or body.get("id") or ""
            )
            # Safrapay real usa chargeStatus/transactionStatus (não "status").
            tx0 = (charge.get("transactions") or [{}])[0] if isinstance(charge.get("transactions"), list) else {}
            status_gw = (
                status_gw
                or charge.get("status")
                or charge.get("chargeStatus")
                or tx0.get("transactionStatus")
                or body.get("status")
            )
            if isinstance(status_gw, dict):
                status_gw = status_gw.get("name") or status_gw.get("value")
    return gid or None, status_gw, body


def _json(data, status=200):
    from django.http import JsonResponse
    return JsonResponse(data, status=status)

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.nucleo.models import Pessoa, Prospecto, modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .forms import ConversaoForm, CotacaoForm, MetaForm, PerdaForm
from .models import AtividadeComercial, EtapaFunil, MotivoPerda, Oportunidade
from .proposta_instagram import PROPOSTA as PROPOSTA_INSTAGRAM

Usuario = get_user_model()


def _valor(txt):
    if txt in (None, ""):
        return None
    s = str(txt).strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _data(txt):
    if not txt:
        return None
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


def _contexto_form():
    return {
        "pessoas_data": pessoas_agrupadas(Pessoa.objects.filter(ativo=True)),
        "etapas": services.etapas(),
        "faturamentos": Oportunidade.Faturamento.choices,
        "origens": Oportunidade.Origem.choices,
        "responsaveis": Usuario.objects.filter(is_active=True).order_by(
            "first_name", "username"),
        "motivos_perda": MotivoPerda.objects.filter(ativo=True),
    }


def _conversao_inicial(op):
    initial = {}
    cot = op.ultima_cotacao
    if cot:
        initial.update({
            "tipo_uh": cot.tipo_uh_id,
            "checkin": cot.checkin,
            "checkout": cot.checkout,
            "valor_diaria": cot.valor_diaria,
        })
    else:
        if op.checkin_previsto:
            initial["checkin"] = op.checkin_previsto
        if op.checkout_previsto:
            initial["checkout"] = op.checkout_previsto
        if (op.valor_estimado and op.checkin_previsto and op.checkout_previsto
                and op.checkout_previsto > op.checkin_previsto):
            noites = (op.checkout_previsto - op.checkin_previsto).days
            if noites and op.quartos:
                initial["valor_diaria"] = (
                    op.valor_estimado / noites / op.quartos
                ).quantize(Decimal("0.01"))
    return ConversaoForm(initial=initial)


def _cotacao_inicial(op):
    initial = {}
    if op.checkin_previsto:
        initial["checkin"] = op.checkin_previsto
    if op.checkout_previsto:
        initial["checkout"] = op.checkout_previsto
    return CotacaoForm(initial=initial)


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def funil(request):
    fat = request.GET.get("fat", "")
    colunas = services.dados_kanban(faturamento=fat)
    itens = [op for col in colunas for op in col["itens"]]
    ctx = {
        "colunas": colunas,
        "fat": fat,
        "faturamento_filtros": Oportunidade.Faturamento.choices,
        "valor_total": sum((c["total"] for c in colunas), Decimal("0.00")),
        "ponderado_total": sum((o.valor_ponderado for o in itens), Decimal("0.00")),
        "qtd_total": len(itens),
    }
    ctx.update(_contexto_form())
    return render(request, "comercial/funil.html", ctx)


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def instagram(request):
    """Proposta Instagram → Comercial (ainda não implementada)."""
    return render(
        request,
        "comercial/instagram.html",
        {"proposta": PROPOSTA_INSTAGRAM},
    )


@requer_modulo(Modulo.COMERCIAL)
def nova(request):
    if request.method != "POST":
        return redirect("comercial:funil")
    pessoa = Pessoa.objects.filter(pk=request.POST.get("pessoa") or None).first()
    if not pessoa:
        messages.error(request, "Selecione o lead (pessoa/agência/empresa).")
        return redirect("comercial:funil")
    responsavel = (Usuario.objects.filter(pk=request.POST.get("responsavel") or None).first()
                   or request.user)
    etapa = EtapaFunil.objects.filter(pk=request.POST.get("etapa") or None).first()
    try:
        op = services.criar_oportunidade(
            usuario=request.user, pessoa=pessoa,
            titulo=request.POST.get("titulo", "").strip() or f"Oportunidade — {pessoa.nome}",
            etapa=etapa,
            faturamento=request.POST.get("faturamento") or Oportunidade.Faturamento.PARTICULAR,
            origem=request.POST.get("origem") or Oportunidade.Origem.OUTRO,
            valor_estimado=_valor(request.POST.get("valor_estimado")) or Decimal("0.00"),
            checkin_previsto=_data(request.POST.get("checkin_previsto")),
            checkout_previsto=_data(request.POST.get("checkout_previsto")),
            quartos=int(request.POST.get("quartos") or 1),
            hospedes=int(request.POST.get("hospedes") or 2),
            responsavel=responsavel,
            observacao=request.POST.get("observacao", ""),
        )
    except (ValidationError, ValueError) as erro:
        msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Dados inválidos."
        messages.error(request, msg)
        return redirect("comercial:funil")
    messages.success(request, "Oportunidade criada.")
    return redirect("comercial:oportunidade", pk=op.pk)


@requer_modulo(Modulo.COMERCIAL)
def lead_novo(request):
    if request.method != "POST":
        return JsonResponse({"erro": "Método inválido."}, status=405)
    nome = request.POST.get("nome", "").strip()
    if not nome:
        return JsonResponse({"erro": "Informe o nome do lead."}, status=400)
    pessoa = Pessoa.objects.create(
        nome=nome,
        documento=request.POST.get("documento", "").strip(),
        telefone=request.POST.get("telefone", "").strip(),
        email=request.POST.get("email", "").strip(),
    )
    Prospecto.objects.create(pessoa=pessoa)
    return JsonResponse({"id": pessoa.pk, "nome": pessoa.nome, "grupo": "Prospecção"})


@requer_modulo(Modulo.COMERCIAL)
def mover(request, pk):
    oportunidade = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        etapa = get_object_or_404(EtapaFunil, pk=request.POST.get("etapa"))
        motivo = MotivoPerda.objects.filter(pk=request.POST.get("motivo") or None).first()
        try:
            services.mover_etapa(oportunidade, etapa, request.user, motivo=motivo)
            messages.success(request, f"Movida para '{etapa.nome}'.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    destino = request.POST.get("next", "")
    if destino.startswith("/crm/"):
        return redirect(destino)
    return redirect("comercial:funil")


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def oportunidade(request, pk):
    op = get_object_or_404(
        Oportunidade.objects.select_related("pessoa", "etapa", "responsavel", "motivo_perda"),
        pk=pk,
    )
    return render(request, "comercial/oportunidade.html", {
        "op": op,
        "atividades": op.atividades.select_related("responsavel"),
        "cotacoes": op.cotacoes.select_related("tipo_uh"),
        "tipos_atividade": AtividadeComercial.Tipo.choices,
        "etapas": [e for e in services.etapas() if e.tipo == EtapaFunil.Tipo.ABERTA],
        "conversao_form": _conversao_inicial(op),
        "cotacao_form": _cotacao_inicial(op),
        "perda_form": PerdaForm(),
        "templates": services.templates_mensagem(op),
        "pagamentos_ativo": modulo_ativo(Modulo.PAGAMENTOS),
        "responsaveis": Usuario.objects.filter(is_active=True).order_by(
            "first_name", "username"),
    })


@requer_modulo(Modulo.COMERCIAL)
def atividade(request, pk):
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        responsavel = Usuario.objects.filter(pk=request.POST.get("responsavel") or None).first()
        try:
            services.registrar_atividade(
                oportunidade=op, usuario=request.user,
                tipo=request.POST.get("tipo") or AtividadeComercial.Tipo.NOTA,
                descricao=request.POST.get("descricao", "").strip(),
                quando=_datahora(request.POST.get("quando")),
                concluida=request.POST.get("concluida") != "0",
                responsavel=responsavel,
            )
            messages.success(request, "Atividade registrada.")
        except (ValidationError, ValueError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Dados inválidos."
            messages.error(request, msg)
    return redirect("comercial:oportunidade", pk=pk)


@requer_modulo(Modulo.COMERCIAL)
def concluir_tarefa(request, pk):
    at = get_object_or_404(AtividadeComercial, pk=pk)
    if request.method == "POST":
        services.concluir_tarefa(at, request.user)
        messages.success(request, "Tarefa concluída.")
    return redirect("comercial:oportunidade", pk=at.oportunidade_id)


@requer_modulo(Modulo.COMERCIAL)
def cotar(request, pk):
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        form = CotacaoForm(request.POST)
        if form.is_valid():
            try:
                services.registrar_cotacao(
                    oportunidade=op, usuario=request.user,
                    tipo_uh=form.cleaned_data["tipo_uh"],
                    checkin=form.cleaned_data["checkin"],
                    checkout=form.cleaned_data["checkout"],
                    valor_diaria=form.cleaned_data.get("valor_diaria"),
                    validade=form.cleaned_data.get("validade"),
                    observacao=form.cleaned_data.get("observacao") or "",
                )
                messages.success(request, "Cotação registrada.")
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
        else:
            messages.error(request, "Confira os dados da cotação.")
    return redirect("comercial:oportunidade", pk=pk)


@requer_modulo(Modulo.COMERCIAL)
def converter(request, pk):
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        form = ConversaoForm(request.POST)
        if form.is_valid():
            try:
                reserva = services.converter_em_reserva(
                    op, usuario=request.user,
                    tipo_uh=form.cleaned_data["tipo_uh"],
                    checkin=form.cleaned_data["checkin"],
                    checkout=form.cleaned_data["checkout"],
                    valor_diaria=form.cleaned_data.get("valor_diaria"),
                    criar_sinal=bool(form.cleaned_data.get("criar_sinal")),
                    valor_sinal=form.cleaned_data.get("valor_sinal"),
                )
                msg = f"Convertida! Reserva #{reserva.pk} criada."
                op.refresh_from_db()
                if op.cobranca_sinal_id:
                    msg += f" Sinal #{op.cobranca_sinal_id} gerado."
                messages.success(request, msg)
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
        else:
            messages.error(request, "Confira os dados da conversão.")
    return redirect("comercial:oportunidade", pk=pk)


@requer_modulo(Modulo.COMERCIAL)
def perder(request, pk):
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        motivo = MotivoPerda.objects.filter(pk=request.POST.get("motivo") or None).first()
        try:
            services.marcar_perdida(op, motivo, request.user)
            messages.success(request, "Oportunidade marcada como perdida.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("comercial:oportunidade", pk=pk)


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def tarefas(request):
    minhas = request.GET.get("todas") != "1"
    lista = services.tarefas_do_dia(responsavel=request.user if minhas else None)
    return render(request, "comercial/tarefas.html", {
        "tarefas": lista, "minhas": minhas,
    })


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def painel(request):
    abertas = Oportunidade.objects.filter(status=Oportunidade.Status.ABERTA)
    valor_funil = abertas.aggregate(t=Sum("valor_estimado"))["t"] or Decimal("0.00")
    ponderado = sum((o.valor_ponderado for o in abertas.select_related("etapa")),
                    Decimal("0.00"))
    hoje = timezone.localdate()
    ini_mes = hoje.replace(day=1)
    dados = services.relatorio_funil(ini_mes, hoje)
    gestao = services.dados_gestao(ini_mes, hoje)
    perdas = (
        Oportunidade.objects.filter(status=Oportunidade.Status.PERDIDA,
                                    motivo_perda__isnull=False)
        .values("motivo_perda__nome").annotate(n=Count("id")).order_by("-n")
    )
    return render(request, "comercial/painel.html", {
        "abertas": abertas.count(),
        "valor_funil": valor_funil,
        "ponderado": ponderado,
        "dados": dados,
        "gestao": gestao,
        "colunas": services.dados_kanban(),
        "perdas": perdas,
        "meta_form": MetaForm(initial={
            "valor_meta": gestao["meta"] or Decimal("0"),
            "oportunidades_meta": gestao["meta_qtd"] or 0,
        }),
    })


@requer_modulo(Modulo.COMERCIAL)
@requer_gerencia
def meta(request):
    if request.method == "POST":
        form = MetaForm(request.POST)
        if form.is_valid():
            services.definir_meta(
                mes=timezone.localdate().replace(day=1),
                valor_meta=form.cleaned_data["valor_meta"],
                oportunidades_meta=form.cleaned_data.get("oportunidades_meta") or 0,
            )
            messages.success(request, "Meta do mês salva.")
        else:
            messages.error(request, "Confira os valores da meta.")
    return redirect("comercial:painel")


def _datahora(txt):
    if not txt:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return timezone.make_aware(datetime.strptime(txt, fmt))
        except (ValueError, TypeError):
            continue
    return None

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count, F, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from apps.nucleo.models import Pessoa, Prospecto, modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .forms import (
    CampanhaForm,
    ConversaoForm,
    CotacaoForm,
    GastoDiarioForm,
    MetaForm,
    PaginaCaptacaoForm,
    PerdaForm,
    RespostaRapidaForm,
)
from .models import (
    AnaliseLead,
    AtividadeComercial,
    Campanha,
    EtapaFunil,
    MotivoPerda,
    Oportunidade,
    PaginaCaptacao,
    RespostaRapida,
)
from .proposta_instagram import PROPOSTA as PROPOSTA_INSTAGRAM

Usuario = get_user_model()

# Parâmetros de rastreio de anúncio capturados na Página de Captação (Fase A).
RASTREIO_KEYS = (
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid",
)


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
        "agora": timezone.now(),
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


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def cacador(request):
    """Fila do Caçador — leads abertos analisados, do mais quente ao mais frio.

    A análise é por regras (services.analisar_lead); a camada de IA entra depois
    alimentando os mesmos campos. Leads antigos ainda sem análise são preenchidos
    de forma preguiçosa aqui."""
    base = Oportunidade.objects.filter(status=Oportunidade.Status.ABERTA)

    # Filtros por origem (com contagem) — só as origens que têm lead aberto.
    contagem = {r["origem"]: r["n"] for r in base.values("origem").annotate(n=Count("id"))}
    origens = [
        {"cod": cod, "label": label, "n": contagem.get(cod, 0)}
        for cod, label in Oportunidade.Origem.choices if contagem.get(cod)
    ]
    origem_sel = request.GET.get("origem", "")

    leads = base.filter(origem=origem_sel) if origem_sel else base
    # Ordenação: "a revisar" primeiro (revisado_em nulo), depois score, depois recência.
    leads = (
        leads.select_related("pessoa", "etapa", "responsavel", "analise")
        .order_by(F("analise__revisado_em").asc(nulls_first=True), "-score", "-criado_em")
    )

    limite_novo = timezone.now() - timedelta(hours=24)
    fila = []
    for op in leads:
        try:
            analise = op.analise
        except AnaliseLead.DoesNotExist:
            analise = services.analisar_lead(op)  # backfill preguiçoso
        fila.append({"op": op, "analise": analise, "novo": op.criado_em >= limite_novo})
    kpi = {
        "total": len(fila),
        "quentes": sum(1 for f in fila if f["analise"].temperatura == "quente"),
        "a_revisar": sum(1 for f in fila if f["analise"].revisado_em is None),
    }
    return render(request, "comercial/cacador.html", {
        "fila": fila, "kpi": kpi,
        "origens": origens, "origem_sel": origem_sel, "total_geral": base.count(),
    })


@requer_modulo(Modulo.COMERCIAL)
def cacador_feedback(request, pk):
    """Atendente marca a análise como útil ou não — semente do loop de aprendizado."""
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method != "POST":
        return redirect("comercial:cacador")
    analise = services.analisar_lead(op)  # garante que existe
    util = request.POST.get("util")
    analise.util = True if util == "1" else (False if util == "0" else None)
    analise.revisado_por = request.user
    analise.revisado_em = timezone.now()
    analise.save(update_fields=["util", "revisado_por", "revisado_em"])
    services.assumir_lead(op, request.user)  # avaliar no Caçador = interagir
    messages.success(request, "Feedback registrado — o Caçador aprende com isso.")
    return redirect("comercial:cacador")


@requer_modulo(Modulo.COMERCIAL)
def conversao_reenviar(request, pk):
    """Reenvia a conversão do lead ao provedor de mídia (Fase B)."""
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        if op.status == Oportunidade.Status.GANHA:
            ce = services.enviar_conversao(op, "compra", valor=op.valor_estimado, forcar=True)
        else:
            ce = services.enviar_conversao(op, "lead", forcar=True)
        if ce is None:
            messages.info(request, "Sem identificador de clique (fbclid/gclid) — nada a enviar.")
        elif ce.status == "enviada":
            messages.success(request, "Conversão reenviada ao provedor.")
        else:
            messages.error(request, f"Falha ao enviar: {ce.erro[:140]}")
    return redirect("comercial:oportunidade", pk=op.pk)


@requer_modulo(Modulo.COMERCIAL)
def assumir(request, pk):
    """Vendedor pega o lead (assume a propriedade se estiver sem dono)."""
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        if services.assumir_lead(op, request.user):
            messages.success(request, f"Você assumiu «{op.pessoa.nome}».")
        elif op.responsavel_id:
            dono = op.responsavel.get_full_name() or op.responsavel.username
            messages.info(request, f"Lead já é de {dono}.")
    destino = request.META.get("HTTP_REFERER") or ""
    return redirect(destino if destino else "comercial:funil")


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
    from django.conf import settings as _settings
    conversa_wpp = services.abrir_conversa_whatsapp(op)
    return render(request, "comercial/oportunidade.html", {
        "op": op,
        "atividades": op.atividades.select_related("responsavel"),
        "cotacoes": op.cotacoes.select_related("tipo_uh"),
        "tipos_atividade": AtividadeComercial.Tipo.choices,
        "etapas": [e for e in services.etapas() if e.tipo == EtapaFunil.Tipo.ABERTA],
        "conversao_form": _conversao_inicial(op),
        "cotacao_form": _cotacao_inicial(op),
        "perda_form": PerdaForm(),
        "pagamentos_ativo": modulo_ativo(Modulo.PAGAMENTOS),
        "responsaveis": Usuario.objects.filter(is_active=True).order_by(
            "first_name", "username"),
        "conversa_wpp": conversa_wpp,
        "mensagens_wpp": list(conversa_wpp.mensagens.all()),
        "respostas_rapidas": services.respostas_rapidas_para(op),
        "whatsapp_simulado": getattr(_settings, "WHATSAPP_GATEWAY", "simulado") == "simulado",
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


# ─────────────────── Gestor de Páginas de Captação (Landing Pages) ───────────────────

@never_cache
@requer_modulo(Modulo.COMERCIAL)
def paginas(request):
    """Lista as Páginas de Captação com visitas · leads · conversão."""
    itens = list(PaginaCaptacao.objects.all())
    return render(request, "comercial/paginas/lista.html", {"paginas": itens})


@requer_modulo(Modulo.COMERCIAL)
def pagina_nova(request):
    if request.method == "POST":
        form = PaginaCaptacaoForm(request.POST)
        if form.is_valid():
            pagina = form.save(commit=False)
            if not pagina.slug:
                pagina.slug = slugify(pagina.nome)[:60]
            pagina.criado_por = request.user
            if pagina.publicada and not pagina.publicada_em:
                pagina.publicada_em = timezone.now()
            pagina.save()
            messages.success(request, "Página de captação criada.")
            return redirect("comercial:pagina_detalhe", pk=pagina.pk)
    else:
        form = PaginaCaptacaoForm()
    return render(request, "comercial/paginas/form.html", {"form": form, "novo": True})


@requer_modulo(Modulo.COMERCIAL)
def pagina_editar(request, pk):
    pagina = get_object_or_404(PaginaCaptacao, pk=pk)
    if request.method == "POST":
        form = PaginaCaptacaoForm(request.POST, instance=pagina)
        if form.is_valid():
            pagina = form.save(commit=False)
            if pagina.publicada and not pagina.publicada_em:
                pagina.publicada_em = timezone.now()
            pagina.save()
            messages.success(request, "Página atualizada.")
            return redirect("comercial:pagina_detalhe", pk=pagina.pk)
    else:
        form = PaginaCaptacaoForm(instance=pagina)
    return render(request, "comercial/paginas/form.html",
                  {"form": form, "pagina": pagina, "novo": False})


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def pagina_detalhe(request, pk):
    pagina = get_object_or_404(PaginaCaptacao, pk=pk)
    leads = pagina.oportunidades.select_related("pessoa", "etapa").order_by("-criado_em")
    url_publica = request.build_absolute_uri(pagina.get_absolute_url())
    return render(request, "comercial/paginas/detalhe.html", {
        "pagina": pagina,
        "leads": leads,
        "url_publica": url_publica,
    })


@requer_modulo(Modulo.COMERCIAL)
def pagina_status(request, pk):
    """Publicar / despublicar / encerrar (POST)."""
    pagina = get_object_or_404(PaginaCaptacao, pk=pk)
    if request.method == "POST":
        novo = request.POST.get("status")
        if novo in PaginaCaptacao.Status.values:
            pagina.status = novo
            if novo == PaginaCaptacao.Status.PUBLICADA and not pagina.publicada_em:
                pagina.publicada_em = timezone.now()
            pagina.save(update_fields=["status", "publicada_em", "atualizado_em"])
            messages.success(request, f"Página {pagina.get_status_display().lower()}.")
    return redirect("comercial:pagina_detalhe", pk=pagina.pk)


@requer_modulo(Modulo.COMERCIAL)
def pagina_qr(request, pk):
    """QR Code (SVG) da URL pública da página."""
    import qrcode
    import qrcode.image.svg

    pagina = get_object_or_404(PaginaCaptacao, pk=pk)
    url = request.build_absolute_uri(pagina.get_absolute_url())
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=2)
    buf = BytesIO()
    img.save(buf)
    return HttpResponse(buf.getvalue(), content_type="image/svg+xml")


@never_cache
@csrf_protect
def captacao_publica(request, slug):
    """Página pública da campanha (sem login). GET conta visita; POST captura lead."""
    pagina = PaginaCaptacao.objects.filter(slug=slug).first()
    if pagina is None or not pagina.publicada:
        raise Http404("Página não encontrada.")

    enviado = request.GET.get("ok") == "1"
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        telefone = (request.POST.get("telefone") or "").strip()
        email = (request.POST.get("email") or "").strip()
        checkin = _data(request.POST.get("checkin"))
        checkout = _data(request.POST.get("checkout"))
        try:
            pessoas = max(1, min(8, int(request.POST.get("pessoas") or 2)))
        except (TypeError, ValueError):
            pessoas = 2
        origem = {k: (request.POST.get(k) or "").strip() for k in RASTREIO_KEYS}
        origem["referer"] = request.META.get("HTTP_REFERER", "")
        origem["landing_url"] = request.build_absolute_uri(pagina.get_absolute_url())
        if nome and telefone:
            if checkin and checkout and checkout <= checkin:
                checkout = None  # ignora saída inválida (funil aceita só a entrada)
            try:
                services.capturar_lead_site(
                    nome=nome, telefone=telefone, email=email,
                    tipo_interesse=pagina.tipo_interesse, pagina=pagina,
                    hospedes=pessoas, checkin=checkin, checkout=checkout,
                    mensagem=f"Lista de espera — {pagina.nome}", origem=origem,
                )
            except Exception:
                pass  # best-effort: nunca quebra a página pública do lead
            return redirect(f"{pagina.get_absolute_url()}?ok=1")
        return render(request, "comercial/captacao_publica.html",
                      {"pagina": pagina, "erro": "Preencha nome e WhatsApp.",
                       "rastreio": {k: request.POST.get(k, "") for k in RASTREIO_KEYS}})

    services.registrar_visita_pagina(pagina)
    rastreio = {k: request.GET.get(k, "") for k in RASTREIO_KEYS}
    return render(request, "comercial/captacao_publica.html",
                  {"pagina": pagina, "enviado": enviado, "rastreio": rastreio})


# ─────────────────── Gestor de Impulsionamento (anúncios) — Fase A ───────────────────

@never_cache
@requer_modulo(Modulo.COMERCIAL)
def impulsionamento(request):
    """Painel: campanhas com gasto · leads · reservas · custo por lead · retorno."""
    campanhas = list(Campanha.objects.all())
    tot_gasto = sum((c.gasto_total for c in campanhas), Decimal("0.00"))
    tot_leads = sum(c.leads for c in campanhas)
    tot_reservas = sum(c.reservas for c in campanhas)
    tot_receita = sum((c.receita for c in campanhas), Decimal("0.00"))
    kpi = {
        "gasto": tot_gasto,
        "leads": tot_leads,
        "reservas": tot_reservas,
        "cpl": (tot_gasto / tot_leads).quantize(Decimal("0.01")) if tot_leads else Decimal("0.00"),
        "retorno": (tot_receita / tot_gasto).quantize(Decimal("0.01")) if tot_gasto else Decimal("0.00"),
    }
    return render(request, "comercial/impulsionamento/painel.html",
                  {"campanhas": campanhas, "kpi": kpi})


@requer_modulo(Modulo.COMERCIAL)
def campanha_nova(request):
    if request.method == "POST":
        form = CampanhaForm(request.POST)
        if form.is_valid():
            camp = form.save(commit=False)
            if not camp.codigo:
                camp.codigo = slugify(camp.nome)[:80]
            camp.criado_por = request.user
            camp.save()
            messages.success(request, "Campanha criada.")
            return redirect("comercial:campanha_detalhe", pk=camp.pk)
    else:
        form = CampanhaForm()
    return render(request, "comercial/impulsionamento/form.html",
                  {"form": form, "novo": True})


@requer_modulo(Modulo.COMERCIAL)
def campanha_editar(request, pk):
    camp = get_object_or_404(Campanha, pk=pk)
    if request.method == "POST":
        form = CampanhaForm(request.POST, instance=camp)
        if form.is_valid():
            form.save()
            messages.success(request, "Campanha atualizada.")
            return redirect("comercial:campanha_detalhe", pk=camp.pk)
    else:
        form = CampanhaForm(instance=camp)
    return render(request, "comercial/impulsionamento/form.html",
                  {"form": form, "campanha": camp, "novo": False})


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def campanha_detalhe(request, pk):
    camp = get_object_or_404(Campanha, pk=pk)
    gasto_form = GastoDiarioForm()
    leads = camp.oportunidades.select_related("pessoa", "etapa").order_by("-criado_em")
    gastos = camp.gastos.select_related("criado_por")
    url_utm = ""
    if camp.pagina_captacao:
        base = request.build_absolute_uri(camp.pagina_captacao.get_absolute_url())
        url_utm = f"{base}?utm_source={camp.provedor}&utm_medium=cpc&utm_campaign={camp.codigo}"
    return render(request, "comercial/impulsionamento/detalhe.html", {
        "campanha": camp, "gasto_form": gasto_form,
        "leads": leads, "gastos": gastos, "url_utm": url_utm,
    })


@requer_modulo(Modulo.COMERCIAL)
def campanha_sincronizar(request, pk):
    """Puxa o gasto da plataforma para a campanha (Fase C). POST."""
    camp = get_object_or_404(Campanha, pk=pk)
    if request.method == "POST":
        try:
            n = services.sincronizar_gastos(campanha=camp, dias=30)
            if n:
                messages.success(request, f"{n} dia(s) de gasto sincronizado(s).")
            else:
                messages.info(
                    request,
                    "Nada sincronizado. Verifique MIDIA_GATEWAY, o token e o ID da campanha "
                    "na plataforma (ou lance o gasto manualmente).")
        except Exception as e:  # best-effort
            messages.error(request, f"Falha na sincronização: {str(e)[:140]}")
    return redirect("comercial:campanha_detalhe", pk=camp.pk)


@requer_modulo(Modulo.COMERCIAL)
def campanha_gasto(request, pk):
    """Lança um gasto na campanha (POST)."""
    camp = get_object_or_404(Campanha, pk=pk)
    if request.method == "POST":
        form = GastoDiarioForm(request.POST)
        if form.is_valid():
            try:
                services.registrar_gasto(
                    campanha=camp, data=form.cleaned_data["data"],
                    valor=form.cleaned_data["valor"], usuario=request.user,
                )
                messages.success(request, "Gasto lançado.")
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
        else:
            messages.error(request, "Preencha data e valor.")
    return redirect("comercial:campanha_detalhe", pk=camp.pk)


# ─────────────────── WhatsApp no funil (MVP) + Respostas Rápidas ───────────────────

@requer_modulo(Modulo.COMERCIAL)
def enviar_proposta_sinal(request, pk):
    """Gera a cobrança do sinal (Safrapay/simulado), monta o link público e envia no WhatsApp."""
    from django.urls import reverse
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        try:
            cobranca = services.criar_cobranca_sinal(op, request.user)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect("comercial:oportunidade", pk=op.pk)
        link = request.build_absolute_uri(reverse("pagamentos:pagar", args=[cobranca.token]))
        valor_br = f"{cobranca.valor:.2f}".replace(".", ",")
        texto = services.montar_proposta_sinal(op, cobranca, link)
        try:
            conv = services.abrir_conversa_whatsapp(op)
            services.enviar_mensagem_whatsapp(conversa=conv, texto=texto, usuario=request.user)
        except Exception:
            pass  # best-effort — o link já foi gerado
        services.registrar_atividade(
            oportunidade=op, usuario=request.user, tipo=AtividadeComercial.Tipo.WHATSAPP,
            descricao=f"Proposta + sinal enviada (R$ {valor_br}) — {link}")
        messages.success(request, f"Sinal gerado e enviado no WhatsApp. Link: {link}")
    return redirect("comercial:oportunidade", pk=op.pk)


@requer_modulo(Modulo.COMERCIAL)
def enviar_email_lead(request, pk):
    """Trilho 1:1: compõe o e-mail da proposta (cotação + valores + link), preview
    editável, e envia para o lead. Roda no gateway simulado (console em dev)."""
    op = get_object_or_404(Oportunidade, pk=pk)
    stored = (op.pessoa.email or "").strip()
    destinatario = stored
    assincrono = getattr(settings, "EMAIL_ENVIO_ASSINCRONO", True)
    template_sel = ""
    if request.method == "POST":
        assunto = (request.POST.get("assunto") or "").strip()
        corpo = request.POST.get("corpo") or ""
        acao = request.POST.get("acao") or "previa"
        destinatario = (request.POST.get("destinatario") or "").strip()
        template_sel = (request.POST.get("template") or "").strip()

        # Aplicar template: substitui assunto+corpo pelo template preenchido com o lead.
        if acao == "template" and template_sel:
            tpl = services.templates_email_ativos().filter(pk=template_sel).first()
            if tpl:
                assunto, corpo = services.aplicar_template_email(tpl, op)
                messages.success(request, f"Template “{tpl.nome}” aplicado.")

        dados = services.montar_proposta_email(op, corpo=corpo)
        if assunto:
            dados["assunto"] = assunto

        if acao == "salvar_template":
            tpl = services.salvar_template_email(
                nome=request.POST.get("template_nome", ""),
                assunto=dados["assunto"], corpo=corpo,
                oportunidade=op, usuario=request.user)
            messages.success(request, f"Template “{tpl.nome}” salvo na biblioteca.")

        elif acao == "enviar":
            try:
                validate_email(destinatario)
            except ValidationError:
                messages.error(request, "Informe um e-mail válido para enviar ao lead.")
            else:
                # Novo contato / correção: grava o e-mail no cadastro (fica na trilha).
                salvou_contato = destinatario != stored
                if salvou_contato:
                    op.pessoa.email = destinatario
                    op.pessoa.save(update_fields=["email"])
                envio = services.enviar_email(
                    para=destinatario, assunto=dados["assunto"], html=dados["html"],
                    texto=dados["texto"], usuario=request.user, oportunidade=op,
                    assincrono=assincrono)
                if envio.status != envio.Status.ERRO:
                    messages.success(
                        request,
                        f"E-mail a caminho de {destinatario}." +
                        (" E-mail salvo no cadastro do lead." if salvou_contato else ""))
                    return redirect("comercial:oportunidade", pk=op.pk)
                messages.error(request, f"Falha ao enviar o e-mail: {envio.erro}")

        elif acao == "teste":
            para = (request.user.email or "").strip()
            if not para:
                messages.error(request, "Seu usuário não tem e-mail cadastrado "
                               "para receber o teste.")
            else:
                envio = services.enviar_email(
                    para=para, assunto=f"[TESTE] {dados['assunto']}", html=dados["html"],
                    texto=dados["texto"], usuario=request.user, oportunidade=None,
                    assincrono=assincrono)
                if envio.status != envio.Status.ERRO:
                    messages.success(request, f"Teste a caminho de {para}.")
                else:
                    messages.error(request, f"Falha ao enviar o teste: {envio.erro}")
    else:
        dados = services.montar_proposta_email(op)

    return render(request, "comercial/email/enviar.html", {
        "op": op, "dados": dados, "resumo": services.resumo_da_conversa(op),
        "lead_email": destinatario, "templates": services.templates_email_ativos(),
        "template_sel": template_sel,
    })


@requer_modulo(Modulo.COMERCIAL)
def email_templates(request):
    from .models import TemplateEmail
    return render(request, "comercial/email/templates_lista.html",
                  {"itens": TemplateEmail.objects.all()})


@requer_modulo(Modulo.COMERCIAL)
def email_template_novo(request):
    from .forms import TemplateEmailForm
    if request.method == "POST":
        form = TemplateEmailForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.criado_por = request.user
            t.save()
            messages.success(request, "Template criado.")
            return redirect("comercial:email_templates")
    else:
        form = TemplateEmailForm()
    return render(request, "comercial/email/template_form.html",
                  {"form": form, "novo": True})


@requer_modulo(Modulo.COMERCIAL)
def email_template_editar(request, pk):
    from .forms import TemplateEmailForm
    from .models import TemplateEmail
    t = get_object_or_404(TemplateEmail, pk=pk)
    if request.method == "POST":
        form = TemplateEmailForm(request.POST, instance=t)
        if form.is_valid():
            form.save()
            messages.success(request, "Template atualizado.")
            return redirect("comercial:email_templates")
    else:
        form = TemplateEmailForm(instance=t)
    return render(request, "comercial/email/template_form.html",
                  {"form": form, "template": t, "novo": False})


@requer_modulo(Modulo.COMERCIAL)
def email_template_excluir(request, pk):
    from .models import TemplateEmail
    t = get_object_or_404(TemplateEmail, pk=pk)
    if request.method == "POST":
        t.delete()
        messages.success(request, "Template removido.")
    return redirect("comercial:email_templates")


@requer_modulo(Modulo.COMERCIAL)
def whatsapp_enviar(request, pk):
    """Envia uma resposta de WhatsApp pelo gateway (MVP simulado)."""
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        conv = services.abrir_conversa_whatsapp(op)
        try:
            services.enviar_mensagem_whatsapp(
                conversa=conv, texto=request.POST.get("texto", ""), usuario=request.user)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
    return redirect("comercial:oportunidade", pk=op.pk)


@requer_modulo(Modulo.COMERCIAL)
def whatsapp_simular(request, pk):
    """MVP: injeta uma mensagem 'recebida' do cliente para testar o fluxo no funil."""
    op = get_object_or_404(Oportunidade, pk=pk)
    if request.method == "POST":
        texto = request.POST.get("texto", "").strip() or "Oi! Tenho interesse 🙂"
        services.receber_mensagem_whatsapp(oportunidade=op, texto=texto)
        messages.success(request, "Mensagem simulada recebida.")
    return redirect("comercial:oportunidade", pk=op.pk)


@never_cache
@requer_modulo(Modulo.COMERCIAL)
def respostas(request):
    itens = RespostaRapida.objects.all()
    return render(request, "comercial/respostas/lista.html", {"respostas": itens})


@requer_modulo(Modulo.COMERCIAL)
def resposta_nova(request):
    if request.method == "POST":
        form = RespostaRapidaForm(request.POST)
        if form.is_valid():
            r = form.save(commit=False)
            r.criado_por = request.user
            r.save()
            messages.success(request, "Resposta rápida criada.")
            return redirect("comercial:respostas")
    else:
        form = RespostaRapidaForm()
    return render(request, "comercial/respostas/form.html", {"form": form, "novo": True})


@requer_modulo(Modulo.COMERCIAL)
def resposta_editar(request, pk):
    r = get_object_or_404(RespostaRapida, pk=pk)
    if request.method == "POST":
        form = RespostaRapidaForm(request.POST, instance=r)
        if form.is_valid():
            form.save()
            messages.success(request, "Resposta atualizada.")
            return redirect("comercial:respostas")
    else:
        form = RespostaRapidaForm(instance=r)
    return render(request, "comercial/respostas/form.html",
                  {"form": form, "resposta": r, "novo": False})


@requer_modulo(Modulo.COMERCIAL)
def resposta_excluir(request, pk):
    r = get_object_or_404(RespostaRapida, pk=pk)
    if request.method == "POST":
        r.delete()
        messages.success(request, "Resposta removida.")
    return redirect("comercial:respostas")

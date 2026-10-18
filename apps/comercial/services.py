"""
Regras do módulo Comercial. Interface pública para views, Site, Auditoria e Relatórios.

Só conversa com outros módulos por services. Ganho exige conversão em reserva;
perda exige motivo. Cotação, SLA, score e metas cobrem o Plano Comercial P0–P3.
"""
import unicodedata
from datetime import UTC, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Avg, Count, DurationField, ExpressionWrapper, F, OuterRef, Subquery, Sum,
)
from django.template.loader import render_to_string
from django.utils import timezone

from apps.nucleo.models import Hospede, Prospecto, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .models import (
    AnaliseLead,
    AtividadeComercial,
    Cotacao,
    EtapaFunil,
    MetaComercial,
    Oportunidade,
    PermanenciaEtapa,
)

Usuario = get_user_model()

DIAS_PARADA = 7
SLA_PRIMEIRO_CONTATO_HORAS = 24
SLA_FOLLOWUP_HORAS = 48
VALIDADE_COTACAO_DIAS = 7
SCORE_ORIGEM = {
    "indicacao": 20, "site": 15, "whatsapp": 15, "telefone": 12,
    "agencia": 10, "presencial": 10, "outro": 5,
}


def etapas():
    return EtapaFunil.objects.filter(ativa=True)


def _etapa_por_tipo(tipo):
    return EtapaFunil.objects.filter(ativa=True, tipo=tipo).order_by("ordem").first()


def _etapa_cotacao():
    return EtapaFunil.objects.filter(ativa=True, nome__icontains="cotação").order_by("ordem").first()


def _usuario_site():
    from apps.nucleo.sistema import usuario_de_sistema
    return usuario_de_sistema("_site", "Site")


def calcular_score(oportunidade) -> int:
    score = 0
    valor = oportunidade.valor_estimado or Decimal("0")
    if valor >= 2000:
        score += 30
    elif valor >= 800:
        score += 20
    elif valor > 0:
        score += 10
    if oportunidade.checkin_previsto and oportunidade.checkout_previsto:
        score += 20
    score += SCORE_ORIGEM.get(oportunidade.origem, 5)
    n = oportunidade.atividades.count()
    score += min(25, n * 5)
    if oportunidade.cotacoes.exists():
        score += 10
    return min(100, score)


def atualizar_score(oportunidade):
    score = calcular_score(oportunidade)
    if oportunidade.score != score:
        Oportunidade.objects.filter(pk=oportunidade.pk).update(score=score)
        oportunidade.score = score
    return score


# ───────── Caçador (Máquina de Vendas, Fase 1): análise do lead por regras ─────────

URGENCIA_KW = (
    "hoje", "amanhã", "amanha", "urgente", "essa semana", "esta semana",
    "o quanto antes", "agora", "feriado", "última", "ultima", "last minute",
)


def _temperatura(score: int) -> str:
    if score >= 60:
        return AnaliseLead.Temperatura.QUENTE
    if score >= 35:
        return AnaliseLead.Temperatura.MORNO
    return AnaliseLead.Temperatura.FRIO


def _sinais_lead(op) -> dict:
    obs = (op.observacao or "").lower()
    tem_datas = bool(op.checkin_previsto and op.checkout_previsto)
    noites = (op.checkout_previsto - op.checkin_previsto).days if tem_datas else 0
    tem_contato = bool(op.pessoa.telefone or op.pessoa.email)
    faltando = []
    if not tem_datas:
        faltando.append("as datas")
    if not tem_contato:
        faltando.append("um contato (telefone/e-mail)")
    return {
        "tem_datas": tem_datas,
        "noites": noites,
        "pax": op.hospedes,
        "tem_contato": tem_contato,
        "tem_orcamento": (op.valor_estimado or Decimal("0")) > 0,
        "urgencia": any(k in obs for k in URGENCIA_KW),
        "faltando": faltando,
    }


def _motivos_lead(op, sinais) -> list:
    m = [f"Origem: {op.get_origem_display()}"]
    m.append(f"Datas definidas ({sinais['noites']} noite{'s' if sinais['noites'] != 1 else ''})"
             if sinais["tem_datas"] else "Sem datas ainda")
    if sinais["tem_orcamento"]:
        m.append("Valor estimado informado")
    n_atv = op.atividades.count()
    if n_atv > 1:
        m.append(f"{n_atv} interações")
    if sinais["urgencia"]:
        m.append("Sinais de urgência")
    if not sinais["tem_contato"]:
        m.append("Falta contato")
    return m


def _disponibilidade_snippet(op) -> str:
    """Trecho de disponibilidade REAL do Reservas, conforme o tipo de interesse
    (hospedagem exclui as UHs de day-use; day-use conta só as de day-use)."""
    if not modulo_ativo(Modulo.RESERVAS):
        return ""
    ci, co = op.checkin_previsto, op.checkout_previsto
    if not (ci and co):
        return ""
    try:
        from apps.reservas.services import uhs_disponiveis
        if op.tipo_interesse == Oportunidade.TipoInteresse.DAY_USE:
            fim = co if co > ci else ci + timedelta(days=1)
            n = uhs_disponiveis(ci, fim).filter(tipo__modalidade="day_use").count()
            return (f" Temos {n} vaga(s) de day-use na data." if n
                    else " O day-use nessa data está cheio — posso ver outra data.")
        if op.tipo_interesse == Oportunidade.TipoInteresse.HOSPEDAGEM:
            n = uhs_disponiveis(ci, co).exclude(tipo__modalidade="day_use").count()
            return (f" Temos {n} quarto(s) livre(s) no período." if n
                    else " No período não há quarto livre — posso sugerir datas próximas.")
    except Exception:
        return ""
    return ""


def _rascunho_lead(op, sinais) -> str:
    nome = op.pessoa.nome.split()[0] if op.pessoa.nome else ""
    saud = f"Olá, {nome}!" if nome else "Olá!"
    tipo_lbl = op.get_tipo_interesse_display().lower()
    if not sinais["tem_datas"]:
        faltam = " e ".join(sinais["faltando"]) or "as datas"
        return (f"{saud} Para montar sua proposta de {tipo_lbl}, me confirma {faltam}? "
                "Assim já garanto a disponibilidade e a melhor tarifa.")
    ci = op.checkin_previsto.strftime("%d/%m")
    co = op.checkout_previsto.strftime("%d/%m")
    if op.tipo_interesse == Oportunidade.TipoInteresse.EVENTO:
        return (f"{saud} Sobre seu evento previsto para {ci}: vou verificar o espaço e "
                "montar uma proposta com os valores. Podemos falar rapidinho por telefone/WhatsApp?")
    if op.tipo_interesse == Oportunidade.TipoInteresse.DAY_USE:
        return (f"{saud} Sobre o Dia na Pousada em {ci} para {sinais['pax']} pessoa(s):"
                f"{_disponibilidade_snippet(op)} Quer que eu reserve e envie os valores?")
    return (f"{saud} Sobre seu interesse em {tipo_lbl} de {ci} a {co} para "
            f"{sinais['pax']} pessoa(s):{_disponibilidade_snippet(op)} "
            "Quer que eu segure e já envie a proposta?")


def proxima_acao(op):
    """O que fazer AGORA neste lead + urgência — selo no topo da oportunidade.
    Deriva do estado (sinal pendente, validade da cotação, SLA do 1º contato). None se
    a oportunidade não está aberta."""
    if not op.aberta:
        return None
    hoje = timezone.localdate()
    agora = timezone.now()

    # 1. Sinal gerado, aguardando pagamento.
    if op.cobranca_sinal_id and modulo_ativo(Modulo.PAGAMENTOS):
        from apps.pagamentos.models import Cobranca
        cob = Cobranca.objects.filter(pk=op.cobranca_sinal_id).first()
        if cob and cob.status == Cobranca.Status.PENDENTE:
            return {"nivel": "info", "texto": "Aguardando pagamento do sinal"}

    # 2. Cotação: validade.
    cot = op.cotacoes.order_by("-criado_em").first()
    if cot and cot.validade:
        dias = (cot.validade - hoje).days
        if dias < 0:
            return {"nivel": "alerta", "texto": "Cotação vencida — refazer ou cobrar"}
        if dias <= 2:
            return {"nivel": "aviso",
                    "texto": f"Cotação vence em {dias} dia{'s' if dias != 1 else ''}"}

    # 3. Sem cotação ainda — 1º contato (SLA 24h).
    if not op.valor_estimado or op.valor_estimado <= 0:
        horas = (agora - op.criado_em).total_seconds() / 3600
        if horas >= SLA_PRIMEIRO_CONTATO_HORAS:
            return {"nivel": "alerta", "texto": "1º contato atrasado (SLA 24h)"}
        return {"nivel": "info", "texto": "Fazer 1º contato e cotar"}

    return {"nivel": "info", "texto": "Aguardando resposta do cliente"}


def analisar_lead(op):
    """Preenche/atualiza a análise do Caçador (por regras). Idempotente."""
    atualizar_score(op)
    sinais = _sinais_lead(op)
    analise, _ = AnaliseLead.objects.update_or_create(
        oportunidade=op,
        defaults={
            "temperatura": _temperatura(op.score),
            "sinais": sinais,
            "motivos": _motivos_lead(op, sinais),
            "rascunho": _rascunho_lead(op, sinais),
        },
    )
    _avaliar_sombra_jev(op, analise)  # Fase 0 (sombra) — não afeta score/temperatura
    return analise


def features_lead(op) -> dict:
    """Features derivadas do lead p/ o modelo de decisão — SEM PII (só sinais)."""
    hoje = timezone.localdate()
    ci, co = op.checkin_previsto, op.checkout_previsto
    return {
        "origem": op.origem,
        "tipo_interesse": op.tipo_interesse,
        "faturamento": op.faturamento,
        "valor_estimado": float(op.valor_estimado or 0),
        "tem_datas": bool(ci and co),
        "antecedencia_dias": ((ci - hoje).days if ci else None),
        "noites": ((co - ci).days if (ci and co) else None),
        "hospedes": op.hospedes or 0,
        "n_atividades": op.atividades.count(),
        "tem_cotacao": op.cotacoes.exists(),
        "pagina": (op.pagina_captacao.slug if op.pagina_captacao_id else ""),
        "tem_email": bool(op.pessoa.email),
        "tem_telefone": bool(op.pessoa.telefone),
    }


def _avaliar_sombra_jev(op, analise):
    """Fase 0 (sombra): grava a previsão do gateway de decisão em paralelo ao
    heurístico. Best-effort — nunca estoura e NÃO altera score/temperatura oficiais."""
    from .decisao_gateway import get_decisao_gateway
    try:
        res = get_decisao_gateway().avaliar_lead(features_lead(op))
    except Exception:  # noqa: BLE001 — sombra nunca quebra a análise
        res = None
    if not res:
        return
    AnaliseLead.objects.filter(pk=analise.pk).update(
        score_jev=res.get("score"),
        confianca_jev=res.get("confianca"),
        canal_sugerido=res.get("canal") or "",
        qualificado_jev=res.get("qualificado"),
        jev_modelo=res.get("modelo") or "",
        jev_avaliado_em=timezone.now(),
    )


def _abrir_permanencia(oportunidade, etapa, quando=None):
    PermanenciaEtapa.objects.create(
        oportunidade=oportunidade, etapa=etapa,
        iniciado_em=quando or timezone.now(),
    )


def _fechar_permanencia(oportunidade, quando=None):
    aberta = PermanenciaEtapa.objects.filter(
        oportunidade=oportunidade, finalizado_em__isnull=True,
    ).order_by("-iniciado_em").first()
    if aberta:
        aberta.finalizado_em = quando or timezone.now()
        aberta.save(update_fields=["finalizado_em"])


def dados_kanban(faturamento="", inicio=None, fim=None, todos=False):
    """Colunas do funil. As etapas abertas mostram os leads em aberto (sempre — o pipeline
    é "agora", não depende de período); as etapas terminais (Ganho/Perdido) mostram os
    fechados do PERÍODO (padrão = mês corrente) — ou o histórico inteiro se `todos=True`.
    Sem isso, o card sumiria do quadro ao marcar ganho/perda (histórico fica em Relatórios).
    """
    from .models import ConversaWhatsApp
    base = Oportunidade.objects.select_related(
        "pessoa", "etapa", "responsavel", "pagina_captacao", "analise"
    ).annotate(
        # Mensagens de WhatsApp recebidas e ainda não respondidas (zera ao responder).
        wpp_nao_lidas=Subquery(ConversaWhatsApp.objects.filter(
            oportunidade=OuterRef("pk")).values("nao_lidas")[:1]),
    )
    abertas = base.filter(status=Oportunidade.Status.ABERTA)
    if faturamento:
        abertas = abertas.filter(faturamento=faturamento)
    por_etapa = {}
    for op in abertas:
        por_etapa.setdefault(op.etapa_id, []).append(op)

    # Fechados (ganha/perdida) na sua etapa terminal, filtrados pelo período.
    fechadas = base.filter(
        status__in=[Oportunidade.Status.GANHA, Oportunidade.Status.PERDIDA]
    )
    if not todos:
        if inicio is None or fim is None:
            hoje = timezone.localdate()
            inicio, fim = hoje.replace(day=1), hoje
        fechadas = fechadas.filter(fechado_em__date__range=(inicio, fim))
    if faturamento:
        fechadas = fechadas.filter(faturamento=faturamento)
    for op in fechadas.order_by("-fechado_em"):
        por_etapa.setdefault(op.etapa_id, []).append(op)

    colunas = []
    for etapa in etapas():
        itens = por_etapa.get(etapa.id, [])
        colunas.append({
            "etapa": etapa,
            "itens": itens,
            "total": sum((o.valor_estimado for o in itens), Decimal("0.00")),
        })
    return colunas


@transaction.atomic
def criar_oportunidade(*, usuario, pessoa, titulo, etapa=None, disparar_crm=True, **campos):
    """`disparar_crm=False` pula o envio síncrono do evento à Meta CAPI (POST com timeout
    de 20s) — usado no webhook do WhatsApp, onde não se pode bloquear a resposta à Meta."""
    if etapa is None:
        etapa = etapas().first()
        if etapa is None:
            raise ValidationError("Nenhuma etapa de funil configurada.")
    op = Oportunidade.objects.create(
        pessoa=pessoa, titulo=titulo, etapa=etapa, criado_por=usuario,
        responsavel=campos.pop("responsavel", usuario), **campos,
    )
    _abrir_permanencia(op, etapa)
    analisar_lead(op)  # Caçador analisa o lead na entrada (score + rascunho)
    if disparar_crm:
        transaction.on_commit(lambda: enviar_evento_crm(op, _estagio_key(op.etapa)))
    return op


@transaction.atomic
def _resolver_campanha(rastreio):
    """Acha a Campanha pelo utm_campaign do rastreio (case-insensitive)."""
    from .models import Campanha
    utm = (rastreio or {}).get("utm_campaign") or ""
    if not utm:
        return None
    return Campanha.objects.filter(codigo__iexact=utm.strip()).first()


def _norm_nome(s):
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.split())


def _norm_tel(s):
    """Só dígitos, sem o DDI do Brasil (55). Ex.: '(49) 99143-8813' → '49991438813'.

    Serve p/ casar o mesmo número gravado com/sem máscara, DDD ou +55.
    """
    d = "".join(c for c in (s or "") if c.isdigit())
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    return d


def _pessoa_por_telefone(telefone, nome):
    """Acha a Pessoa ativa do mesmo telefone (compara os últimos 8 dígitos, tolera
    máscara/DDD/DDI) cujo nome seja compatível. None se não houver — evita duplicar
    contato quando a LP manda só nome + WhatsApp (sem e-mail nem documento).
    """
    from apps.nucleo.models import Pessoa
    chave = _norm_tel(telefone)[-8:]
    if len(chave) < 8:
        return None
    # Pré-filtra no banco pelos últimos 4 dígitos (sempre contíguos, mesmo com máscara)
    # e confirma em Python o casamento dos 8 dígitos — o `__contains` sozinho falha
    # entre '(49) 99143-8813' e '49991438813'.
    cand = Pessoa.objects.filter(telefone__contains=chave[-4:], ativo=True)
    for c in cand.iterator():
        if _norm_tel(c.telefone)[-8:] == chave and _nomes_compativeis(c.nome, nome):
            return c
    return None


def _nomes_compativeis(a, b):
    """Mesma pessoa? Ignora acento/caixa; aceita prefixo/contido ou mesmo 1º nome.

    'Flavio' ~ 'Flávio Calgaro' (True); 'Daniela' vs 'Flávio Calgaro' (False).
    """
    na, nb = _norm_nome(a), _norm_nome(b)
    if not na or not nb:
        return True
    if na == nb or na in nb or nb in na:
        return True
    return na.split()[0] == nb.split()[0]


def _pessoa_por_telefone_qualquer(telefone):
    """Acha a Pessoa do mesmo telefone pelos últimos 8 dígitos, SEM exigir nome.

    Para o WhatsApp recebido o telefone É a identidade — o nome do perfil pode nem vir,
    ou vir diferente do cadastro. Tolera máscara/DDD/DDI (ver `_norm_tel`). Inclui
    inativas de propósito: anexar a resposta ao cadastro existente (mesmo desativado) é
    melhor do que criar um contato duplicado.
    """
    from apps.nucleo.models import Pessoa
    chave = _norm_tel(telefone)[-8:]
    if len(chave) < 8:
        return None
    for c in Pessoa.objects.filter(telefone__contains=chave[-4:]).iterator():
        if _norm_tel(c.telefone)[-8:] == chave:
            return c
    return None


def _formatar_tel_br(telefone):
    """'5549999648702' → '(49) 99964-8702' (para nomear o lead quando o perfil não vem)."""
    d = _norm_tel(telefone)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d or telefone


def _anota_lead_repetido(op, mensagem, usuario):
    """Lead repetido na MESMA campanha com card ABERTO: NÃO duplica — registra no card
    existente que um novo cadastro chegou (nota + reanálise). Nunca muda a etapa."""
    hoje = timezone.localdate()
    cab = f"🔁 Lead repetido (mesma campanha) em {hoje:%d/%m/%Y}."
    texto = cab + (f" {mensagem}" if mensagem else "")
    op.observacao = ((op.observacao + "\n") if op.observacao else "") + texto
    op.save(update_fields=["observacao", "atualizado_em"])
    registrar_atividade(oportunidade=op, usuario=usuario,
                        tipo=AtividadeComercial.Tipo.NOTA, descricao=texto[:200])
    analisar_lead(op)
    return op


def _reabrir_lead_para_campanha(op, pagina, mensagem, usuario):
    """Pessoa com histórico voltou por uma campanha (nova LP, ou a mesma já fechada):
    reaproveita o MESMO card — reabre em "Novo lead", marca a campanha e preserva a
    conversa (1:1). Espelha _reativar_oportunidade, adaptado ao contexto de LP."""
    primeira = etapas().first()
    if primeira is None:
        return None  # sem funil configurado → cai no fluxo normal (cria novo)
    motivo_anterior = op.motivo_perda.nome if op.motivo_perda_id else None
    _fechar_permanencia(op)
    op.status = Oportunidade.Status.ABERTA
    op.etapa = primeira
    op.fechado_em = None
    op.reativada_em = timezone.now()
    op.motivo_perda = None
    op.motivo_perda_detalhe = ""
    op.pagina_captacao = pagina
    if mensagem:
        op.observacao = ((op.observacao + "\n") if op.observacao else "") + mensagem
    op.save(update_fields=["status", "etapa", "fechado_em", "reativada_em",
                           "motivo_perda", "motivo_perda_detalhe", "pagina_captacao",
                           "observacao", "atualizado_em"])
    _abrir_permanencia(op, primeira)
    atualizar_score(op)
    nota = f"♻️ Reativado — novo interesse pela campanha “{pagina.nome}”."
    if motivo_anterior:
        nota += f" Perda anterior: {motivo_anterior}."
    _nota_sistema_lead(op, nota)
    return op


def _dedupe_lead_por_campanha(*, pessoa, pagina, mensagem, usuario):
    """Dedup de lead por campanha (LP). Retorna a Oportunidade tratada, ou None para
    seguir o fluxo normal (pessoa sem nenhum card)."""
    cards = Oportunidade.objects.filter(pessoa=pessoa)
    # 1) card ABERTO na MESMA campanha → repetido: só anota
    aberto_mesma = cards.filter(
        pagina_captacao=pagina, status=Oportunidade.Status.ABERTA,
    ).order_by("-criado_em").first()
    if aberto_mesma is not None:
        return _anota_lead_repetido(aberto_mesma, mensagem, usuario)
    # 2) tem histórico (card fechado, ou aberto em outra campanha) → reabre p/ Novo lead
    anterior = cards.order_by("-criado_em").first()
    if anterior is not None:
        return _reabrir_lead_para_campanha(anterior, pagina, mensagem, usuario)
    # 3) sem card → fluxo normal
    return None


def capturar_lead_site(*, nome, email="", telefone="", mensagem="",
                       checkin=None, checkout=None, hospedes=2, documento="",
                       tipo_interesse="hospedagem", faturamento=None, pagina=None,
                       origem=None, aceita_email=None, ip="", user_agent=""):
    """Interface pública do site: cria Pessoa+Prospecto+Oportunidade (origem=site).

    Se o módulo Comercial estiver inativo, retorna None (site ainda mostra sucesso).
    Idempotência leve: mesmo e-mail + mesmas datas + tipo em 24h atualiza a aberta.
    `pagina` (PaginaCaptacao) carimba a Landing Page de origem. `origem` (dict) traz o
    rastreio de anúncio (UTM + fbclid/gclid) → grava e casa a Campanha pelo utm_campaign.
    """
    from apps.nucleo.models import Pessoa

    if not modulo_ativo(Modulo.COMERCIAL):
        return None
    nome = (nome or "").strip()
    if not nome:
        raise ValidationError("Informe o nome.")
    email = (email or "").strip().lower()
    telefone = (telefone or "").strip()
    documento = (documento or "").strip()
    mensagem = (mensagem or "").strip()
    tipo = tipo_interesse or Oportunidade.TipoInteresse.HOSPEDAGEM
    if tipo not in Oportunidade.TipoInteresse.values:
        tipo = Oportunidade.TipoInteresse.OUTRO
    fat = faturamento or Oportunidade.Faturamento.PARTICULAR
    if tipo == Oportunidade.TipoInteresse.EVENTO and not faturamento:
        fat = Oportunidade.Faturamento.EMPRESA
    usuario = _usuario_site()

    # Enriquecimento best-effort do lead (sinais estimados: sexo/UF/cidade/dispositivo)
    # → carimbados no origem_rastreio, sem sobrescrever nada explícito do anúncio.
    origem = dict(origem or {})
    try:
        from .enriquecimento import sinais_do_lead
        for chave, valor in sinais_do_lead(
                nome=nome, telefone=telefone, ip=ip, user_agent=user_agent).items():
            origem.setdefault(chave, valor)
    except Exception:  # noqa: BLE001 — enriquecimento nunca quebra a captação
        pass

    pessoa = None
    if email:
        pessoa = Pessoa.objects.filter(email__iexact=email, ativo=True).first()
    if pessoa is None and documento:
        pessoa = Pessoa.objects.filter(documento=documento, ativo=True).first()
    # E-mail/documento podem ser compartilhados (agência, família, engano). Se o nome é
    # claramente outro, é OUTRA pessoa — não funde leads distintos sob o nome antigo.
    if pessoa is not None and not _nomes_compativeis(pessoa.nome, nome):
        pessoa = None
    # Dedupe por telefone: a LP manda só nome + WhatsApp (sem e-mail/doc), então sem isto
    # cada envio criava um contato novo. Reaproveita a Pessoa do mesmo número + nome.
    if pessoa is None and telefone:
        pessoa = _pessoa_por_telefone(telefone, nome)
    if pessoa is None:
        pessoa = Pessoa.objects.create(
            nome=nome, email=email, telefone=telefone, documento=documento,
        )
    else:
        mudou = []
        if telefone and not pessoa.telefone:
            pessoa.telefone = telefone
            mudou.append("telefone")
        if email and not pessoa.email:
            pessoa.email = email
            mudou.append("email")
        # Nome compatível e mais completo → atualiza ("Flavio" → "Flávio Calgaro").
        if nome and len(nome) > len(pessoa.nome or ""):
            pessoa.nome = nome
            mudou.append("nome")
        if mudou:
            pessoa.save(update_fields=mudou)

    # Consentimento explícito da LP (opt-in) — concede e-mail E WhatsApp (o texto da LP
    # autoriza os dois). Carimba cada data uma vez; canais desligam-se de forma
    # independente depois (descadastro de e-mail vs. "sair" no WhatsApp).
    if aceita_email:
        campos = []
        if not pessoa.aceita_email or pessoa.email_optin_em is None:
            pessoa.aceita_email = True
            pessoa.email_optin_em = pessoa.email_optin_em or timezone.now()
            campos += ["aceita_email", "email_optin_em"]
        if not pessoa.aceita_whatsapp or pessoa.whatsapp_optin_em is None:
            pessoa.aceita_whatsapp = True
            pessoa.whatsapp_optin_em = pessoa.whatsapp_optin_em or timezone.now()
            campos += ["aceita_whatsapp", "whatsapp_optin_em"]
        if campos:
            pessoa.save(update_fields=campos)

    Prospecto.objects.get_or_create(pessoa=pessoa)

    # Deduplicação por campanha (LP): decide pelo histórico da pessoa —
    #  • card ABERTO na MESMA campanha → lead repetido: só anota, não duplica;
    #  • qualquer outro histórico → reabre o card da pessoa em "Novo lead" para esta
    #    campanha, preservando a conversa (1:1 com o card).
    # Pessoa sem card algum → segue o fluxo normal (cria novo).
    if pagina is not None:
        tratado = _dedupe_lead_por_campanha(
            pessoa=pessoa, pagina=pagina, mensagem=mensagem, usuario=usuario)
        if tratado is not None:
            return tratado

    limite = timezone.now() - timedelta(hours=24)
    qs = Oportunidade.objects.filter(
        pessoa=pessoa, origem=Oportunidade.Origem.SITE,
        status=Oportunidade.Status.ABERTA, criado_em__gte=limite,
        tipo_interesse=tipo,
    )
    if checkin:
        qs = qs.filter(checkin_previsto=checkin)
    if checkout:
        qs = qs.filter(checkout_previsto=checkout)
    existente = qs.order_by("-criado_em").first()
    if existente:
        mudou = []
        if pagina and existente.pagina_captacao_id is None:
            existente.pagina_captacao = pagina
            mudou.append("pagina_captacao")
        rastreio_e = {k: v for k, v in (origem or {}).items() if v}
        if rastreio_e and not existente.origem_rastreio:
            existente.origem_rastreio = rastreio_e
            mudou.append("origem_rastreio")
        if rastreio_e and existente.campanha_id is None:
            camp = _resolver_campanha(rastreio_e)
            if camp:
                existente.campanha = camp
                mudou.append("campanha")
        if mudou:
            existente.save(update_fields=mudou + ["atualizado_em"])
        if mensagem:
            obs = (existente.observacao + "\n" if existente.observacao else "") + mensagem
            existente.observacao = obs.strip()
            existente.save(update_fields=["observacao", "atualizado_em"])
            registrar_atividade(
                oportunidade=existente, usuario=usuario, tipo=AtividadeComercial.Tipo.NOTA,
                descricao=f"Atualização do site: {mensagem[:200]}",
            )
        analisar_lead(existente)  # reanalisa com a nova mensagem
        return existente

    rotulos = {
        Oportunidade.TipoInteresse.EVENTO: "Evento",
        Oportunidade.TipoInteresse.DAY_USE: "Dia na Pousada",
        Oportunidade.TipoInteresse.HOSPEDAGEM: "Proposta",
        Oportunidade.TipoInteresse.OUTRO: "Proposta",
    }
    prefixo = rotulos.get(tipo, "Proposta")
    titulo = f"{prefixo} site — {nome}"
    if checkin and checkout:
        titulo = f"{prefixo} {checkin:%d/%m}→{checkout:%d/%m} — {nome}"
    rastreio = {k: v for k, v in (origem or {}).items() if v}
    op = criar_oportunidade(
        usuario=usuario, pessoa=pessoa, titulo=titulo[:120],
        origem=Oportunidade.Origem.SITE, tipo_interesse=tipo, faturamento=fat,
        checkin_previsto=checkin, checkout_previsto=checkout,
        hospedes=max(1, int(hospedes or 2)),
        observacao=mensagem,
        responsavel=None,
        pagina_captacao=pagina,
        campanha=_resolver_campanha(rastreio),
        origem_rastreio=rastreio,
    )
    registrar_atividade(
        oportunidade=op, usuario=usuario, tipo=AtividadeComercial.Tipo.TAREFA,
        descricao=f"1º contato (SLA 24h) — {prefixo.lower()} capturado no site",
        quando=timezone.now() + timedelta(hours=SLA_PRIMEIRO_CONTATO_HORAS),
        concluida=False,
    )
    # Devolve o evento Lead ao provedor de mídia (Fase B), após gravar. Best-effort.
    transaction.on_commit(lambda: enviar_conversao(op, "lead"))
    # Avisa a equipe e manda boas-vindas ao lead (assíncrono, após o commit).
    transaction.on_commit(lambda: notificar_lead_novo(op.pk))
    transaction.on_commit(lambda: enviar_boas_vindas(op.pk))
    return op


def _log_evento(oportunidade, usuario, descricao):
    """Evento de SISTEMA na Linha do tempo (a 'trilha' do lead: quem fez o quê).

    Registra só com autor real (usuários de sistema _site/_portal não poluem).
    """
    if usuario is None or getattr(usuario, "username", "").startswith("_"):
        return None
    return AtividadeComercial.objects.create(
        oportunidade=oportunidade, tipo=AtividadeComercial.Tipo.SISTEMA,
        descricao=descricao, quando=timezone.now(), concluida=True,
        responsavel=oportunidade.responsavel, criado_por=usuario,
    )


@transaction.atomic
def assumir_lead(oportunidade, usuario) -> bool:
    """Primeiro vendedor a interagir/pegar vira dono do lead (se estiver sem dono).

    Regra: todos veem todos os leads; quem pega ou interage primeiro assume a
    propriedade. Usuários de sistema (_site/_portal) nunca assumem.
    Retorna True se assumiu agora.
    """
    if usuario is None or oportunidade.responsavel_id is not None:
        return False
    if getattr(usuario, "username", "").startswith("_"):
        return False
    oportunidade.responsavel = usuario
    oportunidade.save(update_fields=["responsavel", "atualizado_em"])
    nome = usuario.get_full_name() or usuario.username
    registrar_auditoria(usuario, "lead_assumido", oportunidade, {"responsavel": nome})
    _log_evento(oportunidade, usuario, "assumiu o lead")
    return True


def mover_etapa(oportunidade, etapa, usuario, motivo=None, detalhe=""):
    """Move entre etapas abertas. Ganho exige reserva; Perdido exige motivo."""
    assumir_lead(oportunidade, usuario)
    de = oportunidade.etapa.nome
    if etapa.tipo == EtapaFunil.Tipo.GANHO:
        if not oportunidade.reserva_id:
            raise ValidationError(
                "Para marcar como ganha, use «Ganhar → criar reserva». "
                "Ganho sem conversão não é permitido."
            )
        _fechar_permanencia(oportunidade)
        oportunidade.etapa = etapa
        oportunidade.status = Oportunidade.Status.GANHA
        if not oportunidade.fechado_em:
            oportunidade.fechado_em = timezone.now()
        oportunidade.save(update_fields=["etapa", "status", "fechado_em", "atualizado_em"])
        _abrir_permanencia(oportunidade, etapa)
        _fechar_permanencia(oportunidade)  # ganho é terminal
        transaction.on_commit(lambda: enviar_evento_crm(oportunidade, _estagio_key(etapa)))
        return oportunidade

    if etapa.tipo == EtapaFunil.Tipo.PERDIDO:
        return marcar_perdida(oportunidade, motivo, usuario, detalhe)

    _fechar_permanencia(oportunidade)
    oportunidade.etapa = etapa
    oportunidade.status = Oportunidade.Status.ABERTA
    oportunidade.fechado_em = None
    oportunidade.save(update_fields=["etapa", "status", "fechado_em", "atualizado_em"])
    _abrir_permanencia(oportunidade, etapa)
    atualizar_score(oportunidade)
    if de != etapa.nome:
        _log_evento(oportunidade, usuario, f"moveu: {de} → {etapa.nome}")
    transaction.on_commit(lambda: enviar_evento_crm(oportunidade, _estagio_key(etapa)))
    return oportunidade


@transaction.atomic
def registrar_atividade(*, oportunidade, usuario, tipo, descricao, quando=None,
                        concluida=True, responsavel=None):
    assumir_lead(oportunidade, usuario)  # quem interage primeiro assume o lead
    atividade = AtividadeComercial.objects.create(
        oportunidade=oportunidade, tipo=tipo, descricao=descricao,
        quando=quando or timezone.now(), concluida=concluida,
        responsavel=responsavel or oportunidade.responsavel, criado_por=usuario,
    )
    Oportunidade.objects.filter(pk=oportunidade.pk).update(atualizado_em=timezone.now())
    atualizar_score(oportunidade)
    return atividade


def concluir_tarefa(atividade, usuario):
    if not atividade.concluida:
        atividade.concluida = True
        atividade.save(update_fields=["concluida"])
        atualizar_score(atividade.oportunidade)
    return atividade


@transaction.atomic
def marcar_perdida(oportunidade, motivo, usuario, detalhe=""):
    if motivo is None:
        raise ValidationError("Informe o motivo da perda.")
    detalhe = (detalhe or "").strip()
    _fechar_permanencia(oportunidade)
    oportunidade.status = Oportunidade.Status.PERDIDA
    oportunidade.motivo_perda = motivo
    oportunidade.motivo_perda_detalhe = detalhe
    oportunidade.fechado_em = timezone.now()
    etapa_perdido = _etapa_por_tipo(EtapaFunil.Tipo.PERDIDO)
    if etapa_perdido:
        oportunidade.etapa = etapa_perdido
    oportunidade.save(update_fields=["status", "motivo_perda", "motivo_perda_detalhe",
                                     "fechado_em", "etapa", "atualizado_em"])
    if etapa_perdido:
        _abrir_permanencia(oportunidade, etapa_perdido)
        _fechar_permanencia(oportunidade)
    registrar_auditoria(usuario, "oportunidade_perdida", oportunidade,
                        {"motivo": motivo.nome, "detalhe": detalhe})
    _log_evento(oportunidade, usuario,
                f"marcou como perdida — {motivo.nome}"
                + (f": {detalhe}" if detalhe else ""))
    transaction.on_commit(lambda: enviar_evento_crm(oportunidade, "perdido"))
    return oportunidade


def _limpar_prospecto(pessoa):
    Prospecto.objects.filter(pessoa=pessoa).delete()


def faixas_oportunidade(op):
    """Deriva (adultos_preço, crianças 0-5, crianças 6-15) da oportunidade para a motor
    de preço. Criança 16+ conta como adulto; sem o detalhe de idade, trata as crianças
    como 6-15 (meia) — conservador."""
    idades = [a for a in (op.idades_criancas or []) if a is not None]
    if idades:
        c05 = sum(1 for a in idades if a <= 5)
        c615 = sum(1 for a in idades if 6 <= a <= 15)
        c16 = sum(1 for a in idades if a >= 16)
        return op.adultos + c16, c05, c615
    return op.adultos, 0, op.criancas


@transaction.atomic
def quartos_para_cotacao(checkin=None, checkout=None):
    """Os 24 quartos (não day use) para o dropdown do lead, ordenados por número.
    Com datas válidas e Reservas ativo, retorna só os **livres** no período
    (disponibilidade central: reservas ativas + bloqueios de manutenção)."""
    from apps.nucleo.models import UH
    from apps.nucleo.models.cadastros import TipoUH
    qs = (UH.objects.exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
          .select_related("tipo").order_by("numero"))
    if checkin and checkout and checkout > checkin and modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import uhs_disponiveis
        livres = list(uhs_disponiveis(checkin, checkout).values_list("pk", flat=True))
        qs = qs.filter(pk__in=livres)
    return qs


def rotulo_quarto(uh):
    """Rótulo do quarto 'Quarto NN — Ala' (+ ' PCD'). A ala vem da regra oficial
    (UH.ala); o tipo não entra no rótulo. Usado em exibições fora do combo."""
    base = f"{uh.numero} — {uh.ala}" if uh.ala else uh.numero
    return f"{base} PCD" if uh.pcd else base


def quartos_combo_dados(queryset):
    """Dados do combo de quarto (Alpine), quebrado por sessões de ala:
    `[{id, nome, grupo}]` por número. `grupo` = ala oficial (vira o cabeçalho da sessão);
    `nome` = 'Quarto NN' (+ ' · PCD' quando acessível)."""
    return [
        {"id": u.pk,
         "nome": f"{u.numero} · PCD" if u.pcd else u.numero,
         "grupo": u.ala or "Outros"}
        for u in queryset
    ]


def registrar_cotacao(*, oportunidade, usuario, tipo_uh=None, uh=None, checkin, checkout,
                      valor_diaria=None, validade=None, observacao="",
                      cobra_iss=True, cobra_taxa_turismo=True,
                      mover_para_cotacao=True):
    """Grava orçamento real; atualiza valor/datas da oportunidade e (opcional) etapa.
    Preço pela motor de tarifa (Manual §2 + taxas) a partir da lotação da oportunidade,
    salvo diária informada à mão pelo vendedor.

    `uh` = quarto físico cotado (venda por unidade); deriva o `tipo_uh`. Sem `uh`
    (ex.: day use), usa o `tipo_uh` direto. O preço segue pelo TIPO do quarto."""
    if not oportunidade.aberta:
        raise ValidationError("Só oportunidades abertas recebem cotação.")
    if uh is not None:
        tipo_uh = uh.tipo  # venda por unidade → o tipo vem do quarto
    if tipo_uh is None:
        raise ValidationError("Informe o quarto (ou o tipo).")
    assumir_lead(oportunidade, usuario)  # cotar = interagir → assume o lead
    if checkout <= checkin:
        raise ValidationError("O check-out deve ser depois do check-in.")
    noites = (checkout - checkin).days
    total_por_quarto = None
    if valor_diaria is None and modulo_ativo(Modulo.RESERVAS):
        from apps.reservas import precos
        adultos_p, c05, c615 = faixas_oportunidade(oportunidade)
        cot = precos.cotacao(
            tipo=tipo_uh, checkin=checkin, checkout=checkout, adultos=adultos_p,
            criancas_0_5=c05, criancas_6_15=c615,
            cobra_iss=cobra_iss, cobra_taxa_turismo=cobra_taxa_turismo)
        valor_diaria = cot["media_noite"]
        total_por_quarto = cot["total"]  # hospedagem + ISS + turismo
    elif valor_diaria is None:
        valor_diaria = tipo_uh.tarifa_base
    valor_diaria = Decimal(str(valor_diaria)).quantize(Decimal("0.01"))
    quartos = max(1, oportunidade.quartos)
    if total_por_quarto is not None:
        valor_total = (total_por_quarto * quartos).quantize(Decimal("0.01"))
    else:
        valor_total = (valor_diaria * noites * quartos).quantize(Decimal("0.01"))
    validade = validade or (timezone.localdate() + timedelta(days=VALIDADE_COTACAO_DIAS))
    cotacao = Cotacao.objects.create(
        oportunidade=oportunidade, tipo_uh=tipo_uh, uh=uh,
        checkin=checkin, checkout=checkout,
        valor_diaria=valor_diaria, valor_total=valor_total, validade=validade,
        observacao=observacao or "", criado_por=usuario,
    )
    oportunidade.checkin_previsto = checkin
    oportunidade.checkout_previsto = checkout
    oportunidade.valor_estimado = valor_total
    oportunidade.save(update_fields=[
        "checkin_previsto", "checkout_previsto", "valor_estimado", "atualizado_em",
    ])
    rotulo_quarto = f"{uh.numero} ({tipo_uh.nome})" if uh is not None else tipo_uh.nome
    registrar_atividade(
        oportunidade=oportunidade, usuario=usuario, tipo=AtividadeComercial.Tipo.COTACAO,
        descricao=(
            f"Cotação {rotulo_quarto}: {checkin:%d/%m}→{checkout:%d/%m} "
            f"— R$ {valor_total} (válida até {validade:%d/%m})"
        ),
    )
    if mover_para_cotacao:
        etapa = _etapa_cotacao()
        if etapa and oportunidade.etapa_id != etapa.id and etapa.tipo == EtapaFunil.Tipo.ABERTA:
            mover_etapa(oportunidade, etapa, usuario)
    atualizar_score(oportunidade)
    return cotacao


@transaction.atomic
def converter_em_reserva(oportunidade, *, tipo_uh=None, uh=None, checkin, checkout, usuario,
                         valor_diaria=None, criar_sinal=False, valor_sinal=None):
    if oportunidade.reserva_id:
        raise ValidationError("Esta oportunidade já foi convertida em reserva.")
    if not modulo_ativo(Modulo.RESERVAS):
        raise ValidationError(
            "Módulo Reservas inativo — não é possível converter em reserva."
        )
    if uh is not None:
        tipo_uh = uh.tipo  # venda por unidade → o tipo vem do quarto
    if tipo_uh is None:
        raise ValidationError("Informe o quarto (ou o tipo).")
    from apps.reservas.services import criar_prereserva

    Hospede.objects.get_or_create(pessoa=oportunidade.pessoa)
    base_obs = f"Convertida da oportunidade #{oportunidade.pk} — {oportunidade.titulo}"
    reserva_kwargs = dict(
        checkin=checkin, checkout=checkout, hospede=oportunidade.pessoa, usuario=usuario,
        canal="site" if oportunidade.origem == "site" else "balcao",
        faturamento=oportunidade.faturamento, adultos=oportunidade.hospedes,
        valor_diaria=valor_diaria,
    )
    if uh is not None:
        # Pré-atribui o quarto cotado; se estiver ocupado no período, aloca qualquer
        # livre do tipo (fallback), registrando a troca na observação.
        try:
            reserva = criar_prereserva(uh=uh, observacoes=base_obs, **reserva_kwargs)
        except ValidationError:
            reserva = criar_prereserva(
                tipo_uh=tipo_uh,
                observacoes=f"{base_obs} (quarto {uh.numero} ocupado — alocado outro do tipo)",
                **reserva_kwargs)
    else:
        reserva = criar_prereserva(tipo_uh=tipo_uh, observacoes=base_obs, **reserva_kwargs)
    _fechar_permanencia(oportunidade)
    oportunidade.reserva_id = reserva.pk
    oportunidade.status = Oportunidade.Status.GANHA
    oportunidade.fechado_em = timezone.now()
    oportunidade.checkin_previsto = checkin
    oportunidade.checkout_previsto = checkout
    etapa_ganho = _etapa_por_tipo(EtapaFunil.Tipo.GANHO)
    if etapa_ganho:
        oportunidade.etapa = etapa_ganho
    oportunidade.save(update_fields=[
        "reserva_id", "status", "fechado_em", "etapa",
        "checkin_previsto", "checkout_previsto", "atualizado_em",
    ])
    if etapa_ganho:
        _abrir_permanencia(oportunidade, etapa_ganho)
        _fechar_permanencia(oportunidade)
    _limpar_prospecto(oportunidade.pessoa)
    registrar_auditoria(usuario, "oportunidade_convertida", oportunidade,
                        {"reserva_id": reserva.pk})
    # Devolve o evento Compra (com valor) ao provedor de mídia (Fase B), após gravar.
    _valor_conv = oportunidade.valor_estimado
    transaction.on_commit(
        lambda: enviar_conversao(oportunidade, "compra", valor=_valor_conv))
    # Evento de estágio 'ganho' p/ a integração de leads qualificados (CAPI CRM).
    transaction.on_commit(lambda: enviar_evento_crm(oportunidade, "ganho"))

    if criar_sinal and modulo_ativo(Modulo.PAGAMENTOS):
        from apps.pagamentos.models import Cobranca
        from apps.pagamentos.services import criar_cobranca
        valor = valor_sinal
        if valor is None:
            valor = (oportunidade.valor_estimado * Decimal("0.30")).quantize(Decimal("0.01"))
        if valor and valor > 0:
            _cancelar_sinal_pendente(oportunidade, usuario)
            cobranca = criar_cobranca(
                usuario, valor=valor, metodo="pix",
                descricao=f"Sinal — oportunidade #{oportunidade.pk} / reserva #{reserva.pk}",
                finalidade=Cobranca.Finalidade.SINAL,
                pagador=oportunidade.pessoa, reserva_id=reserva.pk,
            )
            oportunidade.cobranca_sinal_id = cobranca.pk
            oportunidade.save(update_fields=["cobranca_sinal_id", "atualizado_em"])
            registrar_atividade(
                oportunidade=oportunidade, usuario=usuario,
                tipo=AtividadeComercial.Tipo.SISTEMA,
                descricao=f"Cobrança de sinal #{cobranca.pk} — R$ {valor}",
            )
    _log_evento(oportunidade, usuario, f"converteu em reserva #{reserva.pk}")
    atualizar_score(oportunidade)
    return reserva


def _brl(valor) -> str:
    """1500 → '1.500,00' (padrão BR com separador de milhar)."""
    return f"{Decimal(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_proposta_sinal(oportunidade, cobranca, link) -> str:
    """Copy da proposta+sinal para o WhatsApp (texto puro: *negrito*, _itálico_, emoji).

    Calor humano no topo, o quarto e a experiência em destaque, os números com
    hierarquia (sinal = herói) e uma só chamada à ação. O restante na chegada
    baixa a barreira de decisão.
    """
    op = oportunidade
    nome = (op.pessoa.nome or "").split()[0] if op.pessoa and op.pessoa.nome else ""
    cot = op.ultima_cotacao
    quarto = cot.tipo_uh.nome if cot else op.get_tipo_interesse_display()

    saudacao = f"Oi, {nome} 💛" if nome else "Oi 💛"
    linhas = [
        saudacao,
        "",
        "Sua estadia na *Pousada Vô Testa* está a um passo de ser sua — "
        "separei tudo pra você:",
        "",
        f"*🏕 {quarto}*",
    ]
    if op.checkin_previsto and op.checkout_previsto:
        noites = (op.checkout_previsto - op.checkin_previsto).days
        linhas.append(
            f"🗓 {op.checkin_previsto:%d/%m} → {op.checkout_previsto:%d/%m/%Y}  ·  "
            f"_{noites} noite{'s' if noites != 1 else ''}_"
        )
    linhas.append(f"👥 {op.hospedes} pessoa{'s' if op.hospedes != 1 else ''}")
    linhas.append("")

    if op.valor_estimado:
        linhas.append(f"💰 Total da estadia: *R$ {_brl(op.valor_estimado)}*")
        linhas.append(f"🔒 Sinal para garantir: *R$ {_brl(cobranca.valor)}* _(30%)_")
        restante = Decimal(op.valor_estimado) - Decimal(cobranca.valor)
        if restante > 0:
            linhas.append(f"🏡 O restante (R$ {_brl(restante)}) você paga na chegada.")
    else:
        linhas.append(f"🔒 Sinal para garantir a data: *R$ {_brl(cobranca.valor)}* _(30%)_")

    linhas += [
        "",
        "É só pagar o sinal e a data fica *travada no seu nome* 👇",
        link,
        "",
        "Qualquer ajuste de datas ou de quarto, me chama por aqui. "
        "Vai ser um prazer receber você 🌿",
    ]
    return "\n".join(linhas)


def resumo_da_conversa(oportunidade, limite=8):
    """Últimas mensagens do WhatsApp do lead — para o bloco 'O que combinamos'.

    Devolve [{'quem','texto','quando'}] em ordem cronológica. Degrada para [] sem
    conversa (WhatsApp inativo ou lead sem histórico).
    """
    from .models import MensagemWhatsApp
    conv = getattr(oportunidade, "conversa_whatsapp", None)
    if conv is None:
        return []
    nome_cliente = (oportunidade.pessoa.nome or "").split()[0] if oportunidade.pessoa and oportunidade.pessoa.nome else "Cliente"
    msgs = list(conv.mensagens.order_by("-horario", "-id")[:limite])[::-1]
    return [{
        "quem": "Você" if m.direcao == MensagemWhatsApp.Direcao.SAIDA else nome_cliente,
        "texto": m.texto,
        "quando": m.horario,
    } for m in msgs]


def _link_sinal_da_oportunidade(oportunidade):
    """Link público de pagamento do sinal já existente (se houver) — não cria cobrança."""
    if not (oportunidade.cobranca_sinal_id and modulo_ativo(Modulo.PAGAMENTOS)):
        return None
    try:
        from django.urls import reverse

        from apps.pagamentos.models import Cobranca
        cob = Cobranca.objects.filter(pk=oportunidade.cobranca_sinal_id).first()
        if cob and cob.status == "pendente":
            return settings.SITE_PUBLIC_URL + reverse("pagamentos:pagar", args=[cob.token])
    except Exception:
        return None
    return None


def _contato_pousada():
    """Contatos oficiais (WhatsApp/telefone/e-mail) da ConfiguracaoSite — fonte única.

    Reply-to preferencial = caixa comercial monitorada. Degrada com defaults se o site
    não estiver disponível.
    """
    whatsapp = telefone = ""
    email = getattr(settings, "EMAIL_COMERCIAL_REPLY_TO", "") or "comercial@pousadavotesta.com.br"
    try:
        from apps.site.models import ConfiguracaoSite
        cfg = ConfiguracaoSite.load()
        whatsapp = "".join(c for c in (cfg.whatsapp or "") if c.isdigit())
        telefone = (cfg.telefone or "").strip()
        email = email or (cfg.email or "")
    except Exception:
        pass
    return {"whatsapp": whatsapp, "telefone": telefone, "email": email}


def montar_proposta_email(oportunidade, cobranca=None, link=None, corpo=None):
    """Monta o e-mail 1:1 da proposta (HTML + texto), reusando a cotação/valores do lead.

    `corpo` = texto de abertura editável pelo vendedor (None → padrão caloroso). O cartão
    da estadia e os valores são sempre renderizados dos dados (não do corpo).
    Devolve {assunto, corpo, html, texto}.
    """
    op = oportunidade
    nome = (op.pessoa.nome or "").split()[0] if op.pessoa and op.pessoa.nome else ""
    cot = op.ultima_cotacao
    quarto = cot.tipo_uh.nome if cot else op.get_tipo_interesse_display()

    periodo = noites = None
    if op.checkin_previsto and op.checkout_previsto:
        periodo = f"{op.checkin_previsto:%d/%m} → {op.checkout_previsto:%d/%m/%Y}"
        noites = (op.checkout_previsto - op.checkin_previsto).days

    total_br = _brl(op.valor_estimado) if op.valor_estimado else None
    sinal_br = restante_br = None
    if cobranca is not None:
        sinal_br = _brl(cobranca.valor)
        if op.valor_estimado:
            restante = Decimal(op.valor_estimado) - Decimal(cobranca.valor)
            if restante > 0:
                restante_br = _brl(restante)

    if link is None:
        link = _link_sinal_da_oportunidade(op)

    assunto = f"Sua estadia na Pousada Vô Testa — {quarto}"
    if periodo:
        assunto += f" ({op.checkin_previsto:%d/%m}–{op.checkout_previsto:%d/%m})"

    if corpo is None:
        saud = f"Oi, {nome}!" if nome else "Olá!"
        corpo = (
            f"{saud} Como combinamos por aqui, deixei tudo por escrito abaixo.\n\n"
            "Qualquer ajuste de datas ou de quarto, é só responder este e-mail — "
            "vai ser um prazer receber você."
        )

    # Links de resposta no rodapé (o cliente clica e já fala com a gente).
    from urllib.parse import quote
    contato = _contato_pousada()
    msg_wa = f"Olá! Sobre a proposta da {quarto}" + (f" ({periodo})" if periodo else "")
    url_whatsapp = (f"https://wa.me/{contato['whatsapp']}?text={quote(msg_wa)}"
                    if contato["whatsapp"] else "")
    url_email = (f"mailto:{contato['email']}?subject={quote('Re: ' + assunto)}"
                 if contato["email"] else "")

    corpo_paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    contexto = {
        "assunto": assunto, "corpo_paragrafos": corpo_paragrafos,
        "quarto": quarto, "periodo": periodo, "noites": noites,
        "pessoas": op.hospedes, "total_br": total_br, "sinal_br": sinal_br,
        "restante_br": restante_br, "link": link,
        "cta_texto": "Pagar o sinal e garantir a data",
        "url_whatsapp": url_whatsapp, "url_email": url_email,
        "email_contato": contato["email"], "telefone": contato["telefone"],
    }
    html = render_to_string("comercial/email/proposta.html", contexto)

    # Fallback texto puro (clientes sem HTML) — espelha o cartão.
    linhas = list(corpo_paragrafos)
    linhas.append(f"\n🏕 {quarto}")
    if periodo:
        linhas.append(f"🗓 {periodo}" + (f" · {noites} noites" if noites else ""))
    linhas.append(f"👥 {op.hospedes} pessoas")
    if total_br:
        linhas.append(f"Total da estadia: R$ {total_br}")
    if sinal_br:
        linhas.append(f"Sinal para garantir: R$ {sinal_br}")
    if restante_br:
        linhas.append(f"Restante na chegada: R$ {restante_br}")
    if link:
        linhas.append(f"\nPagar o sinal: {link}")
    if url_whatsapp:
        linhas.append(f"\nFalar no WhatsApp: {url_whatsapp}")
    if contato["email"]:
        linhas.append(f"Ou responda este e-mail / escreva para {contato['email']}")
    texto = "\n".join(linhas)

    return {"assunto": assunto, "corpo": corpo, "html": html, "texto": texto}


def _processar_envio_email(envio_id, para, assunto, html, texto, remetente, reply_to,
                           usuario_id, oportunidade_id, headers=None):
    """Faz o envio pelo gateway e atualiza o EnvioEmail (re-busca objetos por id)."""
    from .email_gateways import get_email_gateway
    from .models import EnvioEmail

    envio = EnvioEmail.objects.filter(pk=envio_id).first()
    if envio is None:
        return
    try:
        res = get_email_gateway().enviar(
            para=para, assunto=assunto, html=html, texto=texto,
            remetente=remetente, reply_to=reply_to, headers=headers)
        envio.status = EnvioEmail.Status.ENVIADO
        envio.message_id = res.get("message_id", "")
        envio.enviado_em = timezone.now()
    except Exception as e:  # noqa: BLE001 — best-effort, registra o erro
        envio.status = EnvioEmail.Status.ERRO
        envio.erro = str(e)
    envio.save(update_fields=["status", "message_id", "enviado_em", "erro"])
    if envio.status == EnvioEmail.Status.ENVIADO and oportunidade_id:
        op = Oportunidade.objects.filter(pk=oportunidade_id).first()
        user = Usuario.objects.filter(pk=usuario_id).first() if usuario_id else None
        if op:
            _log_evento(op, user, f"enviou e-mail — {assunto}")


def _envio_email_em_thread(*args):
    """Wrapper de thread: processa e fecha a conexão de banco própria da thread."""
    from django.db import connections
    try:
        _processar_envio_email(*args)
    finally:
        connections.close_all()


def enviar_email(*, para, assunto, html, texto, usuario, oportunidade=None,
                 pessoa=None, remetente=None, reply_to=None, assincrono=False,
                 campanha=None, headers=None):
    """Grava o EnvioEmail e dispara pelo gateway.

    `assincrono=True` → não bloqueia o request: cria o registro como 'pendente', envia
    numa thread de fundo (SMTP é lento) e atualiza o status. Best-effort: erro do
    provedor não estoura — fica no EnvioEmail. Evento na trilha só quando dá certo.
    """
    from .models import EnvioEmail

    remetente = remetente or getattr(
        settings, "EMAIL_COMERCIAL_FROM", settings.DEFAULT_FROM_EMAIL)
    reply_to = reply_to or getattr(settings, "EMAIL_COMERCIAL_REPLY_TO", "") or None
    if pessoa is None and oportunidade is not None:
        pessoa = oportunidade.pessoa

    envio = EnvioEmail.objects.create(
        oportunidade=oportunidade, campanha=campanha, pessoa=pessoa, email=para,
        assunto=assunto[:200], autor=usuario, status=EnvioEmail.Status.PENDENTE)
    args = (envio.pk, para, assunto, html, texto, remetente, reply_to,
            usuario.pk if usuario else None,
            oportunidade.pk if oportunidade else None, headers)
    if assincrono:
        import threading
        threading.Thread(target=_envio_email_em_thread, args=args, daemon=True).start()
    else:
        _processar_envio_email(*args)
        envio.refresh_from_db()
    return envio


def templates_mensagem(oportunidade):
    """Textos copiáveis (WhatsApp / e-mail) — P2.2."""
    p = oportunidade.pessoa
    nome = p.nome.split()[0] if p.nome else "olá"
    periodo = "datas a combinar"
    if oportunidade.checkin_previsto and oportunidade.checkout_previsto:
        periodo = (
            f"{oportunidade.checkin_previsto:%d/%m/%Y} a "
            f"{oportunidade.checkout_previsto:%d/%m/%Y}"
        )
    valor = f"R$ {oportunidade.valor_estimado}"
    cot = oportunidade.ultima_cotacao
    if cot:
        valor = f"R$ {cot.valor_total} (diária R$ {cot.valor_diaria}, válida até {cot.validade:%d/%m})"
        periodo = f"{cot.checkin:%d/%m/%Y} a {cot.checkout:%d/%m/%Y}"
    proposta = (
        f"Olá, {nome}! Aqui é da Pousada Vô Testa.\n\n"
        f"Segue proposta para {periodo}: {valor}.\n"
        f"Qualquer ajuste de datas ou tipo de quarto, me avise.\n\n"
        f"Aguardo seu retorno 🌿"
    )
    email_proposta = (
        f"Assunto: Proposta — Pousada Vô Testa\n\n"
        f"Olá, {p.nome},\n\n"
        f"Enviamos a cotação referente a {periodo}.\n"
        f"Valor estimado: {valor}.\n\n"
        f"Ficamos à disposição para confirmar a reserva.\n\n"
        f"Atenciosamente,\nPousada Vô Testa"
    )
    obrigado = (
        f"Olá, {nome}! Obrigado pela estadia na Pousada Vô Testa.\n"
        f"Sua opinião importa — quando puder, avalie-nos (NPS) pelo portal do hóspede.\n"
        f"Esperamos você de novo 🌿"
    )
    return {
        "whatsapp_proposta": proposta,
        "email_proposta": email_proposta,
        "whatsapp_obrigado": obrigado,
        "telefone": p.telefone or "",
        "email": p.email or "",
    }


@transaction.atomic
def anotar_reserva_encerrada(*, reserva_id, evento, motivo="", usuario=None):
    """P2.1 / P2.3 — chamado pelos receivers dos sinais de Reservas."""
    if not modulo_ativo(Modulo.COMERCIAL):
        return None
    op = Oportunidade.objects.filter(reserva_id=reserva_id).first()
    if not op:
        return None
    user = usuario or op.criado_por
    if evento in ("cancelada", "no_show"):
        texto = f"Reserva #{reserva_id} {evento}"
        if motivo:
            texto += f": {motivo[:180]}"
        registrar_atividade(
            oportunidade=op, usuario=user, tipo=AtividadeComercial.Tipo.SISTEMA,
            descricao=texto,
        )
        if op.status == Oportunidade.Status.GANHA:
            # Reabre follow-up sem desfazer o ganho histórico — tarefa de reabordagem.
            registrar_atividade(
                oportunidade=op, usuario=user, tipo=AtividadeComercial.Tipo.TAREFA,
                descricao=f"Reabordar lead após {evento} da reserva #{reserva_id}",
                quando=timezone.now() + timedelta(hours=SLA_FOLLOWUP_HORAS),
                concluida=False,
            )
        return op

    if evento == "checkout":
        registrar_atividade(
            oportunidade=op, usuario=user, tipo=AtividadeComercial.Tipo.SISTEMA,
            descricao=(
                f"Check-out da reserva #{reserva_id} — hand-off retenção/NPS "
                f"(CRM do Hóspede / portal)."
            ),
        )
        if not op.nps_convidado_em:
            op.nps_convidado_em = timezone.now()
            op.save(update_fields=["nps_convidado_em", "atualizado_em"])
            registrar_atividade(
                oportunidade=op, usuario=user, tipo=AtividadeComercial.Tipo.TAREFA,
                descricao="Convidar NPS / campanha de retorno (CRM Hóspede)",
                quando=timezone.now() + timedelta(days=1),
                concluida=False,
            )
        return op
    return op


def tarefas_do_dia(responsavel=None):
    fim = timezone.now().replace(hour=23, minute=59, second=59)
    qs = AtividadeComercial.objects.filter(
        concluida=False, quando__lte=fim,
        oportunidade__status=Oportunidade.Status.ABERTA,
    ).select_related("oportunidade", "oportunidade__pessoa", "responsavel")
    if responsavel is not None:
        qs = qs.filter(responsavel=responsavel)
    return qs.order_by("quando")


def pendencias_auditoria():
    achados = []
    agora = timezone.now()
    limite_parada = agora - timedelta(days=DIAS_PARADA)
    sla_contato = agora - timedelta(hours=SLA_PRIMEIRO_CONTATO_HORAS)
    sla_follow = agora - timedelta(hours=SLA_FOLLOWUP_HORAS)
    abertas = Oportunidade.objects.filter(
        status=Oportunidade.Status.ABERTA
    ).select_related("pessoa", "etapa")
    for op in abertas:
        tem_tarefa = op.atividades.filter(concluida=False).exists()
        if not tem_tarefa:
            achados.append({
                "area": "Comercial", "gravidade": "media", "tipo": "oportunidade_sem_tarefa",
                "descricao": f"Oportunidade '{op.titulo}' ({op.pessoa.nome}) sem próxima ação agendada.",
                "url": _url("comercial:oportunidade", op.pk),
            })
        elif op.atualizado_em < limite_parada:
            achados.append({
                "area": "Comercial", "gravidade": "baixa", "tipo": "oportunidade_parada",
                "descricao": f"Oportunidade '{op.titulo}' ({op.pessoa.nome}) parada há mais de {DIAS_PARADA} dias.",
                "url": _url("comercial:oportunidade", op.pk),
            })
        # SLA 1º contato 24h — sem interação humana concluída
        if op.criado_em <= sla_contato:
            falou = op.atividades.filter(
                concluida=True,
                tipo__in=[
                    AtividadeComercial.Tipo.LIGACAO, AtividadeComercial.Tipo.WHATSAPP,
                    AtividadeComercial.Tipo.EMAIL, AtividadeComercial.Tipo.REUNIAO,
                    AtividadeComercial.Tipo.NOTA, AtividadeComercial.Tipo.COTACAO,
                ],
            ).exists()
            if not falou:
                achados.append({
                    "area": "Comercial", "gravidade": "alta", "tipo": "sla_primeiro_contato",
                    "descricao": (
                        f"SLA 24h: '{op.titulo}' ({op.pessoa.nome}) sem 1º contato."
                    ),
                    "url": _url("comercial:oportunidade", op.pk),
                })
        # Follow-up 48h: tarefa atrasada
        if op.atividades.filter(concluida=False, quando__lt=sla_follow).exists():
            achados.append({
                "area": "Comercial", "gravidade": "media", "tipo": "sla_followup",
                "descricao": (
                    f"SLA 48h: follow-up atrasado em '{op.titulo}' ({op.pessoa.nome})."
                ),
                "url": _url("comercial:oportunidade", op.pk),
            })
        # Telefone incompleto/inválido (passivo de antes da validação). Aceita fixo
        # (agência/empresa) — só acusa número que falha até o critério leniente.
        tel = (op.pessoa.telefone or "").strip()
        if tel and not _telefone_ok(tel):
            achados.append({
                "area": "Comercial", "gravidade": "media", "tipo": "telefone_incompleto",
                "descricao": (
                    f"Telefone incompleto/inválido em '{op.titulo}' "
                    f"({op.pessoa.nome}): {tel}"
                ),
                "url": _url("comercial:oportunidade", op.pk),
            })
    return achados


def _telefone_ok(valor) -> bool:
    """True se o telefone passa na validação (celular 11 díg OU fixo 10 díg)."""
    from django.core.exceptions import ValidationError

    from apps.nucleo.validadores import validar_telefone_br
    try:
        validar_telefone_br(valor, aceitar_fixo=True)
        return True
    except ValidationError:
        return False


def relatorio_funil(inicio, fim):
    criadas = Oportunidade.objects.filter(criado_em__date__range=(inicio, fim))
    ganhas = criadas.filter(status=Oportunidade.Status.GANHA).count()
    perdidas = criadas.filter(status=Oportunidade.Status.PERDIDA).count()
    total = criadas.count()
    fechadas = ganhas + perdidas
    conversao = (Decimal(ganhas) / Decimal(fechadas) * 100) if fechadas else Decimal("0")
    valor_ganho = criadas.filter(status=Oportunidade.Status.GANHA).aggregate(
        t=Sum("valor_estimado"))["t"] or Decimal("0.00")
    por_etapa = (
        Oportunidade.objects.filter(status=Oportunidade.Status.ABERTA)
        .values("etapa__nome").annotate(n=Count("id"), valor=Sum("valor_estimado"))
        .order_by("etapa__ordem")
    )
    return {
        "total": total, "ganhas": ganhas, "perdidas": perdidas,
        "conversao": conversao.quantize(Decimal("0.1")), "valor_ganho": valor_ganho,
        "por_etapa": list(por_etapa),
    }


def dados_gestao(inicio, fim):
    """P3 — score médio, tempo por etapa, forecast × realizado × meta."""
    abertas = Oportunidade.objects.filter(status=Oportunidade.Status.ABERTA)
    forecast = sum((o.valor_ponderado for o in abertas.select_related("etapa")),
                   Decimal("0.00"))
    ganhas_mes = Oportunidade.objects.filter(
        status=Oportunidade.Status.GANHA, fechado_em__date__range=(inicio, fim),
    )
    realizado = ganhas_mes.aggregate(t=Sum("valor_estimado"))["t"] or Decimal("0.00")
    mes_ref = inicio.replace(day=1)
    meta = MetaComercial.objects.filter(mes=mes_ref).first()
    valor_meta = meta.valor_meta if meta else Decimal("0.00")

    # Tempo médio (horas) por etapa nas permanências finalizadas do período
    duracao = ExpressionWrapper(
        F("finalizado_em") - F("iniciado_em"), output_field=DurationField(),
    )
    tempos = (
        PermanenciaEtapa.objects.filter(
            finalizado_em__isnull=False,
            iniciado_em__date__lte=fim,
            finalizado_em__date__gte=inicio,
        )
        .values("etapa__nome", "etapa__ordem")
        .annotate(media=Avg(duracao))
        .order_by("etapa__ordem")
    )
    tempo_por_etapa = []
    for row in tempos:
        media = row["media"]
        horas = round(media.total_seconds() / 3600, 1) if media else 0
        tempo_por_etapa.append({"etapa": row["etapa__nome"], "horas": horas})

    score_medio = abertas.aggregate(m=Avg("score"))["m"] or 0
    top_scores = list(
        abertas.select_related("pessoa", "etapa").order_by("-score", "-valor_estimado")[:8]
    )
    return {
        "forecast": forecast,
        "realizado": realizado,
        "meta": valor_meta,
        "atingimento": (
            (realizado / valor_meta * 100).quantize(Decimal("0.1"))
            if valor_meta else Decimal("0")
        ),
        "tempo_por_etapa": tempo_por_etapa,
        "score_medio": round(float(score_medio), 1),
        "top_scores": top_scores,
        "ganhos_qtd": ganhas_mes.count(),
        "meta_qtd": meta.oportunidades_meta if meta else 0,
    }


def definir_meta(*, mes, valor_meta, oportunidades_meta=0):
    mes = mes.replace(day=1)
    obj, _ = MetaComercial.objects.update_or_create(
        mes=mes,
        defaults={
            "valor_meta": Decimal(str(valor_meta or 0)),
            "oportunidades_meta": int(oportunidades_meta or 0),
        },
    )
    return obj


def _url(nome, *args):
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse(nome, args=args)
    except NoReverseMatch:
        return None


def registrar_visita_pagina(pagina) -> None:
    """Conta +1 visita na Página de Captação (atômico, sem corrida)."""
    from .models import PaginaCaptacao

    PaginaCaptacao.objects.filter(pk=pagina.pk).update(visitas=F("visitas") + 1)


def registrar_gasto(*, campanha, data, valor, usuario, origem_dado="manual"):
    """Lança um gasto de anúncio numa campanha (Fase A: manual)."""
    from decimal import Decimal as _D

    from .models import GastoDiario
    valor = _D(str(valor))
    if valor <= 0:
        raise ValidationError("O valor do gasto deve ser positivo.")
    return GastoDiario.objects.create(
        campanha=campanha, data=data, valor=valor,
        origem=origem_dado, criado_por=usuario,
    )


def enviar_conversao(oportunidade, evento, valor=None, forcar=False):
    """Devolve a conversão (lead/compra) ao provedor de mídia. Best-effort e idempotente.

    Só envia quando há identificador de clique (fbclid/gclid) no rastreio — é o que
    permite ao Meta/Google casar a venda ao anúncio. Nunca levanta exceção ao chamador.
    Fase B do Gestor de Impulsionamento.
    """
    import time

    from django.conf import settings

    from .midia_gateways import get_midia_gateway, hash_email, hash_telefone
    from .models import ConversaoEnviada

    rastreio = oportunidade.origem_rastreio or {}
    fbclid = rastreio.get("fbclid") or ""
    gclid = rastreio.get("gclid") or ""
    if not (fbclid or gclid):
        return None  # sem clique rastreado não há o que atribuir

    if not forcar and ConversaoEnviada.objects.filter(
        oportunidade=oportunidade, evento=evento,
        status=ConversaoEnviada.Status.ENVIADA,
    ).exists():
        return None  # já enviada

    event_time = int(time.time())
    pessoa = oportunidade.pessoa
    evento_dict = {
        "evento": evento,
        "ref": oportunidade.pk,
        "event_id": f"{evento}-{oportunidade.pk}",
        "event_time": event_time,
        "valor": float(valor) if valor else None,
        "email_hash": hash_email(pessoa.email),
        "telefone_hash": hash_telefone(pessoa.telefone),
        "fbc": f"fb.1.{event_time}.{fbclid}" if fbclid else "",
        "gclid": gclid,
        "landing_url": rastreio.get("landing_url", ""),
    }
    provedor = getattr(settings, "MIDIA_GATEWAY", "simulado")
    try:
        res = get_midia_gateway().enviar_conversao(evento_dict)
    except Exception as e:  # provedor sem credencial / erro de rede
        res = {"ok": False, "erro": str(e)[:400]}
    return ConversaoEnviada.objects.create(
        oportunidade=oportunidade, evento=evento, provedor=provedor,
        status=(ConversaoEnviada.Status.ENVIADA if res.get("ok")
                else ConversaoEnviada.Status.ERRO),
        valor=valor, id_externo=(res.get("id") or "")[:120], erro=res.get("erro", "") or "",
    )


def _estagio_key(etapa) -> str:
    """Nome estável do estágio p/ event_name da Meta (ex.: 'Cotação enviada'→'cotacao_enviada')."""
    from django.utils.text import slugify
    return slugify(etapa.nome).replace("-", "_") or "estagio"


def enviar_evento_crm(oportunidade, estagio, quando=None):
    """Manda um evento de ESTÁGIO do lead à Meta (CAPI, integração 'leads qualificados').
    Casa por e-mail/telefone hasheados — NÃO exige fbclid. Best-effort, nunca estoura."""
    import time

    from django.conf import settings

    from .midia_gateways import get_midia_gateway, hash_email, hash_telefone
    p = oportunidade.pessoa
    evento = {
        "estagio": estagio,
        "ref": oportunidade.pk,
        "event_time": int(quando.timestamp()) if quando else int(time.time()),
        "email_hash": hash_email(p.email),
        "telefone_hash": hash_telefone(p.telefone),
        "crm_nome": getattr(settings, "META_CRM_NOME", "Pousada Vô Testa CRM"),
    }
    try:
        return get_midia_gateway().enviar_evento_crm(evento)
    except Exception as e:  # noqa: BLE001 — best-effort, provedor sem credencial/rede
        return {"ok": False, "erro": str(e)[:200]}


def _upsert_gastos_sincronizados(campanha, dados) -> int:
    """Grava/atualiza os gastos vindos da API (origem=sincronizado). Idempotente
    por (campanha, data): re-sincronizar substitui o valor, não duplica."""
    from decimal import Decimal as _D

    from .models import GastoDiario
    n = 0
    for item in dados or []:
        data = item.get("data")
        if not data:
            continue
        try:
            valor = _D(str(item.get("valor") or "0"))
        except Exception:
            continue
        GastoDiario.objects.update_or_create(
            campanha=campanha, data=data, origem=GastoDiario.Origem.SINCRONIZADO,
            defaults={"valor": valor, "criado_por": campanha.criado_por},
        )
        n += 1
    return n


def sincronizar_gastos(campanha=None, dias=7) -> int:
    """Puxa o gasto das plataformas para as campanhas (Fase C). Best-effort.

    Com MIDIA_GATEWAY=simulado (padrão) é no-op (modo manual). Com meta/google e a
    campanha com `id_externo`, busca o gasto diário dos últimos `dias` e grava.
    Retorna o número de dias-campanha sincronizados.
    """
    from datetime import timedelta

    from .midia_gateways import get_midia_gateway
    from .models import Campanha

    ate = timezone.localdate()
    desde = ate - timedelta(days=dias)
    qs = [campanha] if campanha else list(Campanha.objects.filter(ativa=True))
    total = 0
    for camp in qs:
        try:
            dados = get_midia_gateway().sincronizar_gastos(camp, desde, ate)
        except Exception as e:
            registrar_auditoria(None, "gasto_sincronizacao_falha", camp, {"erro": str(e)[:200]})
            continue
        total += _upsert_gastos_sincronizados(camp, dados)
    return total


# ───────────────── WhatsApp no funil (MVP simulado) + Respostas Rápidas ─────────────────

def abrir_conversa_whatsapp(oportunidade):
    from .models import ConversaWhatsApp
    conv, _ = ConversaWhatsApp.objects.get_or_create(
        oportunidade=oportunidade,
        defaults={"telefone": oportunidade.pessoa.telefone or ""},
    )
    return conv


def _nota_sistema_lead(op, descricao):
    """Nota de SISTEMA na timeline, autorada pelo usuário de sistema. Diferente de
    `_log_evento` (que pula usuários de sistema): estes eventos automáticos — reativação,
    recompra — DEVEM aparecer no histórico do lead."""
    AtividadeComercial.objects.create(
        oportunidade=op, tipo=AtividadeComercial.Tipo.SISTEMA,
        descricao=descricao[:255], quando=timezone.now(), concluida=True,
        responsavel=op.responsavel, criado_por=_usuario_site())


def _criar_lead_whatsapp(*, telefone, nome="", pessoa=None, reativacao=False):
    """Número novo escreveu no WhatsApp → nasce um lead no funil (origem=whatsapp).

    Se já existe a Pessoa (mesmo telefone) mas sem nenhuma oportunidade, cria a
    oportunidade para ela; senão cria Pessoa + oportunidade. Nome = perfil do WhatsApp,
    ou '(DDD) número' quando o cliente não compartilha o perfil. `reativacao=True`
    (recompra de hóspede que já fechou) carimba o selo 'Reativado'.
    """
    from apps.nucleo.models import Pessoa
    if pessoa is None:
        nome_final = ((nome or "").strip() or f"WhatsApp {_formatar_tel_br(telefone)}")[:150]
        pessoa = Pessoa.objects.create(nome=nome_final, telefone=_norm_tel(telefone))
    # titulo capado em 120 (max_length do campo) — nome de agência/empresa pode ser longo
    # e estourar o insert, e o webhook engole o erro (perderia a mensagem).
    op = criar_oportunidade(
        usuario=_usuario_site(), pessoa=pessoa,
        titulo=f"WhatsApp — {pessoa.nome}"[:120], origem=Oportunidade.Origem.WHATSAPP,
        disparar_crm=False,
    )
    if reativacao:
        op.reativada_em = timezone.now()
        op.save(update_fields=["reativada_em", "atualizado_em"])
        _nota_sistema_lead(
            op, "♻️ Reativado — hóspede anterior voltou a falar no WhatsApp (recompra).")
    return op


def _reativar_oportunidade(op):
    """Cliente com oportunidade PERDIDA voltou a falar → reabre o MESMO card no funil
    ativo (etapa inicial 'Novo lead'), carimba `reativada_em` e guarda o motivo da perda
    anterior na timeline. Preserva a conversa (1:1 com a oportunidade)."""
    primeira = etapas().first()  # ordering por 'ordem' → "Novo lead"
    if primeira is None:
        return op  # sem funil configurado: não reabre (melhor que estourar o webhook)
    motivo_anterior = op.motivo_perda.nome if op.motivo_perda_id else "não informado"
    _fechar_permanencia(op)
    op.status = Oportunidade.Status.ABERTA
    op.etapa = primeira
    op.fechado_em = None
    op.reativada_em = timezone.now()
    op.motivo_perda = None
    op.motivo_perda_detalhe = ""
    op.save(update_fields=["status", "etapa", "fechado_em", "reativada_em",
                           "motivo_perda", "motivo_perda_detalhe", "atualizado_em"])
    _abrir_permanencia(op, primeira)
    atualizar_score(op)
    _nota_sistema_lead(
        op, f"♻️ Reativado — cliente voltou a falar no WhatsApp. "
            f"Perda anterior: {motivo_anterior}.")
    return op


def _ext_audio(mime):
    """Extensão de arquivo a partir do mime do áudio do WhatsApp."""
    m = (mime or "").lower()
    if "ogg" in m:
        return ".ogg"
    if "mpeg" in m or "mp3" in m:
        return ".mp3"
    if "mp4" in m or "m4a" in m or "aac" in m:
        return ".m4a"
    if "amr" in m:
        return ".amr"
    return ".bin"


def _ext_imagem(mime):
    """Extensão de arquivo a partir do mime da imagem do WhatsApp."""
    m = (mime or "").lower()
    if "png" in m:
        return ".png"
    if "webp" in m:
        return ".webp"
    if "gif" in m:
        return ".gif"
    return ".jpg"


def _ext_midia(tipo, mime):
    """Extensão do arquivo conforme o tipo da mídia (imagem/áudio)."""
    return _ext_imagem(mime) if tipo == "imagem" else _ext_audio(mime)


def _transcode_para_ogg(conteudo, mime):
    """Formatos aceitos pela Meta: ogg(opus)/mp3/mp4/aac/amr. O Chrome grava **webm**, que
    a Meta NÃO aceita → transcodifica p/ ogg/opus com ffmpeg. Best-effort: sem ffmpeg ou se
    falhar, devolve o original (aí o envio pode dar erro, mas nunca estoura)."""
    import os
    import shutil
    import subprocess
    import tempfile
    m = (mime or "").lower()
    if any(s in m for s in ("ogg", "mpeg", "mp3", "mp4", "aac", "amr", "m4a")):
        return conteudo, mime
    if not shutil.which("ffmpeg"):
        return conteudo, mime
    inp = out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".in", delete=False) as fin:
            fin.write(conteudo)
            inp = fin.name
        out = inp + ".ogg"
        subprocess.run(["ffmpeg", "-y", "-i", inp, "-c:a", "libopus", "-b:a", "32k", out],
                       check=True, capture_output=True, timeout=30)
        with open(out, "rb") as f:
            return f.read(), "audio/ogg"
    except Exception:  # noqa: BLE001
        return conteudo, mime
    finally:
        for p in (inp, out):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


def receber_mensagem_whatsapp(*, oportunidade=None, telefone=None, texto,
                              id_externo="", quando=None, nome="", permitir_criar=True,
                              tipo="texto", midia_id="", midia_mime="", midia_voz=False):
    """Registra uma mensagem RECEBIDA do cliente (webhook real ou simulação do MVP).

    Idempotente por id_externo (atalho + constraint de banco). Abre a janela de 24h e
    incrementa não-lidas. Se o número não bate com nenhuma Pessoa e `permitir_criar`,
    CRIA um lead no funil (origem=whatsapp) — "cliente te chama → cai no funil". `nome` é
    o nome do perfil do WhatsApp (quando a Meta envia). `permitir_criar=False` NÃO cria
    lead para número novo (tipos que não são conteúdo do cliente — reação/status/… — não
    devem virar lead-lixo); mensagem de número já conhecido segue sendo registrada.
    `tipo="audio"` + `midia_id` baixa a mídia e guarda no storage (best-effort).
    """
    from django.core.files.base import ContentFile
    from django.db import IntegrityError

    from .models import MensagemWhatsApp, Oportunidade

    # Idempotência (atalho rápido): webhook já processado não refaz nada.
    if id_externo and MensagemWhatsApp.objects.filter(id_externo=id_externo).exists():
        return None

    # Baixa a mídia ANTES da transação (rede não deve segurar o lock do banco).
    conteudo_midia = None
    if tipo in ("audio", "imagem") and midia_id:
        from .whatsapp_gateways import get_whatsapp_gateway
        try:
            conteudo_midia, mime_baixado = get_whatsapp_gateway().baixar_midia(midia_id)
            if mime_baixado and not midia_mime:
                midia_mime = mime_baixado
        except Exception:  # noqa: BLE001 — download best-effort; segue sem o binário
            conteudo_midia = None

    msg = None
    try:
        with transaction.atomic():
            op = oportunidade
            if op is None and telefone:
                pessoa = _pessoa_por_telefone_qualquer(telefone)
                if pessoa:
                    base = Oportunidade.objects.filter(pessoa=pessoa)
                    aberta = (base.filter(status=Oportunidade.Status.ABERTA)
                              .order_by("-criado_em").first())
                    if aberta is not None:
                        op = aberta  # conversa em andamento: anexa (sem carimbo)
                    else:
                        recente = base.order_by("-criado_em").first()
                        if not permitir_criar:
                            # tipo sem conteúdo (reação/status): só anexa ao card mais
                            # recente, se existir — não reabre nem cria lead.
                            op = recente
                        elif recente is None:  # Pessoa sem nenhuma oportunidade
                            op = _criar_lead_whatsapp(
                                telefone=telefone, nome=nome, pessoa=pessoa)
                        elif recente.status == Oportunidade.Status.PERDIDA:
                            op = _reativar_oportunidade(recente)  # voltou a falar → reabre
                        else:  # GANHA → nova oportunidade de recompra
                            op = _criar_lead_whatsapp(
                                telefone=telefone, nome=nome, pessoa=pessoa, reativacao=True)
                elif permitir_criar:
                    op = _criar_lead_whatsapp(telefone=telefone, nome=nome)
            if op is None:
                return None
            conv = abrir_conversa_whatsapp(op)
            quando_ = quando or timezone.now()
            msg = MensagemWhatsApp.objects.create(
                conversa=conv, direcao=MensagemWhatsApp.Direcao.ENTRADA,
                tipo=tipo, texto=texto.strip(), status=MensagemWhatsApp.Status.RECEBIDA,
                id_externo=id_externo, horario=quando_,
                midia_id_externo=midia_id, midia_mime=midia_mime, midia_voz=midia_voz,
            )
            conv.ultima_msg_cliente_em = quando_
            conv.nao_lidas = (conv.nao_lidas or 0) + 1
            conv.save(update_fields=["ultima_msg_cliente_em", "nao_lidas", "atualizado_em"])
    except IntegrityError:
        # Corrida: outra entrega do mesmo wamid venceu e já gravou (viola a unique de
        # id_externo). A transação inteira — lead inclusive — é desfeita, sem duplicata.
        return None

    # Salva o binário no storage FORA da transação (best-effort): se falhar, fica o
    # midia_id_externo gravado pra reprocessar depois.
    if msg is not None and conteudo_midia is not None:
        try:
            msg.midia_arquivo.save(
                f"wa_{msg.id}{_ext_midia(tipo, midia_mime)}",
                ContentFile(conteudo_midia), save=True)
        except Exception:  # noqa: BLE001
            pass
    return msg


def enviar_mensagem_whatsapp(*, conversa, texto, usuario):
    """Envia uma resposta pelo gateway (best-effort). Quem responde primeiro assume o lead."""
    from .models import MensagemWhatsApp
    from .whatsapp_gateways import get_whatsapp_gateway

    texto = (texto or "").strip()
    if not texto:
        raise ValidationError("Escreva uma mensagem.")
    # Fora do simulado, a Meta só aceita texto livre dentro da janela de 24h.
    if (getattr(settings, "WHATSAPP_GATEWAY", "simulado") != "simulado"
            and not conversa.janela_aberta):
        raise ValidationError(
            "Fora da janela de 24h: o cliente não fala há mais de 24h. Reabra a "
            "conversa com um template aprovado.")
    assumir_lead(conversa.oportunidade, usuario)  # quem responde primeiro assume
    try:
        res = get_whatsapp_gateway().enviar(conversa, texto)
    except Exception as e:
        res = {"ok": False, "erro": str(e)[:300]}
    msg = MensagemWhatsApp.objects.create(
        conversa=conversa, direcao=MensagemWhatsApp.Direcao.SAIDA, texto=texto,
        status=(MensagemWhatsApp.Status.ENVIADA if res.get("ok")
                else MensagemWhatsApp.Status.ERRO),
        id_externo=(res.get("id") or "")[:120], autor=usuario, horario=timezone.now(),
    )
    conversa.nao_lidas = 0
    conversa.save(update_fields=["nao_lidas", "atualizado_em"])
    return msg


def enviar_audio_whatsapp(*, conversa, arquivo, usuario):
    """Envia um áudio (voz) pelo gateway. Só dentro da janela de 24h (áudio não vai por
    template). Guarda o próprio áudio enviado pra reproduzir no histórico."""
    from django.core.files.base import ContentFile

    from .models import MensagemWhatsApp
    from .whatsapp_gateways import get_whatsapp_gateway

    conteudo = arquivo.read()
    if not conteudo:
        raise ValidationError("Áudio vazio.")
    if len(conteudo) > 16 * 1024 * 1024:
        raise ValidationError("Áudio acima do limite de 16 MB.")
    if (getattr(settings, "WHATSAPP_GATEWAY", "simulado") != "simulado"
            and not conversa.janela_aberta):
        raise ValidationError(
            "Fora da janela de 24h: o cliente não fala há mais de 24h. Áudio só dentro "
            "da janela (não existe template de áudio).")
    mime = getattr(arquivo, "content_type", "") or "audio/ogg"
    conteudo, mime = _transcode_para_ogg(conteudo, mime)  # webm (Chrome) → ogg/opus
    gw = get_whatsapp_gateway()
    assumir_lead(conversa.oportunidade, usuario)  # quem responde primeiro assume
    try:
        up = gw.upload_midia(conteudo, mime, "audio" + _ext_audio(mime))
        res = (gw.enviar_audio(conversa, up["id"]) if up.get("ok")
               else {"ok": False, "erro": up.get("erro", "upload falhou")})
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "erro": str(e)[:300]}
    msg = MensagemWhatsApp.objects.create(
        conversa=conversa, direcao=MensagemWhatsApp.Direcao.SAIDA,
        tipo=MensagemWhatsApp.Tipo.AUDIO, texto="[áudio]",
        status=(MensagemWhatsApp.Status.ENVIADA if res.get("ok")
                else MensagemWhatsApp.Status.ERRO),
        id_externo=(res.get("id") or "")[:120], autor=usuario,
        horario=timezone.now(), midia_mime=mime, midia_voz=True)
    try:
        msg.midia_arquivo.save(f"wa_out_{msg.id}{_ext_audio(mime)}",
                               ContentFile(conteudo), save=True)
    except Exception:  # noqa: BLE001
        pass
    conversa.nao_lidas = 0
    conversa.save(update_fields=["nao_lidas", "atualizado_em"])
    return msg


def enviar_imagem_whatsapp(*, conversa, arquivo, usuario, legenda=""):
    """Envia uma imagem pelo gateway. Só dentro da janela de 24h (imagem não vai por
    template). Guarda a imagem no histórico. Limite 5 MB (WhatsApp)."""
    from django.core.files.base import ContentFile

    from .models import MensagemWhatsApp
    from .whatsapp_gateways import get_whatsapp_gateway

    conteudo = arquivo.read()
    if not conteudo:
        raise ValidationError("Imagem vazia.")
    if len(conteudo) > 5 * 1024 * 1024:
        raise ValidationError("Imagem acima do limite de 5 MB (WhatsApp).")
    mime = (getattr(arquivo, "content_type", "") or "").lower()
    if not mime.startswith("image/") or "svg" in mime:
        raise ValidationError("Formato não aceito — envie JPG, PNG ou WEBP.")
    if (getattr(settings, "WHATSAPP_GATEWAY", "simulado") != "simulado"
            and not conversa.janela_aberta):
        raise ValidationError(
            "Fora da janela de 24h: o cliente não fala há mais de 24h. Imagem só dentro "
            "da janela (não existe template de imagem).")
    legenda = (legenda or "").strip()
    nome = (getattr(arquivo, "name", "") or ("imagem" + _ext_imagem(mime)))[:160]
    gw = get_whatsapp_gateway()
    assumir_lead(conversa.oportunidade, usuario)  # quem responde primeiro assume
    try:
        up = gw.upload_midia(conteudo, mime, nome)
        res = (gw.enviar_imagem(conversa, up["id"], legenda) if up.get("ok")
               else {"ok": False, "erro": up.get("erro", "upload falhou")})
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "erro": str(e)[:300]}
    msg = MensagemWhatsApp.objects.create(
        conversa=conversa, direcao=MensagemWhatsApp.Direcao.SAIDA,
        tipo=MensagemWhatsApp.Tipo.IMAGEM, texto=legenda,
        status=(MensagemWhatsApp.Status.ENVIADA if res.get("ok")
                else MensagemWhatsApp.Status.ERRO),
        id_externo=(res.get("id") or "")[:120], autor=usuario,
        horario=timezone.now(), midia_mime=mime, midia_nome=nome)
    try:
        msg.midia_arquivo.save(f"wa_out_{msg.id}{_ext_imagem(mime)}",
                               ContentFile(conteudo), save=True)
    except Exception:  # noqa: BLE001
        pass
    conversa.nao_lidas = 0
    conversa.save(update_fields=["nao_lidas", "atualizado_em"])
    return msg


def enviar_template_whatsapp(*, oportunidade, template, idioma="pt_BR",
                             variaveis=None, usuario=None):
    """Dispara um template APROVADO para o lead (inicia conversa / fora da janela 24h).

    Best-effort: registra a mensagem de saída (enviada/erro) e nunca estoura. Os
    templates são pré-aprovados na Meta; aqui só passamos nome + variáveis ({{1}}…).
    """
    from .models import MensagemWhatsApp
    from .whatsapp_gateways import get_whatsapp_gateway

    conv = abrir_conversa_whatsapp(oportunidade)
    telefone = conv.telefone or oportunidade.pessoa.telefone or ""
    variaveis = list(variaveis or [])
    try:
        res = get_whatsapp_gateway().enviar_template(
            telefone, template, idioma=idioma, variaveis=variaveis)
    except Exception as e:  # noqa: BLE001 — best-effort
        res = {"ok": False, "erro": str(e)[:300]}
    resumo = f"[modelo: {template}]" + (" · " + " · ".join(map(str, variaveis))
                                        if variaveis else "")
    msg = MensagemWhatsApp.objects.create(
        conversa=conv, direcao=MensagemWhatsApp.Direcao.SAIDA, texto=resumo,
        status=(MensagemWhatsApp.Status.ENVIADA if res.get("ok")
                else MensagemWhatsApp.Status.ERRO),
        id_externo=(res.get("id") or "")[:120], autor=usuario, horario=timezone.now(),
    )
    return msg


# Palavras que o cliente manda para sair da lista (opt-out LGPD).
_OPT_OUT = {"sair", "sair da lista", "parar", "cancelar", "descadastrar", "remover"}

# Tipos de mensagem que SÃO conteúdo autoral do cliente (abrem lead novo). Os demais
# (reaction, location, system, order, sticker…) só anexam a quem já existe.
_TIPOS_CONTEUDO_WHATSAPP = {"text", "button", "interactive", "audio", "image"}


def _atualizar_status_mensagem(id_externo, status_meta):
    """Atualiza o status de uma mensagem enviada pelo callback da Meta (delivered/read/failed)."""
    from .models import MensagemWhatsApp

    if not id_externo:
        return
    qs = MensagemWhatsApp.objects.filter(
        id_externo=id_externo, direcao=MensagemWhatsApp.Direcao.SAIDA,
    )
    if status_meta == "failed":
        qs.update(status=MensagemWhatsApp.Status.ERRO)
    else:
        # 'sent'/'delivered'/'read' → enviada, mas NUNCA reverte um 'failed' já
        # gravado (a Meta pode reordenar/reenviar callbacks do mesmo wamid).
        qs.exclude(status=MensagemWhatsApp.Status.ERRO).update(
            status=MensagemWhatsApp.Status.ENVIADA)


def processar_webhook_whatsapp(payload: dict) -> dict:
    """Processa o corpo do webhook da Meta: mensagens recebidas + status de entrega.

    Idempotente (via id_externo em receber_mensagem_whatsapp). Trata texto, botão e
    resposta interativa; detecta opt-out por palavra-chave.
    """
    from datetime import datetime

    resumo = {"mensagens": 0, "status": 0, "opt_out": 0}
    for entry in (payload.get("entry") or []):
        for ch in (entry.get("changes") or []):
            val = ch.get("value") or {}
            # Nome do perfil do WhatsApp por remetente (p/ nomear o lead novo).
            contatos = {
                c.get("wa_id"): ((c.get("profile") or {}).get("name") or "")
                for c in (val.get("contacts") or [])}
            for m in (val.get("messages") or []):
                telefone = m.get("from", "")
                wamid = m.get("id", "")
                tipo = m.get("type")
                tipo_msg, midia_id, midia_mime, midia_voz = "texto", "", "", False
                if tipo == "text":
                    texto = (m.get("text") or {}).get("body", "")
                elif tipo == "button":
                    texto = (m.get("button") or {}).get("text", "")
                elif tipo == "interactive":
                    inter = m.get("interactive") or {}
                    alvo = inter.get("button_reply") or inter.get("list_reply") or {}
                    texto = alvo.get("title", "")
                elif tipo == "audio":
                    au = m.get("audio") or {}
                    tipo_msg, midia_id = "audio", au.get("id", "")
                    midia_mime, midia_voz = au.get("mime_type", ""), bool(au.get("voice"))
                    texto = "[áudio]"
                elif tipo == "image":
                    im = m.get("image") or {}
                    tipo_msg, midia_id = "imagem", im.get("id", "")
                    midia_mime = im.get("mime_type", "")
                    texto = im.get("caption", "")  # legenda (pode ser vazia)
                else:
                    texto = f"[{tipo}]"
                quando = None
                try:
                    quando = datetime.fromtimestamp(int(m.get("timestamp")), tz=UTC)
                except (TypeError, ValueError):
                    pass
                # Só conteúdo autoral do cliente abre lead novo; reação/status/mídia de
                # sistema anexa a quem já existe, mas não cria lead-lixo.
                msg = receber_mensagem_whatsapp(
                    telefone=telefone,
                    texto=texto if tipo_msg in ("audio", "imagem") else (texto or "[sem texto]"),
                    id_externo=wamid, quando=quando,
                    nome=contatos.get(telefone, ""),
                    permitir_criar=tipo in _TIPOS_CONTEUDO_WHATSAPP,
                    tipo=tipo_msg, midia_id=midia_id, midia_mime=midia_mime,
                    midia_voz=midia_voz)
                if msg is not None:
                    resumo["mensagens"] += 1
                    if texto.strip().lower() in _OPT_OUT:
                        _marcar_opt_out(msg.conversa.oportunidade)
                        resumo["opt_out"] += 1
            for st in (val.get("statuses") or []):
                _atualizar_status_mensagem(st.get("id"), st.get("status"))
                resumo["status"] += 1
    return resumo


def _marcar_opt_out(oportunidade):
    """Cliente pediu para sair PELO WHATSAPP: desliga só o consentimento de WhatsApp
    (o e-mail é canal à parte, com seu próprio descadastro)."""
    pessoa = oportunidade.pessoa
    if pessoa.aceita_whatsapp:
        pessoa.aceita_whatsapp = False
        pessoa.save(update_fields=["aceita_whatsapp"])


def disparar_campanha_whatsapp(*, template, idioma="pt_BR", leads=None, usuario=None,
                               so_primeiro_nome=True, limite=None):
    """Dispara um template para uma lista de leads (best-effort). Respeita opt-in.

    `leads`: queryset de Oportunidade (default = abertas). Pula quem não tem telefone
    ou não deu opt-in de WhatsApp (`pessoa.aceita_whatsapp`). Devolve o resumo
    (enviados/pulados/erros).
    """
    from .models import MensagemWhatsApp, Oportunidade

    qs = leads if leads is not None else Oportunidade.objects.filter(
        status=Oportunidade.Status.ABERTA)
    resumo = {"enviados": 0, "pulados": 0, "erros": 0}
    for op in qs.select_related("pessoa"):
        pessoa = op.pessoa
        if not (pessoa.telefone or "").strip() or not pessoa.aceita_whatsapp:
            resumo["pulados"] += 1
            continue
        variaveis = [(pessoa.nome or "").split()[0]] if so_primeiro_nome else []
        msg = enviar_template_whatsapp(
            oportunidade=op, template=template, idioma=idioma,
            variaveis=variaveis, usuario=usuario)
        if msg.status == MensagemWhatsApp.Status.ENVIADA:
            resumo["enviados"] += 1
        else:
            resumo["erros"] += 1
        if limite and resumo["enviados"] >= limite:
            break
    return resumo


def aplicar_variaveis_resposta(texto, oportunidade) -> str:
    """Preenche {nome} {checkin} {checkout} {noites} {valor} {vagas} com dados do lead."""
    op = oportunidade
    nome = (op.pessoa.nome or "").split()[0] if op.pessoa.nome else ""
    ci = op.checkin_previsto.strftime("%d/%m") if op.checkin_previsto else "—"
    co = op.checkout_previsto.strftime("%d/%m") if op.checkout_previsto else "—"
    noites = ((op.checkout_previsto - op.checkin_previsto).days
              if op.checkin_previsto and op.checkout_previsto else 0)
    valor = (f"R$ {op.valor_estimado:.2f}".replace(".", ",")
             if op.valor_estimado else "a combinar")
    subs = {
        "{nome}": nome, "{checkin}": ci, "{checkout}": co,
        "{noites}": str(noites), "{valor}": valor, "{vagas}": "algumas",
    }
    for k, v in subs.items():
        texto = texto.replace(k, v)
    return texto


def respostas_rapidas_para(oportunidade):
    """Respostas ativas com as variáveis já aplicadas ao lead (para os chips)."""
    from .models import RespostaRapida
    itens = []
    for r in RespostaRapida.objects.filter(ativo=True):
        itens.append({"titulo": r.titulo,
                      "texto": aplicar_variaveis_resposta(r.texto, oportunidade)})
    return itens


def _vars_email(op) -> dict:
    """Valores das variáveis do e-mail para um lead."""
    nome = (op.pessoa.nome or "").strip() if op.pessoa else ""
    primeiro = nome.split()[0] if nome else ""
    cot = op.ultima_cotacao
    quarto = cot.tipo_uh.nome if cot else op.get_tipo_interesse_display()
    ci = op.checkin_previsto.strftime("%d/%m") if op.checkin_previsto else "—"
    co = op.checkout_previsto.strftime("%d/%m") if op.checkout_previsto else "—"
    noites = ((op.checkout_previsto - op.checkin_previsto).days
              if op.checkin_previsto and op.checkout_previsto else 0)
    total = f"R$ {_brl(op.valor_estimado)}" if op.valor_estimado else "a combinar"
    return {
        "{primeiro_nome}": primeiro, "{nome}": nome, "{quarto}": quarto,
        "{checkin}": ci, "{checkout}": co, "{noites}": str(noites),
        "{pessoas}": str(op.hospedes), "{total}": total,
    }


def aplicar_variaveis_email(texto, oportunidade) -> str:
    """Preenche {primeiro_nome}{nome}{quarto}{checkin}{checkout}{noites}{pessoas}{total}."""
    for k, v in _vars_email(oportunidade).items():
        texto = texto.replace(k, v)
    return texto


def aplicar_template_email(template, oportunidade):
    """Aplica um TemplateEmail ao lead → (assunto, corpo) com as variáveis preenchidas."""
    return (aplicar_variaveis_email(template.assunto, oportunidade),
            aplicar_variaveis_email(template.corpo, oportunidade))


def salvar_template_email(*, nome, assunto, corpo, oportunidade=None, usuario):
    """Cria um TemplateEmail. Se vier de um lead, troca o 1º nome do lead por
    {primeiro_nome} para o texto voltar a ser reutilizável."""
    from .models import TemplateEmail
    assunto = (assunto or "").strip()
    corpo = corpo or ""
    if oportunidade is not None and oportunidade.pessoa and oportunidade.pessoa.nome:
        primeiro = oportunidade.pessoa.nome.split()[0]
        if primeiro:
            assunto = assunto.replace(primeiro, "{primeiro_nome}")
            corpo = corpo.replace(primeiro, "{primeiro_nome}")
    nome = (nome or "").strip() or (assunto[:60] or "Template sem nome")
    return TemplateEmail.objects.create(
        nome=nome, assunto=assunto or "(sem assunto)", corpo=corpo, criado_por=usuario)


def templates_email_ativos():
    from .models import TemplateEmail
    return TemplateEmail.objects.filter(ativo=True)


# ───────────────────────── Campanha de e-mail (Fase 3) ─────────────────────────

def publico_da_campanha(segmento):
    """Pessoas-alvo de uma campanha, a partir de filtros do funil.

    Sempre exige e-mail válido + aceita_email e exclui quem já deu bounce/reclamação.
    Filtros de `segmento`: etapa, origem, pagina (LP), temperatura, status.
    Sem filtros → todos os leads (pessoas com alguma oportunidade).
    """
    from apps.nucleo.models import Pessoa

    from .models import EnvioEmail

    seg = segmento or {}
    ops = Oportunidade.objects.all()
    if seg.get("etapa"):
        ops = ops.filter(etapa_id=seg["etapa"])
    if seg.get("origem"):
        ops = ops.filter(origem=seg["origem"])
    if seg.get("pagina"):
        ops = ops.filter(pagina_captacao_id=seg["pagina"])
    if seg.get("temperatura"):
        ops = ops.filter(analise__temperatura=seg["temperatura"])
    if seg.get("status"):
        ops = ops.filter(status=seg["status"])

    ids = ops.values_list("pessoa_id", flat=True).distinct()
    pessoas = (Pessoa.objects.filter(pk__in=ids, ativo=True, aceita_email=True)
               .exclude(email=""))
    ruins = (EnvioEmail.objects
             .filter(status__in=[EnvioEmail.Status.BOUNCE, EnvioEmail.Status.RECLAMADO])
             .values_list("email", flat=True))
    return pessoas.exclude(email__in=ruins).order_by("nome")


def descadastrar_por_token(token):
    """Descadastro público (LGPD): desliga aceita_email. Idempotente. Devolve a Pessoa."""
    from apps.nucleo.models import Pessoa
    pessoa = Pessoa.objects.filter(unsub_token=token).first()
    if pessoa is None:
        return None
    if pessoa.aceita_email:
        pessoa.aceita_email = False
        pessoa.email_descadastro_em = timezone.now()
        pessoa.save(update_fields=["aceita_email", "email_descadastro_em"])
    return pessoa


def _op_recente(pessoa):
    return (Oportunidade.objects.filter(pessoa=pessoa)
            .order_by("-atualizado_em").first())


def notificar_lead_novo(op_id):
    """Avisa a equipe (e-mail) que um lead novo caiu no funil. Best-effort/assíncrono."""
    op = (Oportunidade.objects
          .filter(pk=op_id).select_related("pessoa", "pagina_captacao").first())
    if op is None:
        return
    destinos = [e.strip() for e in getattr(settings, "LEADS_ALERTA_EMAILS", "").split(",")
                if e.strip()]
    if not destinos:
        alvo = getattr(settings, "EMAIL_COMERCIAL_REPLY_TO", "") or ""
        destinos = [alvo] if alvo else []
    if not destinos:
        return
    p = op.pessoa
    origem = op.pagina_captacao.nome if op.pagina_captacao else op.get_origem_display()
    link = settings.SITE_PUBLIC_URL + f"/crm/comercial/{op.pk}/"
    linhas = [
        f"Novo lead capturado ({origem}):", "",
        f"Nome: {p.nome}", f"WhatsApp: {p.telefone or '—'}", f"E-mail: {p.email or '—'}",
    ]
    if op.checkin_previsto and op.checkout_previsto:
        linhas.append(f"Datas: {op.checkin_previsto:%d/%m} → {op.checkout_previsto:%d/%m}")
    linhas += ["", f"Abrir no funil: {link}", "",
               "Quem pegar primeiro assume o lead."]
    texto = "\n".join(linhas)
    html = "<p>" + "</p><p>".join(x or "&nbsp;" for x in linhas) + "</p>"
    for d in destinos:
        enviar_email(para=d, assunto=f"🔥 Novo lead: {p.nome}", html=html, texto=texto,
                     usuario=None, oportunidade=None,
                     assincrono=getattr(settings, "EMAIL_ENVIO_ASSINCRONO", True))


def montar_email_boas_vindas(oportunidade):
    """E-mail de boas-vindas ao lead recém-cadastrado (com descadastro/LGPD)."""
    from urllib.parse import quote  # noqa: F401 (mantém paridade com montar_email_campanha)

    from django.urls import reverse
    op = oportunidade
    p = op.pessoa
    primeiro = (p.nome or "").split()[0] if p.nome else ""
    saud = f"Oi, {primeiro}!" if primeiro else "Olá!"
    corpo = (
        f"{saud} Que bom ter você na lista de fundadores da Pousada Vô Testa 💛\n\n"
        "Você vai ser um dos primeiros a saber das novidades, dos pacotes e da condição "
        "especial de fundador — antes de abrirmos ao público.\n\n"
        "Em breve a gente te chama."
    )
    descadastro_url = settings.SITE_PUBLIC_URL + reverse(
        "email_publico:descadastrar", args=[p.unsub_token])
    url_whatsapp = ""  # WhatsApp ainda não disponível — sem botão por ora
    ctx = {
        "assunto": "Bem-vindo à lista de fundadores 💛",
        "corpo_paragrafos": [x.strip() for x in corpo.split("\n\n") if x.strip()],
        "descadastro_url": descadastro_url, "url_whatsapp": url_whatsapp,
    }
    html = render_to_string("comercial/email/campanha.html", ctx)
    texto = corpo + f"\n\nDescadastrar: {descadastro_url}"
    headers = {
        "List-Unsubscribe": f"<{descadastro_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return {"assunto": ctx["assunto"], "html": html, "texto": texto, "headers": headers}


def enviar_boas_vindas(op_id):
    """Dispara o welcome ao lead (se tem e-mail e opt-in). Best-effort/assíncrono."""
    if not getattr(settings, "LEAD_BOAS_VINDAS", True):
        return
    op = Oportunidade.objects.filter(pk=op_id).select_related("pessoa").first()
    if op is None or op.pessoa is None:
        return
    email = (op.pessoa.email or "").strip()
    if not email or not op.pessoa.aceita_email:
        return
    dados = montar_email_boas_vindas(op)
    enviar_email(para=email, assunto=dados["assunto"], html=dados["html"],
                 texto=dados["texto"], usuario=None, oportunidade=op, pessoa=op.pessoa,
                 headers=dados["headers"],
                 assincrono=getattr(settings, "EMAIL_ENVIO_ASSINCRONO", True))


def enviar_capi_lead(*, email="", telefone="", event_id="", fbp="", fbc="",
                     event_source_url="", client_ip="", user_agent="", assincrono=True):
    """Evento 'Lead' à Meta pela Conversions API (servidor). Dedupe com o Pixel do
    navegador via event_id. Best-effort; dorme sem META_CAPI_TOKEN (o Pixel segue)."""
    token = getattr(settings, "META_CAPI_TOKEN", "")
    pixel = getattr(settings, "META_PIXEL_ID", "")
    if not token or not pixel:
        return None
    import hashlib
    import json
    import time as _t

    def _h(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest()

    tel = "".join(c for c in (telefone or "") if c.isdigit())
    if tel and not tel.startswith("55"):
        tel = "55" + tel
    user_data = {}
    if email:
        user_data["em"] = [_h(email)]
    if tel:
        user_data["ph"] = [hashlib.sha256(tel.encode()).hexdigest()]
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent

    evento = {
        "event_name": "Lead", "event_time": int(_t.time()),
        "action_source": "website",
        "event_source_url": event_source_url or (settings.SITE_PUBLIC_URL + "/"),
        "user_data": user_data,
    }
    if event_id:
        evento["event_id"] = event_id
    body = json.dumps({"data": [evento]}).encode("utf-8")

    def _post():
        from urllib import request as urlreq
        url = (f"https://graph.facebook.com/v21.0/{pixel}/events"
               f"?access_token={token}")
        req = urlreq.Request(url, data=body,
                             headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlreq.urlopen(req, timeout=10) as r:
                r.read()
        except Exception:  # noqa: BLE001 — best-effort, não trava a captação
            pass

    if assincrono:
        import threading
        threading.Thread(target=_post, daemon=True).start()
    else:
        _post()
    return evento


def montar_email_campanha(campanha, pessoa, oportunidade=None):
    """Renderiza o e-mail da campanha para um destinatário (variáveis + descadastro)."""
    from django.urls import reverse
    op = oportunidade or _op_recente(pessoa)
    if op is not None:
        assunto = aplicar_variaveis_email(campanha.assunto, op)
        corpo = aplicar_variaveis_email(campanha.corpo, op)
    else:
        primeiro = (pessoa.nome or "").split()[0] if pessoa.nome else ""
        assunto = campanha.assunto.replace("{primeiro_nome}", primeiro)
        corpo = campanha.corpo.replace("{primeiro_nome}", primeiro)

    descadastro_url = settings.SITE_PUBLIC_URL + reverse(
        "email_publico:descadastrar", args=[pessoa.unsub_token])
    url_whatsapp = ""  # WhatsApp ainda não disponível — sem botão por ora
    contexto = {
        "assunto": assunto,
        "corpo_paragrafos": [p.strip() for p in corpo.split("\n\n") if p.strip()],
        "descadastro_url": descadastro_url, "url_whatsapp": url_whatsapp,
    }
    html = render_to_string("comercial/email/campanha.html", contexto)
    texto = corpo + f"\n\nDescadastrar: {descadastro_url}"
    headers = {
        "List-Unsubscribe": f"<{descadastro_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return {"assunto": assunto, "html": html, "texto": texto, "headers": headers}


def criar_campanha_email(*, nome, assunto, corpo, segmento, usuario, template=None,
                         agendar_para=None):
    from .models import CampanhaEmail
    return CampanhaEmail.objects.create(
        nome=nome, assunto=assunto, corpo=corpo, segmento=segmento or {},
        template=template, agendar_para=agendar_para, criado_por=usuario,
        status=(CampanhaEmail.Status.AGENDADA if agendar_para
                else CampanhaEmail.Status.RASCUNHO))


def enviar_campanha_email(campanha, usuario=None):
    """Dispara a campanha para o público do segmento. Idempotente por (campanha, pessoa):
    não reenvia a quem já recebeu. Atualiza contadores e status."""
    from .models import CampanhaEmail, EnvioEmail

    if campanha.status in (CampanhaEmail.Status.ENVIADA, CampanhaEmail.Status.CANCELADA):
        return campanha
    campanha.status = CampanhaEmail.Status.ENVIANDO
    campanha.save(update_fields=["status"])

    ja_enviados = set(EnvioEmail.objects.filter(
        campanha=campanha, status=EnvioEmail.Status.ENVIADO
    ).values_list("pessoa_id", flat=True))

    publico = publico_da_campanha(campanha.segmento)
    total = enviados = erros = 0
    for pessoa in publico:
        total += 1
        if pessoa.pk in ja_enviados:
            continue
        dados = montar_email_campanha(campanha, pessoa)
        envio = enviar_email(
            para=pessoa.email, assunto=dados["assunto"], html=dados["html"],
            texto=dados["texto"], usuario=usuario, pessoa=pessoa,
            campanha=campanha, headers=dados["headers"], assincrono=False)
        if envio.status == EnvioEmail.Status.ENVIADO:
            enviados += 1
        else:
            erros += 1

    campanha.total = total
    campanha.enviados = len(ja_enviados) + enviados
    campanha.erros = erros
    campanha.status = CampanhaEmail.Status.ENVIADA
    campanha.enviada_em = timezone.now()
    campanha.save(update_fields=["total", "enviados", "erros", "status", "enviada_em"])
    return campanha


def _cancelar_sinal_pendente(oportunidade, usuario):
    """Idempotência do sinal: cancela a cobrança de sinal PENDENTE anterior do lead,
    para nunca haver dois links pagáveis para a mesma estadia (risco de pagamento em
    dobro na conciliação)."""
    if not oportunidade.cobranca_sinal_id:
        return
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import cancelar
    anterior = Cobranca.objects.filter(
        pk=oportunidade.cobranca_sinal_id, status=Cobranca.Status.PENDENTE).first()
    if anterior:
        cancelar(anterior, usuario)


def criar_cobranca_sinal(oportunidade, usuario, valor=None, metodo="pix"):
    """Cria a cobrança do sinal (Safrapay/simulado) para o lead e a vincula.

    Degrada se o módulo Pagamentos estiver inativo. Valor padrão = 30% do valor estimado.
    Devolve a Cobranca (o link público é montado na view com o request).
    """
    from decimal import Decimal as _D

    if not modulo_ativo(Modulo.PAGAMENTOS):
        raise ValidationError("Módulo Pagamentos inativo — não é possível gerar o sinal.")
    valor = _D(str(valor)) if valor else (oportunidade.valor_estimado or _D("0")) * _D("0.30")
    valor = valor.quantize(_D("0.01"))
    if valor <= 0:
        raise ValidationError("Defina o valor estimado do lead para gerar o sinal.")

    _cancelar_sinal_pendente(oportunidade, usuario)
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import criar_cobranca
    cobranca = criar_cobranca(
        usuario, valor=valor, metodo=metodo,
        descricao=f"Sinal — {oportunidade.titulo}"[:120],
        finalidade=Cobranca.Finalidade.SINAL, pagador=oportunidade.pessoa,
    )
    Oportunidade.objects.filter(pk=oportunidade.pk).update(
        cobranca_sinal_id=cobranca.id, atualizado_em=timezone.now())
    oportunidade.cobranca_sinal_id = cobranca.id
    return cobranca


@transaction.atomic
def ganhar_por_sinal(oportunidade, cobranca, usuario=None):
    """Sinal pago numa oportunidade aberta → ganha e cria a reserva automaticamente.

    Chamado pelo receiver de `pagamento_confirmado`. Se faltarem as datas ou o quarto
    cotado, não dá pra montar a reserva — só registra a atividade p/ conversão manual
    (o vendedor confirma no detalhe do lead)."""
    usuario = usuario or cobranca.criado_por
    cot = oportunidade.ultima_cotacao
    tipo_uh = cot.tipo_uh if cot else None
    uh = cot.uh if cot else None  # quarto cotado (venda por unidade), se houver
    checkin = oportunidade.checkin_previsto
    checkout = oportunidade.checkout_previsto
    if not (tipo_uh and checkin and checkout and modulo_ativo(Modulo.RESERVAS)):
        registrar_atividade(
            oportunidade=oportunidade, usuario=usuario,
            tipo=AtividadeComercial.Tipo.SISTEMA,
            descricao="Sinal pago — converter em reserva manualmente "
                      "(faltam datas ou quarto cotado).")
        return None

    # O quarto cotado pode ter sido reservado por outro canal entre a cotação e o
    # pagamento: nesse caso NÃO quebra o pagamento — registra p/ conversão manual.
    try:
        reserva = converter_em_reserva(
            oportunidade, tipo_uh=tipo_uh, uh=uh, checkin=checkin, checkout=checkout,
            usuario=usuario, criar_sinal=False)
    except ValidationError as e:
        registrar_atividade(
            oportunidade=oportunidade, usuario=usuario,
            tipo=AtividadeComercial.Tipo.SISTEMA,
            descricao="Sinal pago — não foi possível criar a reserva automaticamente "
                      f"({'; '.join(e.messages)}). Converter manualmente.")
        return None

    # Amarra o sinal já pago à reserva recém-criada e confirma a reserva.
    from apps.pagamentos.models import Cobranca
    Cobranca.objects.filter(pk=cobranca.pk).update(reserva_id=reserva.pk)
    from apps.reservas.services import confirmar_reserva
    confirmada = confirmar_reserva(reserva.pk, usuario)
    registrar_atividade(
        oportunidade=oportunidade, usuario=usuario,
        tipo=AtividadeComercial.Tipo.SISTEMA,
        descricao=(f"Sinal pago → oportunidade ganha e reserva #{reserva.pk} "
                   f"criada e confirmada automaticamente." if confirmada else
                   f"Sinal pago → oportunidade ganha e reserva #{reserva.pk} criada "
                   f"(confirme a reserva manualmente)."))
    return reserva

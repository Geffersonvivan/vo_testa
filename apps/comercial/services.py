"""
Regras do módulo Comercial. Interface pública para views, Site, Auditoria e Relatórios.

Só conversa com outros módulos por services. Ganho exige conversão em reserva;
perda exige motivo. Cotação, SLA, score e metas cobrem o Plano Comercial P0–P3.
"""
import unicodedata
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Sum
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
    user, criado = Usuario.objects.get_or_create(
        username="_site", defaults={"is_active": True, "first_name": "Site"},
    )
    if criado:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


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
    return analise


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


def dados_kanban(faturamento=""):
    qs = Oportunidade.objects.filter(status=Oportunidade.Status.ABERTA).select_related(
        "pessoa", "etapa", "responsavel", "pagina_captacao", "analise"
    )
    if faturamento:
        qs = qs.filter(faturamento=faturamento)
    por_etapa = {}
    for op in qs:
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
def criar_oportunidade(*, usuario, pessoa, titulo, etapa=None, **campos):
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


def capturar_lead_site(*, nome, email="", telefone="", mensagem="",
                       checkin=None, checkout=None, hospedes=2, documento="",
                       tipo_interesse="hospedagem", faturamento=None, pagina=None,
                       origem=None):
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

    pessoa = None
    if email:
        pessoa = Pessoa.objects.filter(email__iexact=email, ativo=True).first()
    if pessoa is None and documento:
        pessoa = Pessoa.objects.filter(documento=documento, ativo=True).first()
    # E-mail/documento podem ser compartilhados (agência, família, engano). Se o nome é
    # claramente outro, é OUTRA pessoa — não funde leads distintos sob o nome antigo.
    if pessoa is not None and not _nomes_compativeis(pessoa.nome, nome):
        pessoa = None
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

    Prospecto.objects.get_or_create(pessoa=pessoa)

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


def mover_etapa(oportunidade, etapa, usuario, motivo=None):
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
        return oportunidade

    if etapa.tipo == EtapaFunil.Tipo.PERDIDO:
        return marcar_perdida(oportunidade, motivo, usuario)

    _fechar_permanencia(oportunidade)
    oportunidade.etapa = etapa
    oportunidade.status = Oportunidade.Status.ABERTA
    oportunidade.fechado_em = None
    oportunidade.save(update_fields=["etapa", "status", "fechado_em", "atualizado_em"])
    _abrir_permanencia(oportunidade, etapa)
    atualizar_score(oportunidade)
    if de != etapa.nome:
        _log_evento(oportunidade, usuario, f"moveu: {de} → {etapa.nome}")
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
def marcar_perdida(oportunidade, motivo, usuario):
    if motivo is None:
        raise ValidationError("Informe o motivo da perda.")
    _fechar_permanencia(oportunidade)
    oportunidade.status = Oportunidade.Status.PERDIDA
    oportunidade.motivo_perda = motivo
    oportunidade.fechado_em = timezone.now()
    etapa_perdido = _etapa_por_tipo(EtapaFunil.Tipo.PERDIDO)
    if etapa_perdido:
        oportunidade.etapa = etapa_perdido
    oportunidade.save(update_fields=["status", "motivo_perda", "fechado_em",
                                     "etapa", "atualizado_em"])
    if etapa_perdido:
        _abrir_permanencia(oportunidade, etapa_perdido)
        _fechar_permanencia(oportunidade)
    registrar_auditoria(usuario, "oportunidade_perdida", oportunidade,
                        {"motivo": motivo.nome})
    _log_evento(oportunidade, usuario, f"marcou como perdida — {motivo.nome}")
    return oportunidade


def _limpar_prospecto(pessoa):
    Prospecto.objects.filter(pessoa=pessoa).delete()


@transaction.atomic
def registrar_cotacao(*, oportunidade, usuario, tipo_uh, checkin, checkout,
                      valor_diaria=None, validade=None, observacao="",
                      mover_para_cotacao=True):
    """Grava orçamento real; atualiza valor/datas da oportunidade e (opcional) etapa."""
    if not oportunidade.aberta:
        raise ValidationError("Só oportunidades abertas recebem cotação.")
    assumir_lead(oportunidade, usuario)  # cotar = interagir → assume o lead
    if checkout <= checkin:
        raise ValidationError("O check-out deve ser depois do check-in.")
    if valor_diaria is None and modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import diaria_media
        valor_diaria = diaria_media(tipo_uh, checkin, checkout)
    elif valor_diaria is None:
        valor_diaria = tipo_uh.tarifa_base
    valor_diaria = Decimal(str(valor_diaria)).quantize(Decimal("0.01"))
    noites = (checkout - checkin).days
    valor_total = (valor_diaria * noites * max(1, oportunidade.quartos)).quantize(Decimal("0.01"))
    validade = validade or (timezone.localdate() + timedelta(days=VALIDADE_COTACAO_DIAS))
    cotacao = Cotacao.objects.create(
        oportunidade=oportunidade, tipo_uh=tipo_uh, checkin=checkin, checkout=checkout,
        valor_diaria=valor_diaria, valor_total=valor_total, validade=validade,
        observacao=observacao or "", criado_por=usuario,
    )
    oportunidade.checkin_previsto = checkin
    oportunidade.checkout_previsto = checkout
    oportunidade.valor_estimado = valor_total
    oportunidade.save(update_fields=[
        "checkin_previsto", "checkout_previsto", "valor_estimado", "atualizado_em",
    ])
    registrar_atividade(
        oportunidade=oportunidade, usuario=usuario, tipo=AtividadeComercial.Tipo.COTACAO,
        descricao=(
            f"Cotação {tipo_uh.nome}: {checkin:%d/%m}→{checkout:%d/%m} "
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
def converter_em_reserva(oportunidade, *, tipo_uh, checkin, checkout, usuario,
                         valor_diaria=None, criar_sinal=False, valor_sinal=None):
    if oportunidade.reserva_id:
        raise ValidationError("Esta oportunidade já foi convertida em reserva.")
    if not modulo_ativo(Modulo.RESERVAS):
        raise ValidationError(
            "Módulo Reservas inativo — não é possível converter em reserva."
        )
    from apps.reservas.services import criar_prereserva

    Hospede.objects.get_or_create(pessoa=oportunidade.pessoa)
    reserva = criar_prereserva(
        tipo_uh=tipo_uh, checkin=checkin, checkout=checkout,
        hospede=oportunidade.pessoa, usuario=usuario,
        canal="site" if oportunidade.origem == "site" else "balcao",
        faturamento=oportunidade.faturamento, adultos=oportunidade.hospedes,
        valor_diaria=valor_diaria,
        observacoes=f"Convertida da oportunidade #{oportunidade.pk} — {oportunidade.titulo}",
    )
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

    if criar_sinal and modulo_ativo(Modulo.PAGAMENTOS):
        from apps.pagamentos.models import Cobranca
        from apps.pagamentos.services import criar_cobranca
        valor = valor_sinal
        if valor is None:
            valor = (oportunidade.valor_estimado * Decimal("0.30")).quantize(Decimal("0.01"))
        if valor and valor > 0:
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
                           usuario_id, oportunidade_id):
    """Faz o envio pelo gateway e atualiza o EnvioEmail (re-busca objetos por id)."""
    from .email_gateways import get_email_gateway
    from .models import EnvioEmail

    envio = EnvioEmail.objects.filter(pk=envio_id).first()
    if envio is None:
        return
    try:
        res = get_email_gateway().enviar(
            para=para, assunto=assunto, html=html, texto=texto,
            remetente=remetente, reply_to=reply_to)
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
                 pessoa=None, remetente=None, reply_to=None, assincrono=False):
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
        oportunidade=oportunidade, pessoa=pessoa, email=para,
        assunto=assunto[:200], autor=usuario, status=EnvioEmail.Status.PENDENTE)
    args = (envio.pk, para, assunto, html, texto, remetente, reply_to,
            usuario.pk if usuario else None, oportunidade.pk if oportunidade else None)
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
    return achados


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


def receber_mensagem_whatsapp(*, oportunidade=None, telefone=None, texto,
                              id_externo="", quando=None):
    """Registra uma mensagem RECEBIDA do cliente (webhook real ou simulação do MVP).

    Idempotente por id_externo. Abre a janela de 24h e incrementa não-lidas.
    """
    from .models import MensagemWhatsApp, Oportunidade

    if oportunidade is None and telefone:
        from apps.nucleo.models import Pessoa
        so_num = "".join(c for c in telefone if c.isdigit())
        pessoa = Pessoa.objects.filter(telefone__contains=so_num[-8:]).first() if so_num else None
        oportunidade = (Oportunidade.objects.filter(pessoa=pessoa,
                        status=Oportunidade.Status.ABERTA).order_by("-criado_em").first()
                        if pessoa else None)
    if oportunidade is None:
        return None
    if id_externo and MensagemWhatsApp.objects.filter(id_externo=id_externo).exists():
        return None  # idempotência
    conv = abrir_conversa_whatsapp(oportunidade)
    quando = quando or timezone.now()
    msg = MensagemWhatsApp.objects.create(
        conversa=conv, direcao=MensagemWhatsApp.Direcao.ENTRADA, texto=texto.strip(),
        status=MensagemWhatsApp.Status.RECEBIDA, id_externo=id_externo, horario=quando,
    )
    conv.ultima_msg_cliente_em = quando
    conv.nao_lidas = (conv.nao_lidas or 0) + 1
    conv.save(update_fields=["ultima_msg_cliente_em", "nao_lidas", "atualizado_em"])
    return msg


def enviar_mensagem_whatsapp(*, conversa, texto, usuario):
    """Envia uma resposta pelo gateway (best-effort). Quem responde primeiro assume o lead."""
    from .models import MensagemWhatsApp
    from .whatsapp_gateways import get_whatsapp_gateway

    texto = (texto or "").strip()
    if not texto:
        raise ValidationError("Escreva uma mensagem.")
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

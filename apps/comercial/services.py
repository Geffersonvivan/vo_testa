"""
Regras do módulo Comercial. Interface pública para views, Site, Auditoria e Relatórios.

Só conversa com outros módulos por services. Ganho exige conversão em reserva;
perda exige motivo. Cotação, SLA, score e metas cobrem o Plano Comercial P0–P3.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.nucleo.models import Hospede, Prospecto, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .models import (
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
        "pessoa", "etapa", "responsavel"
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
    atualizar_score(op)
    return op


@transaction.atomic
def capturar_lead_site(*, nome, email="", telefone="", mensagem="",
                       checkin=None, checkout=None, hospedes=2, documento="",
                       tipo_interesse="hospedagem", faturamento=None):
    """Interface pública do site: cria Pessoa+Prospecto+Oportunidade (origem=site).

    Se o módulo Comercial estiver inativo, retorna None (site ainda mostra sucesso).
    Idempotência leve: mesmo e-mail + mesmas datas + tipo em 24h atualiza a aberta.
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
        if mensagem:
            obs = (existente.observacao + "\n" if existente.observacao else "") + mensagem
            existente.observacao = obs.strip()
            existente.save(update_fields=["observacao", "atualizado_em"])
            registrar_atividade(
                oportunidade=existente, usuario=usuario, tipo=AtividadeComercial.Tipo.NOTA,
                descricao=f"Atualização do site: {mensagem[:200]}",
            )
        atualizar_score(existente)
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
    op = criar_oportunidade(
        usuario=usuario, pessoa=pessoa, titulo=titulo[:120],
        origem=Oportunidade.Origem.SITE, tipo_interesse=tipo, faturamento=fat,
        checkin_previsto=checkin, checkout_previsto=checkout,
        hospedes=max(1, int(hospedes or 2)),
        observacao=mensagem,
        responsavel=None,
    )
    registrar_atividade(
        oportunidade=op, usuario=usuario, tipo=AtividadeComercial.Tipo.TAREFA,
        descricao=f"1º contato (SLA 24h) — {prefixo.lower()} capturado no site",
        quando=timezone.now() + timedelta(hours=SLA_PRIMEIRO_CONTATO_HORAS),
        concluida=False,
    )
    return op


@transaction.atomic
def mover_etapa(oportunidade, etapa, usuario, motivo=None):
    """Move entre etapas abertas. Ganho exige reserva; Perdido exige motivo."""
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
    return oportunidade


@transaction.atomic
def registrar_atividade(*, oportunidade, usuario, tipo, descricao, quando=None,
                        concluida=True, responsavel=None):
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
    atualizar_score(oportunidade)
    return reserva


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

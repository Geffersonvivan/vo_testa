"""Descritivo dos quartos DENTRO da conversa do lead.

Casa a composição do lead (adultos + crianças + idades) com os quartos que a
comportam, lê disponibilidade e preço da fonte única do CRM e monta o painel que
a vendedora usa durante o atendimento.

Fonte da verdade (nunca duplicada aqui):
- capacidade e frase de camas → `apps.nucleo.estrutura`
- disponibilidade e preço → `apps.reservas.services`
- nome temático / qualidades → `nucleo.UH`
- copy de venda, pontos de atenção, "a levantar" → `comercial.FichaComercial`
"""
from __future__ import annotations

from decimal import Decimal

from apps.nucleo import estrutura
from apps.nucleo.models import UH, TipoUH


def _venda_cfg():
    """Parâmetros de venda (desconto Pix + nº de parcelas) lidos UMA vez — p/ não
    consultar a ConfiguracaoSite (singleton) uma vez por card no painel."""
    from django.conf import settings

    from apps.site.models import ConfiguracaoSite

    return {
        "desconto_pix": Decimal(ConfiguracaoSite.load().desconto_pix or 0),
        "parcelas_max": max(1, settings.PRECO_PARCELAS_MAX),
    }


def _venda(total, cfg=None):
    """Preço de VENDA p/ o card/texto: desconto Pix e parcela no cartão. {} se sem total.
    `cfg` = _venda_cfg() reaproveitado (evita 1 query por card); carrega sozinho se None."""
    if not total:
        return {}
    cfg = cfg or _venda_cfg()
    desc, nmax = cfg["desconto_pix"], cfg["parcelas_max"]
    return {
        "desconto_pix": desc,
        "total_pix": (total * (Decimal("100") - desc) / 100).quantize(Decimal("0.01")),
        "parcelas_max": nmax,
        "parcela_valor": (total / nmax).quantize(Decimal("0.01")),
    }


def comporta(uh, adultos: int, criancas: int, idades=None) -> bool:
    """O quarto acomoda essa composição? Regra do descritivo:

    - criança acima da idade do sofá conta como adulto;
    - sem crianças → cabe se adultos ≤ capacidade máxima (só adultos);
    - com crianças → os adultos ocupam camas fixas + colchões extras e as
      crianças ocupam o sofá-cama (1 adulto OU 2 crianças).
    """
    cap = estrutura.capacidade(uh)
    if cap["maxima"] == 0:  # day use / sem pernoite
        return False
    idade_sofa = cap["idade_sofa"]
    acima = sum(1 for i in (idades or []) if i and int(i) > idade_sofa)
    adultos = adultos + acima
    criancas = max(0, criancas - acima)
    if criancas == 0:
        return adultos <= cap["maxima"]
    # sofá ocupado por crianças → adultos ficam nas camas fixas + extras
    adultos_com_criancas = cap["fixa"] + cap["extras"]
    return adultos <= adultos_com_criancas and criancas <= cap["sofa_criancas"]


def frase_capacidade(uh) -> str:
    """"7 adultos, ou 6 adultos + 2 crianças até 15 anos" — no formato do descritivo."""
    cap = estrutura.capacidade(uh)
    if cap["maxima"] == 0:
        return "—"
    so_adultos = cap["maxima"]
    frase = f"{so_adultos} adulto{'s' if so_adultos != 1 else ''}"
    adultos_com = cap["fixa"] + cap["extras"]
    kids = cap["sofa_criancas"]
    if kids and adultos_com:
        frase += (f", ou {adultos_com} adulto{'s' if adultos_com != 1 else ''} "
                  f"+ {kids} criança{'s' if kids != 1 else ''} até {cap['idade_sofa']} anos")
    return frase


def _uhs_hospedagem():
    """UHs de hospedagem (exclui day use), com camas/config/ficha pré-carregados."""
    return (
        UH.objects
        .filter(status=UH.Status.ATIVA)
        .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
        .select_related("tipo", "config", "ficha_comercial", "vitrine")
        .prefetch_related("posicoes_cama")
        .order_by("numero")
    )


def _cotacao_periodo(uh, op):
    """Cotação itemizada da unidade p/ a lotação do lead (motor — Manual §2 + ISS +
    taxa de turismo), ou None sem datas. Mesmos números do site e da recepção."""
    from apps.reservas import precos

    from .services import faixas_oportunidade

    ci, co = op.checkin_previsto, op.checkout_previsto
    if not (ci and co and (co - ci).days > 0):
        return None
    adultos, c05, c615 = faixas_oportunidade(op)
    return precos.cotacao(
        uh=uh, checkin=ci, checkout=co,
        adultos=adultos, criancas_0_5=c05, criancas_6_15=c615)


def _preco_item(uh, op, venda_cfg=None) -> dict:
    """Campos de preço para o card do quarto: diária, total (com taxas), noites e o
    detalhamento (hospedagem/ISS/turismo). Sem datas, só a 'a partir de'.
    `venda_cfg` = _venda_cfg() reaproveitado quando chamado em laço."""
    from apps.reservas import services as reservas

    cot = _cotacao_periodo(uh, op)
    if cot is None:
        return {"diaria": reservas.tarifa_base_unidade(uh), "total": None, "noites": 0,
                "hospedagem": None, "iss": None, "taxa_turismo": None}
    return {"diaria": cot["media_noite"], "total": cot["total"], "noites": cot["noites"],
            "hospedagem": cot["hospedagem"], "iss": cot["iss"],
            "taxa_turismo": cot["taxa_turismo"], **_venda(cot["total"], venda_cfg)}


def _colchoes_info(uh, op) -> dict:
    """Arranjo sugerido de camas + status do pool de colchões para a lotação do lead,
    nas datas (modelo novo). **As camas fixas do quarto sempre cabem — só o colchão
    EXTRA (pool de 10 compartilhado) pode faltar.** `pool_ok=False` = sem colchão extra em
    alguma noite → não oferecer. `aviso` = frase pronta (bloqueio/atenção) ou None. Sem
    datas ou quarto não configurado → pool_ok=True e arranjo None."""
    from apps.reservas import colchoes
    from apps.reservas import services as reservas

    from .services import faixas_oportunidade

    ci, co = op.checkin_previsto, op.checkout_previsto
    if not (ci and co and (co - ci).days > 0) or not colchoes.configurado(uh):
        return {"arranjo": None, "aviso": None, "pool_ok": True}
    adultos, c05, c615 = faixas_oportunidade(op)
    criancas = c05 + c615
    arr = colchoes.sugerir_arranjo(uh, adultos, criancas)
    conf = reservas.conferir_arranjo(
        uh, casais=arr.casais, solteiros=arr.solteiros, usa_sofa_cama=arr.usa_sofa_cama,
        adultos=adultos, criancas=criancas, checkin=ci, checkout=co)
    aviso = conf["erros"][0] if conf["erros"] else (conf["avisos"][0] if conf["avisos"] else None)
    return {
        "arranjo": {"casais": arr.casais, "solteiros": arr.solteiros,
                    "sofa": arr.usa_sofa_cama, "extra": conf["extra"],
                    "montagem": _montagem_texto(arr, conf["extra"])},
        "aviso": aviso,
        "pool_ok": not conf["erros"],
    }


def _montagem_texto(arr, extra: int) -> str:
    """Frase da montagem de camas p/ o card: '1 cama de casal + 1 de solteiro + sofá'."""
    partes = []
    if arr.casais:
        partes.append(f"{arr.casais} cama{'s' if arr.casais > 1 else ''} de casal")
    if arr.solteiros:
        partes.append(f"{arr.solteiros} de solteiro")
    if arr.usa_sofa_cama:
        partes.append("sofá-cama")
    txt = " + ".join(partes) if partes else "—"
    if extra:
        txt += f" · {extra} colchão{'ões' if extra > 1 else ''} extra"
    return txt


def quartos_para_lead(op) -> dict:
    """Painel completo para a conversa: quartos que servem, ocupados com
    alternativa, atenção agregada e a composição consultada."""
    from apps.reservas import services as reservas

    adultos = op.adultos or 0
    criancas = op.criancas or 0
    idades = op.idades_criancas or []
    checkin, checkout = op.checkin_previsto, op.checkout_previsto
    tem_datas = bool(checkin and checkout and (checkout - checkin).days > 0)

    todas = list(_uhs_hospedagem())  # materializa uma vez (com prefetch)
    # disponibilidade num único conjunto — evita uma consulta por quarto.
    disponiveis = None
    berco_disp = None
    if tem_datas:
        disponiveis = set(
            reservas.uhs_disponiveis(checkin, checkout).values_list("pk", flat=True))
        berco_disp = reservas.berco_disponivel(checkin, checkout)

    venda_cfg = _venda_cfg()  # uma vez só (não 1 query por card)
    servem, ocupados, atencao_topo = [], [], []
    for uh in todas:
        if not comporta(uh, adultos, criancas, idades):
            continue
        preco = _preco_item(uh, op, venda_cfg)
        # Disponibilidade = fisicamente livre E com colchão no pool para a lotação.
        fisicamente_livre = (uh.pk in disponiveis) if tem_datas else None
        colchoes = _colchoes_info(uh, op)
        disponivel = None if not tem_datas else bool(fisicamente_livre and colchoes["pool_ok"])
        ficha = getattr(uh, "ficha_comercial", None)
        pontos = list(ficha.pontos_atencao) if ficha and ficha.pontos_atencao else []
        nome = uh.nome_tematico or uh.numero
        item = {
            "uh": uh,
            "nome": nome,
            "capacidade": frase_capacidade(uh),
            "camas": estrutura.descricao_camas(uh),
            "disponivel": disponivel,
            "arranjo": colchoes["arranjo"],
            "pontos_atencao": pontos,
            "ficha": ficha,
            "campos_a_levantar": _campos_a_levantar(uh, ficha),
            # teto guardado p/ ordenar sem re-consultar a capacidade.
            "_teto": estrutura.capacidade(uh)["maxima_criancas"],
            **preco,
        }
        if tem_datas and not disponivel:
            item["motivo"] = "ocupado" if not fisicamente_livre else "sem_colchao"
            item["equivalentes"] = _equivalentes(
                uh, todas, disponiveis, adultos, criancas, idades)
            ocupados.append(item)
        else:
            servem.append(item)
            # Aviso de colchão (resta pouco) computado pelo modelo novo + os pontos da ficha.
            if colchoes["aviso"]:
                atencao_topo.append((nome, uh.numero, colchoes["aviso"]))
            for p in pontos:
                atencao_topo.append((nome, uh.numero, p))

    # melhor encaixe primeiro: menor quarto que comporta (não oferece a cabana de 8
    # para um casal), com o mais barato à frente em caso de empate.
    servem.sort(key=lambda i: (i["_teto"], i["diaria"] or 0))

    # Lotou nessas datas? Sugere datas vizinhas com vaga (mesma estadia, deslocada).
    datas_alternativas = []
    if tem_datas and not servem:
        candidatos = [u.pk for u in todas if comporta(u, adultos, criancas, idades)]
        datas_alternativas = _datas_vizinhas(checkin, checkout, candidatos)

    return {
        "servem": servem,
        "ocupados": ocupados,
        "atencao_topo": atencao_topo,
        "tem_datas": tem_datas,
        "berco_disponivel": berco_disp,
        "datas_alternativas": datas_alternativas,
        "composicao": {
            "adultos": adultos, "criancas": criancas, "idades": idades,
            "checkin": checkin, "checkout": checkout,
        },
    }


def _datas_vizinhas(checkin, checkout, candidatos):
    """Janelas próximas (mesma duração) com ao menos um quarto candidato livre.
    Só uma dica rápida — a disponibilidade final é reconferida ao cotar."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.reservas import services as reservas
    if not candidatos:
        return []
    candidatos = set(candidatos)
    noites = (checkout - checkin).days
    achados = []
    for desloc in (-2, -1, 1, 2, 3, 7):
        ci = checkin + timedelta(days=desloc)
        co = ci + timedelta(days=noites)
        if ci < timezone.localdate():
            continue
        livres = set(reservas.uhs_disponiveis(ci, co).values_list("pk", flat=True))
        qtd = len(candidatos & livres)
        if qtd:
            achados.append({"checkin": ci, "checkout": co, "qtd": qtd})
        if len(achados) >= 3:
            break
    return achados


def _equivalentes(uh, todas, disponiveis, adultos, criancas, idades):
    """Quartos livres, mesmo tipo e que comportam — pra oferecer no lugar do ocupado.
    Reaproveita a lista e o conjunto de disponíveis já materializados (sem consulta
    nova por quarto)."""
    if not disponiveis:
        return []
    return [
        (outro.nome_tematico or outro.numero)
        for outro in todas
        if outro.pk != uh.pk and outro.tipo_id == uh.tipo_id
        and outro.pk in disponiveis
        and comporta(outro, adultos, criancas, idades)
    ]


# ── "a levantar" ──────────────────────────────────────────────────────────
# Detalhe em branco = «não confirmado, não prometa». Preenchido = confirmado.
# Cada detalhe tem casa própria: metragem na Vitrine; banheiro/área/acessibilidade
# na UH. `confirmados` (JSON da ficha) permite marcar exceção à mão.

def _campos_a_levantar(uh, ficha) -> list:
    """Rótulos dos detalhes ainda em branco — aparecem em cinza («não prometa»)."""
    confirmados = set(ficha.confirmados) if ficha and ficha.confirmados else set()
    vitrine = getattr(uh, "vitrine", None)
    checagens = [
        ("metragem", "Metragem", bool(vitrine and vitrine.metragem)),
        ("banheiro", "Banheiro", bool((uh.banheiro or "").strip())),
        ("area_externa", "Área externa", bool((uh.area_externa or "").strip())),
        ("acessibilidade", "Acessibilidade", bool((uh.acessibilidade or "").strip())),
    ]
    return [rotulo for chave, rotulo, tem in checagens
            if not tem and chave not in confirmados]


def _reais(valor) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto_oferta(uh, op) -> str:
    """Texto limpo pro WhatsApp: nome, camas, capacidade p/ a composição e preço
    (pela motor — Manual §2 + taxas). NUNCA inclui pontos de atenção nem nada interno.
    """
    nome = uh.nome_tematico or uh.numero
    ficha = getattr(uh, "ficha_comercial", None)
    resumo = (ficha.resumo if ficha and ficha.resumo else "").strip()
    linhas = [f"*{nome}*" + (f" — {resumo}" if resumo else "")]
    linhas.append(estrutura.descricao_camas(uh).capitalize() + ".")
    cot = _cotacao_periodo(uh, op)
    if cot:
        noites = cot["noites"]
        linhas.append(
            f"De {op.checkin_previsto:%d/%m} a {op.checkout_previsto:%d/%m} "
            f"({noites} noite{'s' if noites != 1 else ''}): hospedagem "
            f"*R$ {_reais(cot['hospedagem'])}*."
        )
        taxas = []
        if cot["iss"]:
            taxas.append(f"ISS R$ {_reais(cot['iss'])}")
        if cot["taxa_turismo"]:
            taxas.append(f"taxa de turismo R$ {_reais(cot['taxa_turismo'])}")
        if taxas:
            linhas.append(f"{' + '.join(taxas)} (quitadas no check-out) — "
                          f"total *R$ {_reais(cot['total'])}*.")
        venda = _venda(cot["total"])
        if venda:
            linhas.append(
                f"💳 À vista no Pix: *R$ {_reais(venda['total_pix'])}* "
                f"(−{venda['desconto_pix']:.0f}%) · ou em até {venda['parcelas_max']}× "
                f"de R$ {_reais(venda['parcela_valor'])} no cartão."
            )
        # Política de cancelamento (7 dias / 10%) — transparência na proposta.
        from apps.reservas.cancelamento import descricao_politica
        linhas.append("")
        linhas.append(descricao_politica()["resumo"])
    return "\n".join(linhas)


def texto_proposta(op, ids) -> str:
    """Uma mensagem só com 2–3 opções de quarto (o cliente escolhe). Abertura calorosa,
    cada quarto resumido (nome + camas + total), e a política de cancelamento uma vez."""
    uhs = {u.pk: u for u in _uhs_hospedagem().filter(pk__in=ids)}
    ordenadas = [uhs[pk] for pk in ids if pk in uhs]
    if not ordenadas:
        return ""
    primeiro = (op.pessoa.nome or "").split()[0] if op.pessoa and op.pessoa.nome else ""
    saudacao = f"Oi, {primeiro}! " if primeiro else "Oi! "
    linhas = [f"{saudacao}Separei {'estas opções' if len(ordenadas) > 1 else 'esta opção'} "
              f"pra você na *Pousada Vô Testa*:", ""]
    vcfg = _venda_cfg()
    for i, uh in enumerate(ordenadas, 1):
        nome = uh.nome_tematico or uh.numero
        cot = _cotacao_periodo(uh, op)
        linha = f"*{i}. {nome}* — {estrutura.descricao_camas(uh)}"
        if cot:
            linha += f"\n   {cot['noites']} noite{'s' if cot['noites'] != 1 else ''}: "
            linha += f"*R$ {_reais(cot['total'])}*"
            venda = _venda(cot["total"], vcfg)
            if venda:
                linha += (f" · Pix R$ {_reais(venda['total_pix'])} "
                          f"ou {venda['parcelas_max']}× R$ {_reais(venda['parcela_valor'])}")
        linhas.append(linha)
    linhas.append("")
    from apps.reservas.cancelamento import descricao_politica
    linhas.append(descricao_politica()["resumo"])
    linhas.append("Qual delas combina mais com você? 😊")
    return "\n".join(linhas)


def comparar(op, ids) -> list:
    """Colunas da comparação de 2–3 quartos, na ordem em que foram selecionados."""
    uhs = {u.pk: u for u in _uhs_hospedagem().filter(pk__in=ids)}
    venda_cfg = _venda_cfg()
    cols = []
    for pk in ids:
        uh = uhs.get(pk)
        if not uh:
            continue
        ficha = getattr(uh, "ficha_comercial", None)
        cols.append({
            "uh": uh,
            "nome": uh.nome_tematico or uh.numero,
            "categoria": uh.tipo.nome,
            "capacidade": frase_capacidade(uh),
            "camas": estrutura.descricao_camas(uh),
            "ar_condicionado": uh.ar_condicionado,
            "vista_lago": uh.vista_lago,
            "varanda": uh.varanda,
            "aceita_pet": uh.aceita_pet,
            "indicado_para": ficha.indicado_para if ficha else "",
            "diferenciais": uh.diferenciais,
            "banheiro": uh.banheiro,
            "area_externa": uh.area_externa,
            "acessibilidade": uh.acessibilidade,
            **_preco_item(uh, op, venda_cfg),
        })
    return cols


def registrar_oferta(op, uh, usuario):
    """Grava na linha do tempo do lead que este quarto foi oferecido — assim outro
    vendedor não reoferece o que o cliente já viu/recusou."""
    from django.utils import timezone

    from .models import AtividadeComercial

    nome = uh.nome_tematico or uh.numero
    desc = f"Ofereceu {nome} (quarto {uh.numero})"
    if op.checkin_previsto and op.checkout_previsto:
        desc += f" · {op.checkin_previsto:%d/%m}–{op.checkout_previsto:%d/%m}"
    return AtividadeComercial.objects.create(
        oportunidade=op, tipo=AtividadeComercial.Tipo.SISTEMA,
        descricao=desc[:255], quando=timezone.now(),
        criado_por=usuario, responsavel=usuario,
    )

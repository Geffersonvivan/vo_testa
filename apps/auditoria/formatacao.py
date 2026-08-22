"""
Formatação legível da Trilha de auditoria.

Transforma (ação + alvo + detalhe) numa frase em pt-BR — "Abriu o caixa de
Reservas — fundo R$ 0,00" em vez do JSON cru. O detalhe bruto continua guardado
(forense); isto é só apresentação. O que não tem molde cai num texto genérico
razoável, nunca quebra.
"""
from decimal import Decimal, InvalidOperation

# Nomes de model → português amigável.
ALVOS = {
    "SessaoCaixa": "caixa",
    "MovimentoCaixa": "movimento de caixa",
    "Reserva": "reserva",
    "ContaHospedagem": "conta de hospedagem",
    "LancamentoConta": "lançamento na conta",
    "PagamentoConta": "pagamento",
    "Adiantamento": "adiantamento",
    "ContaPagarReceber": "conta a pagar/receber",
    "Pessoa": "pessoa",
    "Usuario": "usuário",
    "OrdemServico": "ordem de serviço",
    "Venda": "venda",
    "Comanda": "comanda",
    "OrdemLavanderia": "ordem de lavanderia",
    "EntradaLogbook": "recado de turno",
}

# Verbos de movimento de caixa.
_MOV = {
    "recebimento": "Recebeu", "reforco": "Reforço de",
    "sangria": "Sangria de", "estorno": "Estornou",
}


def _rs(v):
    try:
        return "R$ " + f"{Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (InvalidOperation, TypeError, ValueError):
        return f"R$ {v}"


def frase(registro) -> str:
    acao = registro.acao
    alvo = registro.alvo
    d = registro.detalhe or {}
    valores = d.get("valores", {}) if isinstance(d, dict) else {}
    nome = ALVOS.get(alvo, alvo)

    # Entrar / sair
    if acao == "login":
        return "Entrou no sistema"
    if acao == "logout":
        return "Saiu do sistema"

    # Caixa (abrir / fechar / reabrir)
    if acao == "criar" and alvo == "SessaoCaixa":
        return (f"Abriu o caixa de {valores.get('modulo', '—')} "
                f"— fundo {_rs(valores.get('fundo_troco', 0))}")
    if acao == "fechamento_caixa":
        return (f"Fechou o caixa — contado {_rs(d.get('contado', 0))} "
                f"(diferença {_rs(d.get('diferenca', 0))})")
    if acao == "reabertura_caixa":
        return f"Reabriu o caixa — motivo: {d.get('motivo', '—')}"

    # Movimento de caixa (recebimento, reforço, sangria)
    if acao == "criar" and alvo == "MovimentoCaixa":
        verbo = _MOV.get(valores.get("tipo"), "Movimento de")
        desc = valores.get("descricao")
        return f"{verbo} {_rs(valores.get('valor', 0))}" + (f" — {desc}" if desc else "")

    # Estorno
    if acao == "estorno":
        return f"Estornou {_rs(d.get('valor', 0))} — motivo: {d.get('motivo', '—')}"

    # Grupo de reserva
    if acao == "criar_grupo":
        return f"Criou o grupo {d.get('rotulo', '')}".rstrip()

    # Ações semânticas de reserva/caixa (nomeadas)
    semanticas = {
        "checkout_automatico": "Fez o check-out (vencido) da reserva",
        "troca_quarto": "Trocou a reserva de quarto",
        "confirmar_reserva": "Confirmou a reserva",
        "cancelamento": "Cancelou a reserva",
        "fechamento_grupo": "Encerrou o grupo",
    }
    if acao in semanticas:
        extra = ""
        if "de" in d and "para" in d:
            extra = f" — de {d['de']} para {d['para']}"
        elif "motivo" in d:
            extra = f" — motivo: {d['motivo']}"
        return f"{semanticas[acao]}{extra}"

    # Genéricos da auto-auditoria (criar / editar / excluir)
    if acao == "criar":
        # Verbo mais natural para algumas entidades operacionais.
        if alvo == "EntradaLogbook":
            return "Deixou um recado no turno"
        verbos = {
            "OrdemServico": "Abriu ordem de serviço",
            "Venda": "Registrou venda",
            "Comanda": "Abriu comanda",
            "OrdemLavanderia": "Abriu ordem de lavanderia",
        }
        if alvo in verbos:
            return f"{verbos[alvo]} #{registro.alvo_id}"
        return f"Criou {nome} #{registro.alvo_id}"
    if acao == "excluir":
        return f"Excluiu {nome} #{registro.alvo_id}"
    if acao == "editar":
        alteracoes = d.get("alteracoes", {}) if isinstance(d, dict) else {}
        if alteracoes:
            partes = []
            for campo, par in list(alteracoes.items())[:3]:
                antes, depois = (par + [None, None])[:2] if isinstance(par, list) else (None, par)
                partes.append(f"{campo}: {antes if antes not in (None, '') else '—'} → "
                              f"{depois if depois not in (None, '') else '—'}")
            reticencia = " …" if len(alteracoes) > 3 else ""
            return f"Alterou {nome}: " + "; ".join(partes) + reticencia
        return f"Alterou {nome} #{registro.alvo_id}"

    # Fallback: humaniza o código da ação, nunca mostra JSON cru.
    return f"{acao.replace('_', ' ').capitalize()} — {nome} #{registro.alvo_id}"

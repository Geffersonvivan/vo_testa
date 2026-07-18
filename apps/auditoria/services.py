"""
Auditoria do CRM (ESPECIFICACAO §4.4/§8). Duas frentes, ambas **read-only**:

1. **Varredura de pendências** — checa inconsistências operacionais em todo o sistema.
   Cada módulo dono expõe `pendencias_auditoria()`; a Auditoria só agrega. Checagens
   do núcleo (caixa, financeiro, estoque) são feitas aqui direto sobre os models do
   núcleo. Degrada com graça: só consulta módulos ativos.
2. **Trilha de auditoria** — leitura/filtro da `TrilhaAuditoria` (quem fez o quê).

A Auditoria **não altera dados** — só lê e aponta; a correção acontece no módulo dono.
"""
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.nucleo.modulos import Modulo

# Ordem de gravidade para ordenar os achados (alta primeiro).
_ORDEM_GRAVIDADE = {"alta": 0, "media": 1, "baixa": 2}


def _url(nome, *args):
    try:
        return reverse(nome, args=args)
    except NoReverseMatch:
        return None


def _checagens_nucleo():
    """Pendências que vivem no núcleo: caixa, financeiro, estoque."""
    from apps.nucleo.models import (
        ContaPagarReceber,
        SessaoCaixa,
        produtos_abaixo_minimo,
    )
    achados = []
    hoje = timezone.localdate()

    for c in (SessaoCaixa.objects.filter(status=SessaoCaixa.Status.ABERTA,
                                         aberta_em__date__lt=hoje)
              .select_related("operador")):
        achados.append({
            "area": "Caixa", "tipo": "caixa_aberto_antigo", "gravidade": "alta",
            "descricao": f"Caixa de {c.operador} aberto desde {c.aberta_em:%d/%m %H:%M} — conferir/fechar.",
            "url": _url("caixa_sessao", c.pk),
        })

    for v in ContaPagarReceber.objects.filter(status=ContaPagarReceber.Status.ABERTA,
                                              vencimento__lt=hoje):
        achados.append({
            "area": "Financeiro", "tipo": "conta_vencida", "gravidade": "media",
            "descricao": f"{v.get_tipo_display()} vencida: {v.descricao} (venc. {v.vencimento:%d/%m}).",
            "url": _url("contas"),
        })

    n = produtos_abaixo_minimo()
    if n:
        achados.append({
            "area": "Estoque", "tipo": "estoque_minimo", "gravidade": "media",
            "descricao": f"{n} produto(s) abaixo do estoque mínimo.",
            "url": _url("estoque:posicao"),
        })
    return achados


def varrer():
    """Roda todas as varreduras e devolve os achados ordenados por gravidade."""
    achados = list(_checagens_nucleo())

    from apps.nucleo.models import modulo_ativo
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import pendencias_auditoria
        achados += pendencias_auditoria()
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao.services import pendencias_auditoria
        achados += pendencias_auditoria()
    if modulo_ativo(Modulo.RESTAURANTE):
        from apps.restaurante.services import pendencias_auditoria
        achados += pendencias_auditoria()
    if modulo_ativo(Modulo.LAVANDERIA):
        from apps.lavanderia.services import pendencias_auditoria
        achados += pendencias_auditoria()
    if modulo_ativo(Modulo.FISCAL):
        from apps.fiscal.services import pendencias_auditoria
        achados += pendencias_auditoria()
    if modulo_ativo(Modulo.COMERCIAL):
        from apps.comercial.services import pendencias_auditoria
        achados += pendencias_auditoria()

    achados.sort(key=lambda a: _ORDEM_GRAVIDADE.get(a["gravidade"], 9))
    return achados


def resumo(achados):
    """Contagens para os KPIs do painel."""
    por_area, por_grav = {}, {"alta": 0, "media": 0, "baixa": 0}
    for a in achados:
        por_area[a["area"]] = por_area.get(a["area"], 0) + 1
        por_grav[a["gravidade"]] = por_grav.get(a["gravidade"], 0) + 1
    return {"total": len(achados), "por_area": por_area, "por_gravidade": por_grav}

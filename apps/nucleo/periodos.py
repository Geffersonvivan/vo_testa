"""
Seletor de período compartilhado (mês/ano + intervalo personalizado).

Usado por Relatórios e pela Trilha de auditoria — um único controle, mesmo
comportamento em toda parte. Padrão = mês corrente; `de`+`ate` sobrepõem com um
intervalo livre.
"""
import calendar
from datetime import date, datetime

from django.utils import timezone

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _data(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _mes_ano(request):
    """(mês, ano) escolhidos, com fallback no mês corrente."""
    hoje = timezone.localdate()
    try:
        mes = int(request.GET.get("mes") or hoje.month)
        ano = int(request.GET.get("ano") or hoje.year)
    except (TypeError, ValueError):
        mes, ano = hoje.month, hoje.year
    if not 1 <= mes <= 12:
        mes = hoje.month
    return mes, ano


def periodo(request):
    """Período resolvido: MÊS/ANO (padrão) ou `de`+`ate`. Retorna (inicio, fim, rotulo)."""
    de, ate = _data(request.GET.get("de")), _data(request.GET.get("ate"))
    if de and ate:
        return de, ate, "personalizado"
    mes, ano = _mes_ano(request)
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return inicio, fim, f"{MESES_PT[mes]}/{ano}"


def selecao_periodo(request):
    """Opções do seletor mês/ano para o template (últimos 5 anos + o corrente)."""
    hoje = timezone.localdate()
    mes_sel, ano_sel = _mes_ano(request)
    meses = [(i, MESES_PT[i]) for i in range(1, 13)]
    anos = list(range(hoje.year, hoje.year - 5, -1))
    if ano_sel not in anos:
        anos = sorted(set(anos + [ano_sel]), reverse=True)
    return {"meses": meses, "anos": anos, "mes_sel": mes_sel, "ano_sel": ano_sel}

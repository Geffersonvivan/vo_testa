"""Calendário de feriados para tarifação — nacionais (fixos + móveis) + Itá/SC.

Computado por ano, sem depender de registros no banco: liga uma vez e vale para
sempre. A classificação de temporada consulta `eh_feriado()` quando os feriados
automáticos estão ligados (`ConfiguracaoReservas.feriados_automaticos`, default
ligado). Feriados locais/específicos continuam podendo ser cadastrados à mão como
Temporada classificação Feriado — somam ao automático.
"""
from datetime import date, timedelta


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (Computus gregoriano — algoritmo anônimo)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mes = (h + ll - 7 * m + 114) // 31
    dia = ((h + ll - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


# (mês, dia, nome) — feriados de data fixa: nacionais + aniversário de Itá.
_FIXOS = [
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Consciência Negra"),
    (12, 25, "Natal"),
    (12, 13, "Aniversário de Itá"),  # municipal — emancipação em 13/12/1956
]


def feriados_do_ano(ano: int) -> dict:
    """{data: nome} dos feriados do ano: nacionais fixos + móveis + Itá.

    Móveis (derivados da Páscoa): Sexta-feira Santa, Carnaval (terça) e Corpus
    Christi — os feriadões que a pousada pratica como tarifa de feriado.
    """
    fer = {date(ano, mes, dia): nome for (mes, dia, nome) in _FIXOS}
    p = pascoa(ano)
    fer[p - timedelta(days=2)] = "Sexta-feira Santa"
    fer[p - timedelta(days=47)] = "Carnaval"
    fer[p + timedelta(days=60)] = "Corpus Christi"
    return fer


def eh_feriado(dia: date) -> str | None:
    """Nome do feriado nessa data (nacional ou de Itá), ou None."""
    return feriados_do_ano(dia.year).get(dia)

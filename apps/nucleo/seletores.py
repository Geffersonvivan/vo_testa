"""
Utilidades de seleção de pessoas para a UI — alimentam o combobox com busca
e agrupamento por papel (`templates/componentes/combo_pessoa.html`).
"""
from .models import Pessoa

# Ordem dos grupos no seletor (mais relevante primeiro para o dia a dia).
GRUPOS_PESSOA = [
    ("hospede", "Hóspedes"),
    ("prospecto", "Prospecção"),
    ("avulso", "Clientes avulsos"),
    ("agencia", "Agências e empresas"),
    ("funcionario", "Funcionários"),
    ("fornecedor", "Fornecedores"),
]


def _grupo_pessoa(p) -> str:
    # Hóspede vem antes de prospecto: um lead ganho (virou hóspede) sai da Prospecção.
    if hasattr(p, "hospede"):
        return "hospede"
    if hasattr(p, "agencia"):
        return "agencia"
    if hasattr(p, "funcionario"):
        return "funcionario"
    if hasattr(p, "fornecedor"):
        return "fornecedor"
    if hasattr(p, "prospecto"):
        return "prospecto"
    return "avulso"


def pessoas_agrupadas(queryset=None):
    """Pessoas classificadas por papel, ordenadas por grupo e nome.

    Retorna uma lista de dicts ``{"id", "nome", "grupo"}`` pronta para
    ``json_script`` — o combobox filtra e agrupa no cliente.
    """
    ordem = {chave: i for i, (chave, _) in enumerate(GRUPOS_PESSOA)}
    rotulos = dict(GRUPOS_PESSOA)
    qs = queryset if queryset is not None else Pessoa.objects.filter(ativo=True)
    qs = qs.select_related("hospede", "agencia", "funcionario", "fornecedor", "prospecto")
    itens = [
        {"id": p.pk, "nome": p.nome, "grupo": _grupo_pessoa(p)} for p in qs
    ]
    itens.sort(key=lambda it: (ordem[it["grupo"]], it["nome"].lower()))
    return [
        {"id": it["id"], "nome": it["nome"], "grupo": rotulos[it["grupo"]]}
        for it in itens
    ]

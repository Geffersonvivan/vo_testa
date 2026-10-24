"""
Heurístico de classificação reutilizável (de-para automático de categorias novas).

Mantido fora das migrações de propósito: as migrações carregam a própria cópia
congelada; este módulo é a versão viva usada pelos signals em runtime.
"""

import unicodedata

CHAVES_RECEITA = [
    (("diaria", "hosped", "servic", "lavanderia", "day use", "evento"), "3.1.01.03"),
    (("consumo", "produto", "mercadoria", "bebida", "restaurante", "loja", "venda"), "3.1.01.01"),
    (("simples", "tribut", "imposto", "iss", "devolu", "abatimento"), "3.1.02.01"),
]
CHAVES_DESPESA = [
    (("honor", "contab", "advog"), "5.1.02.02"),
    (("propaganda", "publicid", "market", "comiss", "ota", "promo"), "5.1.01.02"),
    (("energia", "luz", "agua", "internet", "manuten", "telefone", "limpeza", "material", "utilidade"), "4.2.01.03"),
    (("salar", "folha", "pessoal", "fgts", "inss", "feria", "pro-labore", "pro labore", "13"), "4.2.01.01"),
    (("juros", "banc", "tarifa", "cartao", "financ", "adquir"), "5.1.03.02"),
]
PADRAO_RECEITA = "3.1.01.03"
PADRAO_DESPESA = "5.1.02.02"


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def classificacao_para(nome: str, tipo: str) -> str:
    """Classificação sugerida para uma categoria, por palavra-chave do nome."""
    n = _sem_acento(nome)
    chaves = CHAVES_RECEITA if tipo == "receita" else CHAVES_DESPESA
    for termos, classif in chaves:
        if any(t in n for t in termos):
            return classif
    return PADRAO_RECEITA if tipo == "receita" else PADRAO_DESPESA

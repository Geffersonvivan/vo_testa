"""Gerador de Pix "copia-e-cola" (BR Code EMV) — local, sem PSP.

Monta o payload estático do Pix no padrão BACEN/EMV a partir da chave da própria
pousada, com valor e txid embutidos. Não chama rede nenhuma: o dinheiro cai direto
na conta do recebedor (sem taxa de adquirente). Como não há PSP, **não existe
webhook** — a confirmação é manual (a recepção confere o extrato e dá baixa).

Referência: Manual do BR Code (BACEN) + EMV QRCPS MPM. CRC = CRC-16/CCITT-FALSE
(polinômio 0x1021, init 0xFFFF), 4 hex maiúsculos, calculado sobre o payload
inteiro já com "6304" ao final.
"""
from __future__ import annotations

import unicodedata
from decimal import Decimal


def _tlv(id_campo: str, valor: str) -> str:
    """Campo EMV no formato ID + tamanho(2 dígitos) + valor."""
    return f"{id_campo}{len(valor):02d}{valor}"


def crc16(payload: str) -> str:
    """CRC-16/CCITT-FALSE do payload (string ASCII). Retorna 4 hex maiúsculos."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _ascii(texto: str, limite: int) -> str:
    """Remove acentos/símbolos (o BR Code só aceita ASCII imprimível) e corta."""
    limpo = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    # Mantém letras, números e espaço; espaços repetidos viram um.
    limpo = "".join(c for c in limpo if c.isalnum() or c == " ")
    return " ".join(limpo.split())[:limite].strip()


def montar_br_code(*, chave: str, nome: str, cidade: str,
                   valor=None, txid: str = "***", descricao: str = "") -> str:
    """Monta o copia-e-cola do Pix. `valor` opcional (None = sem valor fixo)."""
    chave = (chave or "").strip()
    if not chave:
        raise ValueError("Chave Pix não configurada (PIX_CHAVE).")
    nome = _ascii(nome, 25) or "RECEBEDOR"
    cidade = _ascii(cidade, 15) or "CIDADE"
    txid = _ascii(txid, 25) or "***"

    # Merchant Account Information (ID 26): GUI do Pix + chave (+ descrição opcional).
    mai = _tlv("00", "br.gov.bcb.pix") + _tlv("01", chave)
    if descricao:
        mai += _tlv("02", _ascii(descricao, 40))

    payload = ""
    payload += _tlv("00", "01")           # Payload Format Indicator
    payload += _tlv("26", mai)            # Merchant Account Information — Pix
    payload += _tlv("52", "0000")         # Merchant Category Code (0000 = não informado)
    payload += _tlv("53", "986")          # Moeda = BRL (ISO 4217)
    if valor is not None:
        payload += _tlv("54", f"{Decimal(str(valor)):.2f}")  # Valor da transação
    payload += _tlv("58", "BR")           # País
    payload += _tlv("59", nome)           # Nome do recebedor
    payload += _tlv("60", cidade)         # Cidade do recebedor
    payload += _tlv("62", _tlv("05", txid))  # Additional Data Field (05 = txid)
    payload += "6304"                     # ID+tam do CRC (o valor vem a seguir)
    return payload + crc16(payload)

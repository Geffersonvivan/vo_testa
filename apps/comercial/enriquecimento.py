"""Enriquecimento best-effort do lead — sinais APROXIMADOS, offline, sem chamar
serviço externo (bom p/ LGPD e latência). Nada aqui é fato garantido; tudo é
gravado no lead (`Oportunidade.origem_rastreio`) rotulado como *estimado*, para
segmentar atendimento/campanha — nunca como cadastro autoritativo da pessoa.

Sinais:
  • sexo   → chute pelo 1º nome (mesma regra da Escala);
  • UF     → pelo DDD do WhatsApp que o lead digitou (bem confiável no Brasil,
             melhor que GeoIP de celular);
  • cidade → GeoIP plugável: só ativa se houver base GeoLite2 (settings.GEOIP_CITY_DB)
             + lib `geoip2`; senão, no-op silencioso;
  • dispositivo/navegador → user-agent (iPhone/Android/…, e in-app do Instagram).
"""
from __future__ import annotations

import os

from django.conf import settings

# DDD → UF (todos os DDDs do Brasil). O DDD do número costuma ser o estado de
# origem da pessoa — mais estável que o IP (que num celular é do gateway da operadora).
DDD_UF = {
    11: "SP", 12: "SP", 13: "SP", 14: "SP", 15: "SP", 16: "SP", 17: "SP", 18: "SP", 19: "SP",
    21: "RJ", 22: "RJ", 24: "RJ",
    27: "ES", 28: "ES",
    31: "MG", 32: "MG", 33: "MG", 34: "MG", 35: "MG", 37: "MG", 38: "MG",
    41: "PR", 42: "PR", 43: "PR", 44: "PR", 45: "PR", 46: "PR",
    47: "SC", 48: "SC", 49: "SC",
    51: "RS", 53: "RS", 54: "RS", 55: "RS",
    61: "DF", 62: "GO", 64: "GO", 63: "TO", 65: "MT", 66: "MT", 67: "MS",
    68: "AC", 69: "RO",
    71: "BA", 73: "BA", 74: "BA", 75: "BA", 77: "BA", 79: "SE",
    81: "PE", 87: "PE", 82: "AL", 83: "PB", 84: "RN", 85: "CE", 88: "CE", 86: "PI", 89: "PI",
    91: "PA", 93: "PA", 94: "PA", 92: "AM", 97: "AM", 95: "RR", 96: "AP", 98: "MA", 99: "MA",
}

# Exceções da regra "termina em A → feminino" (alinhado ao chutador da Escala).
NOMES_F = {"ivone", "beatriz", "isabel", "isabela", "raquel", "ester", "miriam",
           "carmen", "eliane", "cleusa", "solange", "ines", "inês", "meire"}
NOMES_M = {"luca", "josue", "josué", "noe", "noé", "elias", "tobias", "jonas",
           "dida", "juca", "nica", "agostinho"}


def sexo_por_nome(nome: str) -> str:
    """'F' | 'M' | '' — chute pelo 1º nome. Vazio só quando não há nome."""
    prim = (nome or "").strip().split(" ")[0].lower()
    if not prim:
        return ""
    if prim in NOMES_F:
        return "F"
    if prim in NOMES_M:
        return "M"
    return "F" if prim.endswith("a") else "M"


def uf_por_telefone(telefone: str) -> str:
    """UF a partir do DDD. Aceita '(49) 99999-0000', '5549...', '49999...'."""
    d = "".join(ch for ch in (telefone or "") if ch.isdigit())
    if d.startswith("55") and len(d) > 11:   # veio com código do país
        d = d[2:]
    if len(d) < 10:                          # sem DDD + número plausível
        return ""
    try:
        return DDD_UF.get(int(d[:2]), "")
    except ValueError:
        return ""


def dispositivo_por_ua(ua: str) -> str:
    u = (ua or "").lower()
    if not u:
        return ""
    if "ipad" in u:
        return "iPad"
    if "iphone" in u or ("ios" in u and "mobile" in u):
        return "iPhone"
    if "android" in u:
        return "Android (celular)" if "mobile" in u else "Android (tablet)"
    if "windows" in u:
        return "Windows"
    if "macintosh" in u or "mac os" in u:
        return "Mac"
    if "linux" in u:
        return "Linux"
    return ""


def navegador_app(ua: str) -> str:
    """Detecta o navegador in-app das redes (confirma a origem do tráfego)."""
    u = (ua or "").lower()
    if "instagram" in u:
        return "Instagram"
    if "fban" in u or "fbav" in u or "fb_iab" in u:
        return "Facebook"
    return ""


def _ip_privado(ip: str) -> bool:
    try:
        import ipaddress
        obj = ipaddress.ip_address(ip)
        return obj.is_private or obj.is_loopback or obj.is_reserved
    except ValueError:
        return True


def cidade_uf_por_ip(ip: str):
    """(cidade, uf) por GeoIP — plugável e OFFLINE. No-op se não houver base.

    Ativa quando: `settings.GEOIP_CITY_DB` aponta p/ um GeoLite2-City.mmdb E a
    lib `geoip2` está instalada. Do contrário retorna ('', '') sem erro.
    """
    if not ip or _ip_privado(ip):
        return "", ""
    path = getattr(settings, "GEOIP_CITY_DB", "") or ""
    if not path or not os.path.exists(path):
        return "", ""
    try:
        import geoip2.database
        with geoip2.database.Reader(path) as reader:
            resp = reader.city(ip)
            cidade = resp.city.name or ""
            uf = ""
            if resp.subdivisions:
                uf = resp.subdivisions.most_specific.iso_code or ""
            return cidade, uf
    except Exception:  # noqa: BLE001 — GeoIP nunca quebra a captação
        return "", ""


def sinais_do_lead(*, nome: str = "", telefone: str = "", ip: str = "",
                   user_agent: str = "") -> dict:
    """Junta os sinais estimados não-vazios para carimbar no `origem_rastreio`."""
    sinais = {}
    sexo = sexo_por_nome(nome)
    if sexo:
        sinais["sexo_estimado"] = sexo
    disp = dispositivo_por_ua(user_agent)
    if disp:
        sinais["dispositivo"] = disp
    app = navegador_app(user_agent)
    if app:
        sinais["navegador"] = app
    cidade, uf_ip = cidade_uf_por_ip(ip)
    if cidade:
        sinais["cidade_estimada"] = cidade
    uf = uf_por_telefone(telefone) or uf_ip
    if uf:
        sinais["uf_estimada"] = uf
    return sinais

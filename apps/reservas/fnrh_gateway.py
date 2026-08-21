"""
Gateway da FNRH Digital (Ficha Nacional de Registro de Hóspedes — Embratur/Serpro).

Estratégia B: o hóspede preenche no NOSSO portal e nós EMPURRAMOS para a API oficial
(cria reserva → cria pessoas → adiciona hóspedes com o bloco `fnrh` → check-in em lote).

Plugável por `FNRH_GATEWAY` (settings):
- **simulado** (default): sandbox local, gera UUIDs fake, sem rede. Para dev/testes.
- **serpro**: API REST v2 (Basic Auth). Exige FNRH_API_URL/USER/SENHA no .env.
  Documento oficial: API FNRH v2.1 (09/03/2026).

Base: Produção  https://fnrh.turismo.serpro.gov.br/FNRH_API/rest/v2
      Homolog.  https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


# Os choices de FichaFNRH já usam os ids oficiais da FNRH (GET /dominios/…), então
# não há de-para: o valor do campo é enviado direto. Ver apps/reservas/models.py.

def _pais_iso(ficha) -> str:
    """País de residência em ISO 3166-1 alpha-2. Hoje guardamos texto livre; até
    termos o código no cadastro, assume BR quando não é estrangeiro."""
    pais = (ficha.pais or "").strip().upper()
    if pais in ("", "BRASIL", "BRAZIL", "BR"):
        return "BR"
    if len(pais) == 2:
        return pais
    return "BR"  # TODO: tabela nome→ISO quando o cadastro tiver o código


def _tipo_documento(ficha) -> str:
    """CPF (nacional) ou PASSAPORTE (estrangeiro). Usa o tipo da ficha; se vazio,
    infere pelo país."""
    return ficha.documento_tipo or (
        "PASSAPORTE" if _pais_iso(ficha) != "BR" else "CPF"
    )


def payload_reserva(reserva) -> dict:
    """POST /reservas."""
    canal_ota = getattr(reserva, "canal", None) == reserva.Canal.OTA
    return {
        "numero_reserva": f"VT-{reserva.pk}",
        "numero_reserva_ota": "",
        "data_entrada": reserva.checkin.isoformat(),
        "data_saida": reserva.checkout.isoformat(),
        "quantidade_hospede_adulto": reserva.adultos,
        "quantidade_hospede_menor": reserva.criancas,
        "origem_reserva_id": "OTA" if canal_ota else "MEIOHOSPEDAGEM",
    }


def payload_pessoa(ficha) -> dict:
    """POST /pessoas (dados pessoais + documento)."""
    dados = {
        "nome": ficha.nome,
        "PaisNacionalidade_id": _pais_iso(ficha),
        "data_nascimento": ficha.nascimento.isoformat() if ficha.nascimento else None,
        "numero_documento": ficha.documento_numero or ficha.cpf,
        "tipo_documento_id": _tipo_documento(ficha),
    }
    if ficha.sexo:
        dados["genero_id"] = ficha.sexo  # já é o id oficial (HOMEM/MULHER/…)
    return dados


def payload_hospede(ficha, *, pessoa_id, situacao="PRECHECKIN_REALIZADO") -> dict:
    """POST /reservas/{id}/hospedes — vincula a pessoa com o bloco fnrh."""
    return {
        "pessoa_id": str(pessoa_id),
        "is_principal": bool(ficha.titular),
        "situacao_hospede_id": situacao,
        "fnrh": {
            "motivo_viagem_id": ficha.motivo_viagem,   # já é o id oficial
            "meio_transporte_id": ficha.meio_transporte,
        },
    }


# ─────────────────────────────────── Gateways ───────────────────────────────────

class GatewaySimulado:
    """Sandbox: devolve UUIDs fake e não toca a rede."""
    nome = "simulado"

    def criar_reserva(self, reserva) -> str:
        return str(uuid.uuid4())

    def criar_pessoa(self, ficha) -> str:
        return str(uuid.uuid4())

    def adicionar_hospede(self, reserva_fnrh_id, ficha, pessoa_id) -> str:
        return str(uuid.uuid4())

    def checkin(self, reserva_fnrh_id) -> None:
        return None

    def checkout(self, reserva_fnrh_id) -> None:
        return None

    def cancelar(self, reserva_fnrh_id) -> None:
        return None


class GatewaySerpro:
    """API REST v2 da FNRH Digital (Serpro). Basic Auth. Precisa de credenciais."""
    nome = "serpro"

    def __init__(self):
        self.base = getattr(settings, "FNRH_API_URL", "").rstrip("/")
        user = getattr(settings, "FNRH_API_USER", "")
        senha = getattr(settings, "FNRH_API_SENHA", "")
        if not (self.base and user and senha):
            raise ValidationError(
                "FNRH gateway 'serpro' exige FNRH_API_URL, FNRH_API_USER e "
                "FNRH_API_SENHA no .env. Sem credenciais, mantenha FNRH_GATEWAY=simulado."
            )
        cred = base64.b64encode(f"{user}:{senha}".encode()).decode()
        self._auth = f"Basic {cred}"

    def _req(self, metodo, caminho, corpo=None):
        url = f"{self.base}{caminho}"
        data = json.dumps(corpo).encode() if corpo is not None else None
        req = urlrequest.Request(url, data=data, method=metodo)
        req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                bruto = resp.read().decode("utf-8") or "{}"
                return json.loads(bruto) if bruto.strip() else {}
        except urlerror.HTTPError as e:
            detalhe = e.read().decode("utf-8", "ignore")
            raise ValidationError(f"FNRH {metodo} {caminho} → HTTP {e.code}: {detalhe}")
        except urlerror.URLError as e:
            raise ValidationError(f"FNRH indisponível ({caminho}): {e.reason}")

    def criar_reserva(self, reserva) -> str:
        r = self._req("POST", "/reservas", payload_reserva(reserva))
        return r.get("reserva", {}).get("reserva_id") or r.get("reserva_id")

    def criar_pessoa(self, ficha) -> str:
        r = self._req("POST", "/pessoas", payload_pessoa(ficha))
        return r.get("pessoa", {}).get("pessoa_id") or r.get("id") or r.get("pessoa_id")

    def adicionar_hospede(self, reserva_fnrh_id, ficha, pessoa_id) -> str | None:
        self._req(
            "POST", f"/reservas/{reserva_fnrh_id}/hospedes",
            payload_hospede(ficha, pessoa_id=pessoa_id),
        )
        # A API não devolve o hospede_id no POST — busca na listagem.
        lista = self._req("GET", f"/reservas/{reserva_fnrh_id}/hospedes")
        for item in lista.get("dados", []):
            if item.get("pessoa", {}).get("pessoa_id") == str(pessoa_id):
                return item.get("hospede", {}).get("hospede_id")
        return None

    def checkin(self, reserva_fnrh_id) -> None:
        self._req("POST", f"/reservas/{reserva_fnrh_id}/checkin")

    def checkout(self, reserva_fnrh_id) -> None:
        self._req("POST", f"/reservas/{reserva_fnrh_id}/checkout")

    def cancelar(self, reserva_fnrh_id) -> None:
        self._req("POST", f"/reservas/{reserva_fnrh_id}/cancelar")


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "serpro": GatewaySerpro,
}


def get_gateway():
    nome = getattr(settings, "FNRH_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"Gateway FNRH desconhecido: {nome!r}. Use um de: {', '.join(sorted(_GATEWAYS))}."
        )
    return cls()

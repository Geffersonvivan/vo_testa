"""
Proposta registrada do NPS — fase CRM do Hóspede.

Este módulo não persiste respostas nesta fase. A API pública abaixo está
documentada e exposta como stub (HTTP 501) para travar o contrato antes da
implementação.
"""

PROPOSTA = {
    "titulo": "NPS pós-estadia (Portal do Hóspede + API)",
    "fase": "CRM do Hóspede (fase 2)",
    "status": "proposta",
    "implementado": False,
    "objetivo": (
        "Coletar Net Promoter Score (0–10) após a estadia, a partir do portal "
        "do hóspede e/ou link por e-mail/WhatsApp, e consolidar no CRM."
    ),
    "escopo_ui": [
        "Ícone/atalho no portal do hóspede (/hospede/<token>/nps/).",
        "Painel interno no CRM (sidebar → NPS) com score, detratores/passivos/promotores.",
        "Gatilho preferencial: pós check-out (e opcionalmente durante a estadia).",
    ],
    "api": {
        "base": "/api/nps/v1/",
        "autenticacao": {
            "hospede": "token opaco do portal (AcessoPortal), sem login",
            "equipe": "sessão CRM (login) — resumo e listagem",
        },
        "endpoints": [
            {
                "metodo": "POST",
                "path": "/api/nps/v1/respostas/",
                "descricao": "Registrar nota NPS (0–10) + comentário opcional.",
                "corpo": {
                    "token": "uuid do portal OU",
                    "reserva_id": "int (quando canal interno)",
                    "nota": "int 0–10",
                    "comentario": "str opcional",
                    "canal": "portal | email | whatsapp | site",
                },
                "regras": [
                    "Uma resposta por reserva (idempotente: segunda POST atualiza ou 409).",
                    "Nota fora de 0–10 → 400.",
                    "Estadia inexistente/encerrada sem janela → 404.",
                ],
            },
            {
                "metodo": "GET",
                "path": "/api/nps/v1/respostas/<reserva_id>/",
                "descricao": "Ler resposta de uma reserva (equipe).",
            },
            {
                "metodo": "GET",
                "path": "/api/nps/v1/resumo/",
                "descricao": "Score NPS + contagem por faixa no período.",
                "query": {"de": "YYYY-MM-DD", "ate": "YYYY-MM-DD"},
            },
        ],
    },
    "modelo_previsto": {
        "app": "apps.nps (ou apps.crm_hospede)",
        "entidade": "RespostaNPS",
        "campos": [
            "reserva (FK reservas.Reserva, unique)",
            "hospede (FK nucleo.Pessoa)",
            "nota (PositiveSmallIntegerField 0–10)",
            "faixa (detrator 0–6 / passivo 7–8 / promotor 9–10)",
            "comentario (TextField blank)",
            "canal",
            "criado_em",
        ],
    },
    "integracoes": [
        "Portal: formulário em /hospede/<token>/nps/ → POST API.",
        "Reservas: opcional emitir link após check-out (signal).",
        "CRM do Hóspede: histórico do hóspede mostra última nota.",
        "Relatórios: série temporal do score (fase Relatórios).",
    ],
    "fora_desta_fase": [
        "Persistência e cálculos reais.",
        "Campanhas automáticas por faixa (retorno / recuperação).",
        "DRF — API desta fase é JsonResponse stub até o pacote ser instalado.",
    ],
    "documento": "docs/Proposta_NPS.md",
}

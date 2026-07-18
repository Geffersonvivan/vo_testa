"""
Proposta: Instagram → Comercial.

Ainda não implementado. Esta tela registra as opções possíveis para
implementação futura — do mais simples (já funciona via site) ao mais
completo (API oficial da Meta).
"""

PROPOSTA = {
    "titulo": "Instagram → Comercial",
    "status": "proposta",
    "implementado": False,
    "objetivo": (
        "Receber dúvidas e leads vindos do Instagram direto no funil "
        "Comercial (Oportunidade + tarefa), com origem rastreável."
    ),
    "encaixe_crm": [
        "Origem nova: Oportunidade.Origem.INSTAGRAM.",
        "Service público: capturar_lead_instagram(...) — mesmo padrão do site.",
        "Webhook autenticado: POST /crm/comercial/webhook/instagram/ "
        "(token em settings / header).",
        "Tarefa automática: “Responder em 24h” no responsável comercial.",
    ],
    "opcoes": [
        {
            "id": 1,
            "nome": "Link na bio / Stories → site",
            "esforco": "Nenhum (já funciona)",
            "como": (
                "Bio, destaque ou Story com link para "
                "#contato ou #eventos no site. O formulário já cria "
                "oportunidade via capturar_lead_site."
            ),
            "pronto": True,
            "proximos_passos": [
                "Usar URL com UTM (?utm_source=instagram) e, depois, "
                "mapear origem Instagram quando o referrer/UTM vier do IG.",
                "Criar destaque “Reservas” / “Eventos” com o link certo.",
            ],
        },
        {
            "id": 2,
            "nome": "ManyChat / Respond.io (Direct → webhook)",
            "esforco": "Baixo–médio",
            "como": (
                "Ferramenta de inbox Instagram Professional captura o DM, "
                "pede nome/WhatsApp/interesse e dispara webhook para o CRM."
            ),
            "pronto": False,
            "proximos_passos": [
                "Conta Instagram Professional + Meta Business.",
                "Contratar/configurar ManyChat (ou Respond.io / similar).",
                "Fluxo: saudação → nome → WhatsApp → interesse → webhook.",
                "Implementar endpoint + capturar_lead_instagram no Comercial.",
            ],
        },
        {
            "id": 3,
            "nome": "Instagram Lead Ads (anúncio)",
            "esforco": "Médio",
            "como": (
                "Formulário nativo do Meta nos anúncios. Lead sync via "
                "Zapier/Make ou webhook da ferramenta → Comercial."
            ),
            "pronto": False,
            "proximos_passos": [
                "Campanha Lead Ads com campos nome, WhatsApp, interesse.",
                "Conector (Make/Zapier) ou app parceiro → webhook CRM.",
                "Mesmo endpoint do item 2 (origem=instagram, canal=lead_ad).",
            ],
        },
        {
            "id": 4,
            "nome": "API oficial Instagram Messaging (Meta)",
            "esforco": "Alto",
            "como": (
                "App no Meta for Developers recebe webhooks de DM e cria "
                "oportunidade direto — sem ferramenta intermediária."
            ),
            "pronto": False,
            "proximos_passos": [
                "App Meta + App Review "
                "(instagram_manage_messages, pages_manage_metadata…).",
                "Webhook Django com validação X-Hub-Signature-256.",
                "Respeitar janela de 24h e política de mensagens da Meta.",
                "Só vale a pena com volume alto de Direct.",
            ],
        },
    ],
    "recomendacao": (
        "Agora: opção 1 (link). Curto prazo: opção 2 (ManyChat + webhook). "
        "API oficial só se o volume de DM justificar."
    ),
    "fora_desta_fase": [
        "Persistência automática de DMs.",
        "Resposta ao Instagram a partir do CRM.",
        "App Review / tokens Meta em produção.",
    ],
}

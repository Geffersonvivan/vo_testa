# Proposta NPS — Portal do Hóspede + API

**Status:** proposta registrada (não implementada)  
**Fase prevista:** CRM do Hóspede (fase 2, ESPECIFICACAO §8)  
**Código:** `apps/nps/` · painel `/crm/nps/` · API stub `/api/nps/v1/` · UI hóspede `/hospede/<token>/nps/`

## Objetivo

Coletar **Net Promoter Score (0–10)** após a estadia, a partir do portal compartilhado com o hóspede (e depois e-mail/WhatsApp), e consolidar no CRM para relacionamento e melhoria operacional.

## O que já existe nesta entrega (esqueleto)

| Superfície | Onde | Comportamento atual |
|---|---|---|
| Sidebar CRM | Relacionamento → **NPS** | Página da proposta (sem dados reais) |
| Portal do hóspede | Ícone estrela **NPS** na home | Tela “em breve” com escala visual |
| API | `POST/GET /api/nps/v1/…` | **HTTP 501** + JSON com o contrato |

Fonte programática do contrato: `apps/nps/proposta.py` (`PROPOSTA`).

## API (contrato)

Base: `/api/nps/v1/`

### `POST /api/nps/v1/respostas/`

Registrar nota. Autenticação do hóspede via `token` do portal.

```json
{
  "token": "<uuid AcessoPortal>",
  "nota": 9,
  "comentario": "opcional",
  "canal": "portal"
}
```

Regras previstas: nota 0–10; **uma resposta por reserva** (idempotente ou 409); 404 se estadia inválida.

### `GET /api/nps/v1/respostas/<reserva_id>/`

Leitura pela equipe (sessão CRM).

### `GET /api/nps/v1/resumo/?de=&ate=`

Score NPS + contagem detratores (0–6) / passivos (7–8) / promotores (9–10).

## Modelo previsto

`RespostaNPS`: reserva (unique), hóspede, nota, faixa, comentário, canal, criado_em.  
App definitivo pode migrar para `apps/crm_hospede` quando o módulo completo for construído.

## Integrações futuras

- Portal → `POST` na API  
- Sinal pós check-out (Reservas) → link/convite  
- Ficha do hóspede no CRM do Hóspede  
- Série em Relatórios  

## Fora do escopo desta fase

Persistência, cálculo real do score, campanhas por faixa, Django REST Framework (stub usa `JsonResponse`).

## Comercial

Plano de evolução registrado em `docs/Plano_Comercial.md` (ondas P0–P3).
Implementação sob comando explícito por onda — não misturar com a coleta real de NPS.

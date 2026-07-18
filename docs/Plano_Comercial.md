# Plano Comercial — Pousada Vô Testa

**Status:** implementado (17/07/2026) — ondas P0–P3  
**Código:** `apps/comercial/` · captura no site `core:pedir_proposta`  
**Fora deste plano:** coleta real de NPS (`docs/Proposta_NPS.md`); Comercial só faz hand-off.

## Objetivo

Comercial como ferramenta de **aquisição → fechamento**, ligada ao site, com ganho/perda confiáveis. Retenção (NPS, campanhas) permanece no CRM do Hóspede.

## Entregue

### P0 — Confiabilidade + captura
- Ganho no Kanban **bloqueado** sem `reserva_id` (UI + `mover_etapa`)
- Perda no drag abre modal de **motivo obrigatório**
- Form **Pedir proposta** em `#contato` → `capturar_lead_site` (Pessoa + Prospecto + Oportunidade + tarefa 24h)
- Testes cobrindo as regras

### P1 — Cotação e fechamento
- Model `Cotacao` + `registrar_cotacao` (diária via Reservas ou manual, validade, move para “Cotação enviada”)
- `ConversaoForm` pré-preenchido com datas/valor da cotação ou oportunidade
- Sinal opcional via Pagamentos (`criar_sinal`)
- SLA 24h/48h em `pendencias_auditoria`
- Prospecto removido ao converter

### P2 — Aprendizado + ponte
- Sinais `reserva_encerrada` (cancel/no-show) + check-out → anotações e tarefas
- Templates WhatsApp/e-mail copiáveis no detalhe
- Hand-off NPS (`nps_convidado_em` + tarefa)

### P3 — Gestão
- Score 0–100 na oportunidade
- `MetaComercial` no painel (gerência)
- Forecast × realizado × meta; tempo médio por etapa; top scores

## Interface pública relevante

| Função | Uso |
|---|---|
| `capturar_lead_site(...)` | Site |
| `registrar_cotacao(...)` | CRM |
| `converter_em_reserva(..., criar_sinal=)` | CRM |
| `anotar_reserva_encerrada(...)` | Receivers Reservas |
| `templates_mensagem(op)` | UI |
| `dados_gestao(inicio, fim)` | Painel |

## Referências

- Auditoria original: canvas `auditoria-comercial.canvas.tsx`  
- NPS (não misturar): `docs/Proposta_NPS.md`

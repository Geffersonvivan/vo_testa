# Auditoria de Segurança — CRM Pousada Vô Testa

> Relatório vivo. Auditoria de **segurança** (OWASP Top 10 + lógica de negócio), 05/10/2026.
> Método: multiagente (7 dimensões) + verificação adversarial. Lente: pagamentos (Safrapay),
> PII de hóspedes, dados de governo (FNRH), tokens Meta/WhatsApp.
>
> **STATUS 05/10/2026 — CORRIGIDO: todas as Altas não-WIP + 8 das 10 Médias.** 737 testes OK,
> sem commit (aguarda ordem). Ver "Correções aplicadas" no fim.
> **Corrigidos:** S-A1, S-A2, S-A3, S-A4 (completo), S-M1, S-M2, S-M3, S-M4, S-M5, S-M6, S-M7,
> S-M9 + nosniff + timeout de sessão.
> **Deferidos:** S-A5 e open-redirect comercial (**WIP**); S-M8 (token Meta — risco à CAPI
> viva, precisa teste), S-M10 (serviço de /media — amarrado à migração p/ R2); baixas; Fase 4 (MFA/CSP).

## Contexto do programa
Faz parte do programa de segurança iniciado nesta data:
- **Fase 1 (feita):** CVEs de dependência corrigidas (Django 6.0.8, urllib3 2.8, sqlparse 0.6) — pip-audit zerado.
- **Fase 2 (feita):** CI de segurança (`.github/workflows/security.yml`), pre-commit, dependabot, detect-secrets baseline, regras `S` do ruff.
- **Fase 3 (este doc):** auditoria profunda + correção.
- **Fase 4 (próxima):** MFA, CSP, confirmação do SECRET_KEY de prod.

## Postura geral
**Boa base** — ORM puro (zero SQL cru), webhooks com HMAC (fiscal/WhatsApp) e fonte-da-verdade
(Safrapay TM-001), rate-limit (TM-002/003), preços recalculados no servidor, movimentos de
caixa imutáveis com lock, trilha de auditoria append-only, hardening de settings. Os achados
abaixo são **buracos pontuais** nessa base, não ausência de controles.

⚠️ Itens em arquivos **WIP** (Descritivo de Quartos) ficam **flagados, não corrigidos** até o WIP subir.

---

## 🔴 Alta

### S-A1 — SECRET_KEY com fallback inseguro versionado, sem trava em produção
`config/settings.py:22` — `SECRET_KEY = os.environ.get("SECRET_KEY", "dev-inseguro-...")`.
Se a env faltar em produção (novo serviço, rollback de config), o app sobe com a chave
**pública do repositório** → forja de cookie de sessão/tokens assinados = **auth bypass total**.
**Fix:** em `not DEBUG`, `raise ImproperlyConfigured` se a env faltar ou começar com `dev-inseguro`.
**STATUS: a corrigir (não-WIP).**

### S-A2 — Desconto arbitrário no folio → check-out sem pagar (skimming)
`apps/reservas/views.py:493` + `forms.py:69` — qualquer usuário do módulo Reservas (sem
gerência) lança `tipo=desconto` com valor livre, zera o saldo e faz check-out sem receber.
Sem teto nem aprovação. Vetor de desvio de caixa pelo recepcionista. (Fica na trilha, mas não
é barrado.)
**Fix:** exigir `eh_gerente` para desconto e/ou limitar ao saldo; motivo obrigatório.
**STATUS: a corrigir (não-WIP).**

### S-A3 — Upload irrestrito (checklist de Marketing) → XSS armazenado same-origin
`apps/marketing/{views.py:343,services.py:316,models.py:255}` — `FileField` sem validator de
tipo/tamanho; `/media/` é servido **inline, mesmo origin, Content-Type pela extensão**, sem
`nosniff`. Usuário do módulo Marketing sobe `.html`/`.svg` com `<script>`; abrir o link
`/media/...` executa no origin do CRM → rouba sessão de quem clicar.
**Fix:** `FileExtensionValidator` (allowlist) + limite de tamanho + nome randomizado;
`SECURE_CONTENT_TYPE_NOSNIFF=True`; servir mídia sensível por view protegida/attachment (ou R2).
**STATUS: a corrigir (não-WIP).**

### S-A4 — Webhook de pagamento confia no corpo forjado em `simulado` (= produção hoje)
`apps/pagamentos/views.py:436-438` — endpoint público (`csrf_exempt`, sem login); em `simulado`
confirma pelo corpo (`status` vazio = pago). Produção roda em `simulado` (aguardando token
Safrapay). **Nuance verificada:** `GatewaySimulado` gera `gateway_id` aleatório (`SIM-<uuid>`,
difícil adivinhar), MAS o **Pix Direto** usa `gateway_id = VT<pk>` (enumerável, `services.py:73`)
→ POST sem auth `gateway_id=VT1..n` confirma cobranças/reservas sem dinheiro.
**Fix:** não confiar no corpo num endpoint público em produção (gatear a confirmação-por-corpo
em `DEBUG`, ou exigir segredo compartilhado como o fiscal); trocar `VT<pk>` por token opaco.
**STATUS: a corrigir (não-WIP) — mexe no fluxo de pagamento, fazer com cuidado + teste.**

### S-A5 — Busca global vaza PII (nome + CPF) a qualquer usuário logado  ⚠️ WIP
`apps/nucleo/views.py:428-445` — `busca_global` gateia Reserva/Produto por módulo, mas a
ramificação de **Pessoa não checa `Area.PESSOAS`**. Garçom/camareira usa o ⌘K, digita 2+
caracteres e enumera nome + documento (CPF) de toda a base.
**Fix:** guardar a busca de Pessoa com `pode_area(Area.PESSOAS)`.
**STATUS: FLAGADO — arquivo é WIP (`nucleo/views.py`); corrigir quando o WIP subir.**

---

## 🟡 Média

- **S-M1 — Login sem rate-limit/lockout** (`config/urls.py:55`, `LoginView` cru): brute-force/
  credential-stuffing ilimitado contra contas de gerência. Fix: `limite_excedido` por IP+usuário
  numa LoginView custom (ou django-axes) + log na trilha. **Não-WIP.**
- **S-M2 — CSV formula-injection** em `apps/escala/views.py:166,176` e `apps/marketing/views.py:458`
  (nome de pessoa/turno/campanha cru). `sanitizar_celula` já existe e é usado nos outros exports.
  Fix: envolver as células com `sanitizar_celula`. **Não-WIP.**
- **S-M3 — `confirmar_pagamento` sem `select_for_update`** (`apps/pagamentos/services.py:84`):
  TOCTOU — dois gatilhos concorrentes podem duplicar evento/liquidação. Fix: `travar(cobranca)`
  no início (padrão já usado no resto). **Não-WIP.**
- **S-M4 — Erro cru do Safrapay vazado na página pública** (`gateways.py:134` → `views.py:287`):
  `messages.error` mostra `raw[:200]` do provedor a usuário anônimo (oráculo p/ card-testing).
  Fix: mensagem genérica no público, detalhe só no log. **Não-WIP.**
- **S-M5 — Payload Safrapay persistido com PII do pagador sem redação** (`gateways.py:362`,
  `services.py:261`): `Cobranca.payload` salva a resposta íntegra (nome/CPF/endereço) sem o
  `_redigir()` que o webhook aplica. Fix: redigir/allowlist antes de salvar. **Não-WIP.**
- **S-M6 — Webhook WhatsApp falha-aberto sem `WHATSAPP_APP_SECRET`** (`views_whatsapp.py:30`):
  `if not segredo: return True` aceita POST forjado se a env faltar com gateway real ligado.
  Fix: falhar fechado quando `WHATSAPP_GATEWAY != simulado`. **Não-WIP.**
- **S-M7 — Open redirect via `next`** (`apps/marketing/views.py:77`): `redirect(next)` sem
  `url_has_allowed_host_and_scheme`. Fix: validar host. **Não-WIP.** (Há um gêmeo em
  `comercial/views.py:315`, guardado por `startswith('/crm/')` — **WIP**, endurecer depois.)
- **S-M8 — Meta CAPI: `access_token` na query string + URL montada com `id_externo` de DB**
  (`comercial/midia_gateways.py:124,170`): token vaza em logs de proxy/erro; `id_externo` com
  `@`/`/` permite param/host confusion. Fix: token no header; validar `id_externo` (regex) e
  `urlencode`. **Não-WIP.**
- **S-M9 — `minha_reserva` (site) sem rate-limit** (`apps/site/views.py:932`): login sobrenome+
  código sem `limite_excedido` → brute-force de PII da reserva. Fix: aplicar o rate-limit. **Não-WIP.**
- **S-M10 — `/media/` sem auth expõe anexos internos de marketing** (`config/urls.py:83`):
  briefings/artes baixáveis por URL. Fix: view protegida/R2 p/ uploads sensíveis. **Não-WIP.**

## 🟢 Baixa (defesa em profundidade)
- SSRF defense-in-depth: `urlopen` dos gateways sem validar esquema https (URLs vêm de settings,
  confiáveis) — criar helper HTTP único que exija `https://`.
- `criar_cobranca`: cast de `valor`/`parcelas` do POST sem try/except → 500 em entrada não numérica.
- Sessão sem `SESSION_COOKIE_AGE`/`EXPIRE_AT_BROWSER_CLOSE` (terminal compartilhado de recepção).
- Token do portal (`AcessoPortal`) sem expiração/revogação (uuid4, inerte após checkout).
- `lancar_na_conta` cria sem `full_clean` (MinValueValidator não aplicado; hoje todos chamadores passam valor do servidor).
- Reserva do site sem teto de intervalo de datas (pré-reserva longa segura quarto).
- Webhook fiscal: token estático sem nonce (replay; idempotente, baixo impacto).
- `WHATSAPP_VERIFY_TOKEN` comparado com `==` (não `compare_digest`).
- `ImageField` do site sem `FileExtensionValidator` (proteção implícita via Pillow).

## Fase 4 (hardening dedicado) — FEITA (05/10/2026)
- ✅ **MFA/2FA (TOTP)** — opt-in para todos, **obrigatório para superusuários** (middleware
  força a ativação). QR de provisionamento, confirmação por código, **códigos de backup**
  (uso único, com hash), desafio de 2º fator no login (`apps/nucleo/mfa.py`, `mfa_views.py`,
  `auth_views.py`; rotas `/crm/mfa/…`; link "MFA" no rodapé da sidebar). Testes em
  `apps/nucleo/tests_mfa.py`. Model: `Usuario.mfa_secret/mfa_ativo/mfa_backup_codes`
  (migração `nucleo.0037_usuario_mfa`).
- ✅ **CSP** (Content-Security-Policy) — `apps/nucleo/security_headers.py`, **report-only**
  por padrão (`CSP_REPORT_ONLY=1`), vira bloqueio quando o console estiver limpo; próximo
  passo é migrar inline→nonce e remover `'unsafe-inline'`.
- ✅ **SECRET_KEY de produção** — trava S-A1 garante que não sobe com o default de dev.
- ✅ **nosniff** global + **timeout de sessão** (10h, renovável).

---

## Verificado como NÃO-vulnerável (não reportado)
Preços server-side (não do POST); descontos de PDV limitados ao subtotal; movimentos de caixa
imutáveis + lock; estorno/reabertura/cancelamento com gerência + auditados; check-out barrado
por saldo; tokens uuid4/secrets (portal/pagamento/site); privilege-escalation gateado por
`eh_gerente` (não rebaixa a si/superuser); FNRH formset escopado por reserva; FNRH é campo de DB
(não upload); zero SQL cru / `eval` / `subprocess` / `mark_safe`; `|safe` só em SVG de QR
server-gerado; `json_script` auto-escapa.

# Plano de implementação — Campanhas de WhatsApp + Opt-in nas LPs

> Passo a passo para implementar **futuramente** duas peças que faltam para
> operar marketing por WhatsApp pelo CRM:
> **(A)** check-box de aceite (opt-in) nas landing pages / form do site;
> **(B)** tela de gestão e disparo de **campanhas de WhatsApp**.
>
> **Estratégia:** espelhar a **campanha de e-mail**, que já está 100% pronta
> (model + serviços + telas), e reusar o que já existe no WhatsApp (opt-in,
> opt-out, motor de disparo). Praticamente nada é do zero.

---

## 0. Estado atual (o que já existe — NÃO refazer)

| Peça | Onde | Status |
|---|---|---|
| Opt-in/opt-out do WhatsApp | `nucleo.Pessoa.aceita_whatsapp` + `whatsapp_optin_em` | ✅ campo existe |
| Opt-out automático por "sair/parar" | `comercial/services.py` → `_marcar_opt_out` / `_OPT_OUT` | ✅ |
| Motor de disparo (respeita opt-in) | `comercial/services.py` → `disparar_campanha_whatsapp(...)` | ✅ (só por código/shell) |
| Envio por lead (template Meta) | `comercial/services.py` → `enviar_template_whatsapp(...)` | ✅ |
| Resolvedor de segmento do funil | `comercial/services.py` → `publico_da_campanha(segmento)` (etapa/origem/pagina/temperatura/status) | ✅ (usado pelo e-mail) |
| Captura de lead do site (concede opt-in) | `comercial/services.py` → `capturar_lead_site(...)` (hoje liga WhatsApp **junto** do e-mail) | ⚠️ ajustar |
| **Referência a espelhar: campanha de E-MAIL** | `CampanhaEmail` (models) · `email_campanha_*` (views/urls) · `templates/comercial/email/*` | ✅ pronto |

**Pré-requisito de produção:** o **envio** ainda está bloqueado pela Meta
(WABA erro **141008**, forma de pagamento/Índia — ver `docs/Evidencia_WhatsApp_141008.*`).
As duas features abaixo podem ser **construídas e testadas em `WHATSAPP_GATEWAY=simulado`**;
só começam a disparar de verdade quando o envio for destravado.

---

## FEATURE A — Check-box de opt-in de WhatsApp nas LPs / site

**Objetivo:** coletar consentimento **explícito e separado** para WhatsApp (hoje é
concedido "de carona" com o e-mail), com prova para LGPD e política da Meta.

### A.1 — Backend: separar o consentimento
- [ ] Em `capturar_lead_site(...)` (`comercial/services.py`, ~linha 412): adicionar o
      parâmetro **`aceita_whatsapp=None`** (separado do `aceita_email`).
- [ ] No bloco de consentimento (~linha 516): gravar `aceita_whatsapp=True` +
      `whatsapp_optin_em=now()` **apenas quando `aceita_whatsapp` vier marcado** —
      desacoplar do `aceita_email`.
- [ ] (Opcional, LGPD) gravar a **origem do opt-in** (página/LP + IP) no
      `whatsapp_optin_fonte` (novo `CharField`, migração) para trilha de prova.

### A.2 — Front: o checkbox nos formulários
- [ ] Adicionar um checkbox dedicado nos forms de captação do site
      (`apps/site/templates/...` dos forms "Pedir proposta" / `#contato` / `#eventos`
      e nas LPs de `comercial` — `templates/comercial/captacao_publica.html`):
      **"Aceito receber novidades e ofertas da Pousada Vô Testa no WhatsApp."**
- [ ] Enviar esse campo no POST e repassar em `aceita_whatsapp` na chamada a
      `capturar_lead_site`.
- [ ] Texto curto de privacidade ao lado: "Você pode sair quando quiser respondendo
      *sair*." (link para a política).
- [ ] **Design:** usar os tokens Lampião (checkbox já tem `accent-color: var(--lampiao)`);
      não hard-codear.

### A.3 — Descadastro (opt-out) explícito
- [ ] O opt-out por palavra ("sair/parar") **já funciona**. Avaliar também um **link de
      descadastro** (espelhar `templates/comercial/email/descadastro.html`) para WhatsApp,
      ou deixar só o fluxo por palavra (recomendado: manter simples).

### A.4 — Testes
- [ ] `aceita_whatsapp=True` → `Pessoa.aceita_whatsapp=True` + `whatsapp_optin_em` preenchido.
- [ ] `aceita_whatsapp` ausente/False → **não** liga o opt-in (mesmo com e-mail marcado).
- [ ] Opt-in não regride um opt-out anterior sem novo consentimento.

**Arquivos tocados (Feature A):** `comercial/services.py`, forms/templates do site e das LPs,
migração do `nucleo.Pessoa` (se adicionar `whatsapp_optin_fonte`), `comercial/tests.py`.

---

## FEATURE B — Gestão e disparo de campanhas de WhatsApp

**Objetivo:** tela para **montar segmento → escolher template aprovado → prever
público/custo → enviar (com pacing) → acompanhar resultados**. Espelhar a campanha de e-mail.

### B.1 — Model `CampanhaWhatsApp`
- [ ] Criar em `comercial/models.py`, espelhando `CampanhaEmail` (linha ~966):
      - `nome` (CharField)
      - `template_nome` (CharField) + `idioma` (CharField, default `pt_BR`) — **o template
        vive na Meta** (aprovado), aqui guarda-se só o **nome/idioma**, não o corpo.
      - `categoria` (choices: marketing/utility — para estimar custo)
      - `variaveis` (JSONField) — mapeamento das variáveis `{{1}}`, `{{2}}`… (ex.: `{{1}}` = primeiro nome)
      - `segmento` (JSONField) — mesmos filtros do e-mail (etapa/origem/pagina/temperatura/status)
      - `status` (RASCUNHO/AGENDADA/ENVIANDO/ENVIADA/CANCELADA)
      - `agendar_para` (DateTimeField, null)
      - contadores desnormalizados: `total`, `enviados`, `erros`, `pulados`
      - `custo_estimado` (DecimalField) — `total × tarifa da categoria`
      - `criado_por`, `criado_em`, `enviada_em`
- [ ] (Idempotência/resultados) ligar os `MensagemWhatsApp` de saída à campanha:
      adicionar FK `campanha` (null) em `MensagemWhatsApp`, ou criar um `EnvioWhatsApp`
      (espelhando `EnvioEmail`) por destinatário. **Recomendado:** FK em `MensagemWhatsApp`
      (reaproveita status via webhook).
- [ ] Migração.

### B.2 — Serviços (reusar o que existe)
- [ ] `criar_campanha_whatsapp(*, nome, template_nome, idioma, categoria, variaveis, segmento, usuario, agendar_para=None)`
      — espelhar `criar_campanha_email` (~linha 2184). Calcula `total` via
      **`publico_da_campanha(segmento)`** (já existe!) filtrando quem tem telefone + opt-in,
      e `custo_estimado = total × tarifa`.
- [ ] `enviar_campanha_whatsapp(campanha)` — materializa o envio:
      - resolve o público com `publico_da_campanha` (**reusar**);
      - itera chamando `enviar_template_whatsapp(...)` (**reusar**) com `campanha=` setado;
      - respeita opt-in/telefone (o `disparar_campanha_whatsapp` já faz esse filtro — pode
        **refatorar** `disparar_campanha_whatsapp` para aceitar `campanha=` e atualizar os contadores);
      - **idempotente** por (campanha, pessoa) — não reenvia a quem já recebeu.
- [ ] **Templates aprovados (picker):** `listar_templates_aprovados()` — busca via Graph API
      `GET /{WABA}/message_templates?status=APPROVED&fields=name,language,category,components`
      (usar `WHATSAPP_CLOUD_TOKEN`), **cacheia** (ex.: 10 min) e devolve nome/idioma/categoria/
      variáveis para popular o seletor. Sem isso não dá para escolher template na tela.

### B.3 — ⚠️ Pacing / limite de mensagens (CRÍTICO)
- [ ] A Meta limita **destinatários únicos / 24h** pelo **messaging tier** (hoje `TIER_250`).
      Campanha grande **não pode** disparar tudo de uma vez.
- [ ] Implementar **envio em lotes com cron** (padrão do projeto, ex.: `manage.py enviar_fnrh_pendentes`):
      um comando `manage.py enviar_campanhas_whatsapp` processa N por rodada respeitando o tier,
      marca a campanha `ENVIANDO`→`ENVIADA` quando o público acaba.
- [ ] Ler o tier atual via API (`GET /{PHONE_ID}?fields=messaging_limit_tier`) para dimensionar o lote.

### B.4 — Views / URLs (espelhar e-mail)
- [ ] Rotas em `comercial/urls.py` espelhando `email_campanha_*`:
      - `whatsapp/campanhas/` (lista) → `whatsapp_campanhas`
      - `whatsapp/campanhas/nova/` → `whatsapp_campanha_nova`
      - `whatsapp/campanhas/<pk>/` → `whatsapp_campanha_detalhe`
      - `whatsapp/campanhas/<pk>/enviar/` → `whatsapp_campanha_enviar`
      - `whatsapp/campanhas/<pk>/teste/` → `whatsapp_campanha_teste` (envia só para 1 número)
- [ ] Proteções: `@requer_modulo(Modulo.COMERCIAL)` (+ gerência para disparar).

### B.5 — Templates (telas) — espelhar `templates/comercial/email/`
- [ ] `whatsapp/campanhas_lista.html` — lista com status + contadores (enviados/erros/pulados) + custo.
- [ ] `whatsapp/campanha_form.html` — seletor de **template aprovado** (do B.2) + **construtor de
      segmento** (reusar os mesmos filtros do e-mail: etapa/origem/pagina/temperatura) +
      **preview do público e do custo estimado** (`total × R$0,35` marketing) + agendar.
- [ ] `whatsapp/campanha_detalhe.html` — resultados: enviados/entregues/lidos/respondidos/
      opt-outs (status vindo do **webhook**) + barra de progresso + botão enviar/cancelar.
- [ ] **Design Lampião obrigatório:** `.cartao`, `.tabela/.quadro`, `.botao-primario`, `.selo-*`,
      KPIs; envolver em `comercial/_estilo_elegante.html`. Nada hard-codeado.

### B.6 — Item de menu
- [ ] Adicionar "Campanhas WhatsApp" na sidebar (seção Comercial/Relacionamento),
      respeitando `@requer_modulo` / `|modulo_ativo`.

### B.7 — Testes
- [ ] `criar_campanha_whatsapp` calcula `total` só com opt-in + telefone; custo correto.
- [ ] `enviar_campanha_whatsapp` é **idempotente** (não reenvia ao mesmo lead).
- [ ] Respeita opt-out (quem deu "sair" é pulado).
- [ ] Pacing: o cron envia no máximo o tamanho do lote por rodada.
- [ ] Gateway `simulado`: campanha completa de ponta a ponta sem rede.

**Arquivos tocados (Feature B):** `comercial/models.py` (+ migração), `comercial/services.py`,
`comercial/views.py`, `comercial/urls.py`, `templates/comercial/whatsapp/*`,
`comercial/management/commands/enviar_campanhas_whatsapp.py`, `base.html` (menu),
`comercial/tests.py`.

---

## Conformidade (Meta + LGPD) — não quebrar
- **Só opt-in.** Nunca disparar para lista comprada / sem consentimento → risco de **ban da WABA**
  por qualidade. O filtro já existe no motor; a **tela nunca deve permitir burlar** isso.
- **Template aprovado obrigatório** para mensagem iniciada pela empresa (fora da janela de 24h).
  Categoria **marketing** custa (~R$0,35/msg); **utilidade** é mais barata e às vezes grátis na janela.
- **Opt-out sempre honrado** (palavra "sair" já desliga; não reativar sem novo opt-in).
- **Segmentar, não blast geral** — reduz custo, sobe conversão e **protege a qualidade/quality rating**
  da WABA (blast repetido para base fria derruba o rating e pode bloquear).
- **LGPD:** guardar `whatsapp_optin_em` (quando) e, idealmente, a fonte do consentimento.

---

## Ordem sugerida de implementação
1. **Feature A** (opt-in) primeiro — é o que **constrói a base limpa**; sem isso a campanha
   não tem para quem enviar com segurança.
2. **Feature B.1–B.2** (model + serviços) — já testável no `simulado`.
3. **B.3** (pacing/cron) — essencial antes de qualquer disparo real.
4. **B.4–B.6** (telas + menu).
5. Ligar em produção **só depois** de destravar o envio na Meta (141008).

## Referências no repo
- Espelho e-mail: `CampanhaEmail`/`EnvioEmail` (models), `criar_campanha_email`/`enviar_campanha_email`
  (services), `templates/comercial/email/*`, rotas `email_campanha_*` em `comercial/urls.py`.
- WhatsApp existente: `disparar_campanha_whatsapp`, `enviar_template_whatsapp`,
  `publico_da_campanha`, `_marcar_opt_out`, `nucleo.Pessoa.aceita_whatsapp/whatsapp_optin_em`.
- Custo/projeção: ver a estimativa de custo (R$0,35/msg marketing; break-even ~0,06%).
- Bloqueio de envio: `docs/Evidencia_WhatsApp_141008.md` / `.png`.

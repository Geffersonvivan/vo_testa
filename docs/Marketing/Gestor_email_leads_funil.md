# Gestor de E-mail dos Leads do Funil — Comercial

> Roteiro de implementação, fase a fase. Este doc é o **plano construível** do e-mail
> atrelado ao lead/funil (envio 1:1 pedido pelo cliente + campanha por segmento), com
> o motor de template/variáveis compartilhado. Estratégia e infra de entregabilidade
> (SES, DNS, LGPD) vivem em [`Gestor_Email_MKT_Massa.md`](./Gestor_Email_MKT_Massa.md) — aqui é o
> **como fazer** dentro do `apps/comercial`.

## Panorama

Um **motor de template + variáveis** alimenta **dois caminhos**:

- **1:1** — botão no lead compõe o e-mail com a cotação, os valores acordados e o
  resumo da conversa, e envia para 1 pessoa (transacional).
- **Massa** — o mesmo template, preenchido por destinatário, dispara para um segmento
  do funil (via SES / subdomínio `news.`).

Regras herdadas do projeto: gateway plugável (`EMAIL_GATEWAY = simulado | ses`),
`simulado` default (sem rede), envios **imutáveis** (`EnvioEmail` append-only), **sem
Celery** (management command + cron), só **opt-in** (LGPD), design **Lampião**,
`@requer_modulo(Modulo.COMERCIAL)`.

---

## FASE 1 — Motor de e-mail + envio 1:1 no lead

**Objetivo:** o botão "Enviar por e-mail" no lead, funcionando ponta a ponta no gateway
simulado. Não depende da AWS.

### 1.1 Gateway plugável
- `apps/comercial/email_gateways.py`: `get_email_gateway()` lê `settings.EMAIL_GATEWAY`.
- Interface `enviar(*, para, assunto, html, texto, headers) -> {message_id, status}`.
- `simulado`: sem rede, `message_id` fake, loga; hook para forçar bounce em teste.

### 1.2 Motor de template + variáveis
- Reusar o preenchedor de variáveis das Respostas Rápidas do WhatsApp
  (`aplicar_variaveis_*`) e generalizar para e-mail.
- Variáveis mínimas: `{primeiro_nome}`, `{nome}`, `{quarto}`, `{checkin}`, `{checkout}`,
  `{noites}`, `{pessoas}`, `{total}`, `{sinal}`, `{restante}`, `{validade}`, `{link}`.
- `services.montar_proposta_email(op, cobranca=None, link=None) -> {assunto, html, texto}`
  — irmã HTML da já existente `montar_proposta_sinal` (texto/WhatsApp). Nasce no visual
  Lampião: logo, cartão da estadia, botão dourado.

### 1.3 Captura do que foi conversado
- `services.resumo_da_conversa(op) -> [linhas]`: últimas N mensagens do WhatsApp
  (`MensagemWhatsApp`) + eventos relevantes da Linha do tempo (`AtividadeComercial`),
  virando o bloco "O que combinamos".
- Puxa dados estruturados: última `Cotacao`, `valor_estimado`, datas, pessoas/quartos.

### 1.4 Ação no lead (view + UI)
- Botão **"Enviar por e-mail"** nas Ações rápidas de `oportunidade.html`.
- View `enviar_email_lead` (POST): monta com `montar_proposta_email`, abre um
  **preview editável** (assunto + corpo), com **"enviar teste pra mim"** e "enviar ao
  lead". Exige e-mail no cadastro (senão, pede pra preencher).
- Ao enviar: grava `EnvioEmail`, registra na **trilha** (`_log_evento`: "enviou e-mail
  da proposta"), toast de sucesso.

### 1.5 Registro (append-only)
- Model **`EnvioEmail`** (compartilhado com o massa): FK opcional `campanha`, FK
  `oportunidade`/`pessoa`, `email`, `assunto`, `status`
  (pendente→enviado→entregue→bounce→reclamado / aberto), `message_id`, `erro`,
  `enviado_em`, `evento_em`. Índice em `message_id`.

### 1.6 Testes
- `montar_proposta_email` preenche variáveis e formata BRL; inclui link quando há sinal.
- `resumo_da_conversa` traz as últimas mensagens; degrada sem WhatsApp.
- Enviar 1:1 grava `EnvioEmail` + evento na trilha; sem e-mail no cadastro → erro amigável.
- Gateway `simulado` não faz rede.

### 1.7 Entregáveis
`email_gateways.py` (simulado), `montar_proposta_email`, `resumo_da_conversa`, model
`EnvioEmail` + migração, view + botão + preview, testes. **Sem tocar em produção.**

---

## FASE 2 — Template salvável + biblioteca

**Objetivo:** transformar o e-mail montado em ativo reutilizável (e base de campanha).

### 2.1 Model `TemplateEmail`
- `nome`, `assunto`, `corpo_html`, `variaveis` (detectadas), `blocos_opcionais` (JSON:
  quais blocos são 1:1 — resumo/link — e ficam OFF no massa), `criado_por`, timestamps.
- Seed com 2–3 prontos (proposta, follow-up "ainda dá tempo", pós-cotação).

### 2.2 Salvar do lead / aplicar
- No preview do 1:1: **"salvar como template"**.
- Escolher um template ao compor (1:1 ou campanha) → preenche variáveis.

### 2.3 Biblioteca (tela)
- CRUD de templates em `comercial/email/templates/` (lista + form), preview com dados
  de exemplo. Design Lampião.

### 2.4 Testes
- Salvar do lead cria `TemplateEmail`; aplicar preenche variáveis; blocos 1:1 desligam.

---

## FASE 3 — Campanha por segmento do funil

**Objetivo:** disparar o mesmo template para um recorte do funil. (Casa com as Fases 1/2
do `Gestor_Email_MKT_Massa.md`.)

### 3.1 Opt-in / descadastro (LGPD)
- Campos em `Pessoa`: `aceita_email`, `email_opt_in_em`, `email_opt_out_em`,
  `unsub_token` (UUID).
- Rota pública `/email/descadastrar/<token>/` (fora do `/crm/`) + página no visual da
  marca. Todo e-mail leva o link no rodapé + header `List-Unsubscribe`.
- Checkbox de consentimento no form da LP (opt-in explícito).

### 3.2 Model `CampanhaEmail`
- `nome`, `assunto`, `template`/corpo, `remetente`, `segmento` (JSON de filtros),
  `status` (rascunho→agendada→enviando→enviada→cancelada), `agendar_para`,
  contadores desnormalizados (enviados/entregues/bounces/reclamações/aberturas/descadastros).

### 3.3 Segmentação (reusa o funil)
- `services.publico_da_campanha(segmento)` → `Pessoa` com e-mail válido, `aceita_email`,
  filtrado por etapa, `temperatura`, origem/LP (`pagina_captacao`), papel, período.
- Sempre exclui opt-out e bounce duro.

### 3.4 Envio em lote (sem Celery)
- `manage.py enviar_campanha_email`: materializa `EnvioEmail` pendentes (idempotente),
  dispara em blocos com **throttling**. Marca `enviada` ao fim.
- **Cron do Railway** roda o comando periodicamente (backstop do agendamento).

### 3.5 Painel
- Lista/criar/agendar campanha, escolher segmento + template, **enviar teste**,
  pré-visualizar. Detalhe com métricas. Botão "duplicar".

### 3.6 Testes
- Segmentação respeita opt-out/bounce; envio idempotente (2× não duplica); descadastro
  remove da base; contadores batem.

---

## FASE 4 — SES real + retorno de bounce

> Depende da **Fase 0** do `Gestor_Email_MKT_Massa.md` (conta AWS, DNS/DKIM/SPF/DMARC, saída
> do sandbox).

### 4.1 Gateway `ses`
- `boto3` `ses:SendRawEmail` (suporta `List-Unsubscribe` + multipart) ou SMTP do SES.
- Remetente de marketing por `news.pousadavotesta.com.br`; 1:1 pode seguir transacional.

### 4.2 Webhook SNS (proteção da reputação)
- SES → SNS → endpoint csrf-exempt `/email/sns/`. Bounce duro/reclamação → `aceita_email
  =False` + atualiza `EnvioEmail` (casa por `message_id`). Some da base automaticamente.
- (Opcional) pixel de abertura → taxa de abertura.

### 4.3 Aquecimento
- Rampa gradual de volume nas primeiras semanas do subdomínio.

---

## FASE 5 — Refinamentos (depois)

- Editor de blocos/arrastar; A/B de assunto.
- Automação por evento (pós-checkout → NPS/reengajamento) — amarra com CRM do Hóspede.
- Relatório de e-mail no módulo Relatórios (mês/ano).
- Variáveis avançadas e personalização por papel (agência/operadora vs hóspede direto).

---

## Ordem recomendada

1. **Fase 1** (motor + 1:1) — entrega valor imediato ao vendedor, sem AWS.
2. **Fase 2** (template salvável) — cria o ativo reutilizável.
3. **Fase 0 do Email_MKT** em paralelo (DNS/SES têm prazo).
4. **Fase 3** (campanha por segmento) — já roda no simulado; liga no SES depois.
5. **Fase 4** (SES real + bounce) quando a infra fechar.
6. **Fase 5** conforme a operação pedir.

## Dependências e reuso

- **Reusa:** `montar_proposta_sinal` (copy), motor de variáveis das Respostas Rápidas,
  `MensagemWhatsApp`/`AtividadeComercial` (resumo), `Cotacao`/`Oportunidade` (dados),
  design Lampião, padrão de gateway plugável.
- **Compartilha com o massa:** `EmailGateway`, `EnvioEmail`, `TemplateEmail`,
  opt-in/descadastro.
- **Novo:** `email_gateways.py`, `montar_proposta_email`, `resumo_da_conversa`,
  `EnvioEmail`, `TemplateEmail`, `CampanhaEmail`, rota de descadastro, command + cron,
  painel.

## Resumo

Fase 1 entrega o **"Enviar por e-mail" no lead** (captura cotação + valores + resumo da
conversa, HTML bonito, registrado na trilha) rodando no gateway simulado. Fase 2 torna o
e-mail um **template reutilizável**. Fases 3–4 usam o **mesmo template** para **campanha
por segmento do funil** via **SES**, com LGPD e limpeza automática por bounce. O motor de
template/variáveis nasce **compartilhado** entre o 1:1 e o massa — zero retrabalho.

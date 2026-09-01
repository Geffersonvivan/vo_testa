# Gestor de E-mail Marketing (Campanhas em Massa) — Comercial

> Documento vivo. Guia para implementarmos ao longo do tempo, por fases.
> **Decisões já tomadas:** caminho **A** (campanha vive **dentro do CRM**, ao lado do
> funil) · provedor de envio **Amazon SES** · envio de marketing por **subdomínio
> dedicado** (`news.pousadavotesta.com.br`) para não contaminar o transacional.

## Objetivo

Disparar campanhas de e-mail em massa (lançamento, ofertas, reengajamento) **de dentro
do CRM**, segmentando pela base do funil (etapa, temperatura, origem, papel), com
entregabilidade e conformidade LGPD — sem queimar a reputação do domínio nem depender de
uma ferramenta externa para montar a campanha.

## Princípios (o que não se quebra)

- **Transacional ≠ marketing.** Confirmação de reserva / link de sinal continuam saindo
  pelo caminho atual (SMTP Zoho, `apps/site/emails.py`). **Campanha em massa NUNCA sai
  pelo Zoho** — vai pelo SES, por um remetente/subdomínio separado.
- **Só com opt-in.** Envia apenas para quem consentiu. Nada de lista comprada.
  Descadastro visível e respeitado (LGPD).
- **Gateway plugável**, igual aos outros módulos (`WHATSAPP_GATEWAY`,
  `PAGAMENTOS_GATEWAY`, `FISCAL_GATEWAY`): `EMAIL_GATEWAY = simulado | ses`.
  `simulado` é o default (sandbox, sem rede) — dev e testes nunca disparam de verdade.
- **Movimentos imutáveis.** Cada envio a um destinatário é um registro append-only
  (`EnvioEmail`) — status, message-id, bounce, reclamação, abertura. Correção = novo
  registro, nunca update destrutivo.
- **Sem Celery** (Railway = gunicorn): o disparo em lote é **management command + cron**,
  nunca um loop dentro do request.
- **Design Lampião**: toda tela nasce no design system (tokens + `_estilo_elegante`).

## Arquitetura (caminho A)

```
[CRM: CampanhaEmail]
   │  segmenta a base pelo funil (etapa/temperatura/origem/papel + aceita_email)
   ▼
[EnvioEmail por destinatário]  ← livro-razão (pendente→enviado→entregue/bounce/reclamado/aberto)
   │  management command em lote (cron do Railway), com throttling
   ▼
[EMAIL_GATEWAY: ses]  → Amazon SES (sa-east-1), remetente news.pousadavotesta.com.br
   ▲
   │  SNS → webhook  (bounce / reclamação / entrega)
[remove da lista automaticamente → protege a reputação]
```

---

# FASE 0 — Infra de envio (pré-requisito para disparo real)

> Parte é **ação do operador** (conta AWS, DNS). O código não depende disto: a Fase 1
> roda inteira no gateway `simulado`.

## 0.1 Conta AWS + SES
- Criar conta AWS; abrir **SES** na região **`sa-east-1`** (São Paulo).
- SES começa em **sandbox**: só envia para e-mails/domínios **verificados**. Ótimo para
  testar ponta a ponta antes de liberar.

## 0.2 Verificar identidade e gerar DKIM
- Verificar o **subdomínio** `news.pousadavotesta.com.br` (identidade de domínio).
- SES gera **3 CNAMEs de DKIM** — anotar.

## 0.3 DNS (no provedor onde o domínio está hospedado)
- **SPF** (TXT no subdomínio): `v=spf1 include:amazonses.com ~all`.
- **DKIM**: os 3 CNAMEs gerados pelo SES.
- **DMARC** (TXT em `_dmarc.pousadavotesta.com.br`): começar em
  `v=DMARC1; p=none; rua=mailto:dmarc@pousadavotesta.com.br` (monitorar) e endurecer
  depois (`quarantine` → `reject`).
- **MAIL FROM personalizado** (opcional, recomendado): `bounce.news.pousadavotesta...`
  para alinhar SPF.

## 0.4 Sair do sandbox
- Abrir o formulário da AWS: caso de uso (pousada, base opt-in), volume estimado, e
  **como tratamos bounce/reclamação/descadastro** (apontar para este doc).

## 0.5 Credenciais no ambiente (Railway)
```
EMAIL_GATEWAY=ses
AWS_SES_REGION=sa-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...        # usuário IAM só com permissão ses:SendEmail/SendRawEmail
EMAIL_MKT_FROM="Pousada Vô Testa <novidades@news.pousadavotesta.com.br>"
EMAIL_MKT_REPLY_TO=contato@pousadavotesta.com.br
```

## 0.6 Checklist Fase 0
- [ ] Conta AWS + SES em `sa-east-1`
- [ ] Subdomínio `news.` verificado
- [ ] SPF + 3× DKIM + DMARC no DNS (propagados)
- [ ] MAIL FROM personalizado (opcional)
- [ ] Saída do sandbox aprovada
- [ ] Variáveis no Railway (produção)

---

# FASE 1 — Scaffold no CRM (construir já, sem depender da AWS)

Roda 100% no gateway `simulado`. Entregável testável antes de qualquer conta AWS.

## 1.1 Gateway plugável — `apps/comercial/email_gateways.py`
- `get_email_gateway()` lê `settings.EMAIL_GATEWAY` (`simulado` default).
- Interface: `enviar(destinatario, assunto, html, texto, headers) -> {message_id, status}`.
- `simulado`: não faz rede, gera `message_id` fake, loga; permite forçar bounce em teste.
- `ses`: preenchido na Fase 2.

## 1.2 Models — `apps/comercial/models.py`
- **`CampanhaEmail`**: `nome`, `assunto`, `remetente`, `corpo_html`, `corpo_texto`
  (auto do html), `status` (rascunho→agendada→enviando→enviada→cancelada),
  `agendar_para` (nullable), `segmento` (JSON com os filtros), `criado_por`, timestamps,
  contadores desnormalizados (enviados/entregues/bounces/reclamações/aberturas/descadastros).
- **`EnvioEmail`** (append-only, 1 por destinatário): FK campanha, FK pessoa, `email`,
  `status` (pendente→enviado→entregue→bounce→reclamado / aberto), `message_id`,
  `erro`, `enviado_em`, `evento_em`. Índice por `message_id` (casar o webhook).
- **`ContatoEmail`** (opt-in/descadastro) — OU um campo em `Pessoa`:
  `aceita_email` (bool), `email_opt_in_em`, `email_opt_out_em`, `unsub_token` (UUID).
  Decisão: começar com **campos em `Pessoa`** (base única) + token para o link público.

## 1.3 Segmentação (reusar o funil)
- `services.publico_da_campanha(segmento)` → queryset de `Pessoa` com e-mail válido e
  `aceita_email=True`, filtrado por: etapa do funil, `temperatura`, `origem`/LP
  (`pagina_captacao`), papel (hóspede/cliente/agência), período do lead.
- Sempre exclui quem deu opt-out e quem já tem bounce duro registrado.

## 1.4 Descadastro (LGPD) — rota pública fora do `/crm/`
- `/email/descadastrar/<token>/` (sem login): marca `aceita_email=False`,
  `email_opt_out_em=now`, registra na trilha. Página de confirmação no visual da marca.
- **Todo e-mail leva** o link no rodapé + header `List-Unsubscribe` (one-click).

## 1.5 Envio em lote — `manage.py enviar_campanha_email`
- Pega campanhas `agendada` com `agendar_para <= now` (ou `--campanha <id>`), materializa
  os `EnvioEmail` pendentes (idempotente — não recria) e dispara em blocos com
  **throttling** ao limite do gateway. Marca `enviada` ao fim.
- **Cron do Railway** roda o comando de X em X min (backstop do agendamento).
- Best-effort: falha de um destinatário não derruba o lote (registra `erro` no `EnvioEmail`).

## 1.6 Painel (dentro do Comercial, `@requer_modulo(COMERCIAL)`)
- Lista de campanhas + criar/editar (assunto, corpo, remetente, segmento, agendar).
- Pré-visualização + **enviar teste** para 1 e-mail.
- Detalhe com métricas: enviados, entregues, bounces, reclamações, aberturas, descadastros.
- Botão "Duplicar campanha". Design Lampião (`.eleg` + `_estilo_elegante`).

## 1.7 Testes
- Segmentação respeita `aceita_email`, opt-out e bounce.
- `enviar_campanha_email` é **idempotente** (rodar 2× não duplica envio).
- Descadastro remove da base e não volta a ser incluído.
- Gateway `simulado` não faz rede; contadores batem.

## 1.8 Entregáveis da Fase 1
- `email_gateways.py` (simulado), models + migração, services de segmentação,
  rota+página de descadastro, command de lote, painel, testes. **Sem tocar em produção.**

---

# FASE 2 — SES real + retorno de bounce (quando a Fase 0 fechar)

## 2.1 Gateway `ses`
- `boto3` (`ses:SendRawEmail` para suportar `List-Unsubscribe` e multipart) OU SMTP do SES.
- Respeita o limite de envio da conta (rate) — throttling no command.

## 2.2 Webhook de bounce/reclamação (proteção da reputação)
- SES → **SNS** → endpoint `pagamentos`-style csrf-exempt `/email/sns/`.
- Bounce **duro** ou **reclamação** → marca a pessoa `aceita_email=False` + registra no
  `EnvioEmail` (casando por `message_id`). Some da base automaticamente.
- (Opcional) pixel de abertura para taxa de abertura.

## 2.3 Aquecimento
- Rampa gradual de volume nas primeiras semanas do subdomínio novo.

## 2.4 Entregáveis da Fase 2
- Gateway `ses`, webhook SNS, tratamento de bounce/reclamação, doc de aquecimento.

---

# TRILHO 1:1 — "Enviar por e-mail" no lead (irmão da campanha)

> Cenário: no meio da conversa, o lead / a agência / a operadora pede **"me manda por
> e-mail o que combinamos"**. Em vez de o vendedor redigir na mão, o CRM **captura o que
> já está estruturado** e monta o e-mail sozinho. É um **fast-follow da Fase 1** e **não
> depende da AWS** (pode até sair pelo transacional que já existe — Zoho — por ser
> e-mail pedido pelo cliente).

## Dois tipos, um só motor

Não é "um e-mail que serve pros dois". É **um mesmo motor de template + variáveis**
alimentando **dois caminhos de envio**:

| | **1:1 (pedido pelo cliente)** | **Massa (campanha)** |
|---|---|---|
| Gatilho | botão no lead, no meio da conversa | agendada, para um segmento |
| Conteúdo | cotação + valores acordados + **resumo da conversa** + link de pagamento | oferta genérica com variáveis |
| Remetente | transacional (ótima entrega) | SES / `news.` |
| Resumo da conversa | **sim** | **nunca** |

```text
            ┌─ preenche c/ dados do lead → envia p/ 1  (transacional)    ← botão no lead
Template ───┤
 (variáveis)└─ preenche por destinatário → dispara p/ segmento (SES/news) ← campanha
```

## O que o botão captura automaticamente

Botão **"Enviar por e-mail"** nas Ações rápidas do lead (ao lado de "Enviar proposta +
sinal"). Ao clicar, compõe puxando o que já existe na tela:

- **última Cotação** → quarto, datas, diária, total, validade;
- **lead** → nome, pessoas/quartos, `valor_estimado` (valores acordados);
- **link de pagamento** (Safrapay) → botão "Pagar o sinal";
- **resumo da conversa** → últimas mensagens do WhatsApp / eventos da Linha do tempo →
  bloco "O que combinamos".

O operador **revisa/edita**, envia, e fica na **trilha** ("gvivan enviou e-mail da
proposta"). Como e-mail aceita **HTML**, nasce bonito (logo, cartão da estadia, botão
dourado) no design Lampião — ao contrário do WhatsApp, que é texto puro.

## Reaproveita o que já existe

- `services.montar_proposta_sinal(op, cobranca, link)` já monta a copy **texto** do
  WhatsApp. A irmã **`montar_proposta_email(op, cobranca, link)`** devolve **HTML +
  variáveis** com os mesmos dados.
- Motor de variáveis = o mesmo das Respostas Rápidas do WhatsApp
  (`{primeiro_nome}`, `{quarto}`, `{checkin}`, `{total}`…).

## Template com blocos opcionais (o elo com o massa)

Um único `TemplateEmail` (assunto + corpo HTML + variáveis) com **blocos que ligam/
desligam**:

- blocos **1:1** (resumo da conversa, link de pagamento pessoal) → **ligados** no envio
  pontual, **desligados** quando o template vira campanha;
- o resto (cartão da estadia, oferta, rodapé) é comum aos dois.

Assim o vendedor pode **salvar o e-mail que acabou de montar como template** e ele já
serve de **base de campanha** depois — sem retrabalho.

---

# FASE 3 — Refinamentos (depois)

- Editor de e-mail com blocos/templates salvos (reaproveitar Respostas Rápidas).
- Variáveis no corpo (`{primeiro_nome}`, `{cidade}`…) — mesmo motor do WhatsApp.
- A/B de assunto.
- Automações simples (gatilho por evento: pós-checkout → NPS/reengajamento) — amarra
  com CRM do Hóspede.
- Relatório de campanha no módulo Relatórios (mês/ano).

---

## Ordem recomendada e porquê

1. **Fase 1 primeiro** (não precisa de AWS): entrega o produto testável e trava o
   contrato dos models/telas.
2. **Fase 0 em paralelo** (tem prazo de DNS + saída do sandbox — começa cedo).
3. **Fase 2** quando 0 e 1 estiverem prontas: liga o SES real.
4. **Fase 3** conforme a operação pedir.

## Riscos e cuidados

- **Reputação**: sem SPF/DKIM/DMARC = spam. Subdomínio dedicado isola o transacional.
- **LGPD**: opt-in registrado + descadastro de 1 clique respeitado. Guardar a base do
  consentimento (a "lista de espera" da LP conta como opt-in leve — adicionar checkbox
  de consentimento explícito no form da LP).
- **Sandbox do SES**: enquanto não sair, só e-mails verificados recebem — não confundir
  com "não está funcionando".
- **Bounce alto derruba a conta**: o webhook que limpa a lista é obrigatório antes de
  volume real.

## Resumo

Campanha montada e gerida **no CRM** (caminho A), enviada pelo **Amazon SES** via
subdomínio **`news.pousadavotesta.com.br`**, com segmentação puxada do funil, descadastro
LGPD e limpeza automática por bounce/reclamação. Construímos a **Fase 1 (scaffold,
gateway simulado)** sem depender da AWS; a **Fase 0 (DNS/SES)** corre em paralelo; a
**Fase 2** liga o envio real.

# CRM + WhatsApp — conversa dentro do funil (+ PWA)

> Plano de implementação. Traz a conversa do WhatsApp para **dentro do card do lead**
> (histórico, respostas rápidas, responder sem sair do CRM) e, como anexo, transforma o
> CRM num **aplicativo instalável no celular (PWA)**. Sem abreviaturas.
> Esboço visual: `mockup_crm_whatsapp.html`.

## 0. A lógica (o que muda na prática)

**Regra de ouro:** um número está **OU no aplicativo do WhatsApp OU na API — nunca nos
dois.** O número que a pousada conectar ao CRM **sai do aplicativo** e passa a viver "na
nuvem". A partir daí:

- **Tudo daquele número acontece no CRM** — o cliente manda, aparece no funil; você
  responde, sai do CRM. Não existe "conversa no celular que depois sincroniza": o número
  não está mais no celular, a conversa **é** o CRM.
- **Não precisa do aplicativo do WhatsApp** para atender — responde-se do computador ou
  do próprio CRM no navegador do celular (e, com o PWA, do ícone na tela inicial).
- **O que NÃO entra no CRM:** conversas de **outro** número (WhatsApp pessoal, app
  antigo) — o aplicativo comum não tem API; não há como puxar esse histórico.
- **Ganho grande para a pousada:** hoje um celular = um atendente por vez. Com o número
  no CRM, **toda a equipe responde junto**, cada lead com dono, e nada se perde.

## 1. O caminho oficial: WhatsApp Business Platform (Cloud API)

- **Receber (inbound):** a Meta dispara um **webhook** para o nosso servidor a cada
  mensagem; o sistema grava, acha o lead pelo telefone e mostra no card do funil.
- **Responder (outbound):** o sistema chama a API. Duas regras:
  1. **Janela de 24 horas:** mensagem livre só dentro de 24h desde a última do cliente.
  2. **Fora das 24h:** só **modelos de mensagem pré-aprovados** (templates), cobrados por
     conversa.
- **Custo:** a Meta cobra **por conversa** (janela de 24h), por categoria
  (atendimento/utilidade/marketing). Atendimento tem cota gratuita.
- **⛔ Não usar** bibliotecas não-oficiais (automatizam o WhatsApp Web) — violam os termos
  e arriscam banir o número.

## 2. Arquitetura (mesmo padrão de gateway plugável do projeto)

App novo `apps/whatsapp` (ou submódulo do Comercial — **item dentro do Comercial**, como
o Impulsionamento), com **gateway plugável**:

> `WHATSAPP_GATEWAY`: **`simulado`** (padrão, sem rede — dev/testes/MVP) /
> **`cloud`** (Meta Cloud API) / **`bsp`** (via provedor: Twilio/360dialog/Zenvia).

**Models:**
- `ConversaWhatsApp` — uma por lead/telefone (liga a `nucleo.Pessoa` / `Oportunidade`).
  Guarda a janela de 24h (última mensagem do cliente) e o não-lido.
- `MensagemWhatsApp` — cada mensagem: direção (entrada/saída), texto, status
  (enviada/entregue/lida), id externo (idempotência), autor (vendedor), horário.
- `RespostaRapida` — biblioteca de respostas prontas (equipe edita).
- `TemplateWhatsApp` — modelos aprovados na Meta (para fora das 24h).

**Serviços (interface pública):** `receber_mensagem(payload)` (idempotente, casa o lead
pelo telefone, cria o lead se novo), `enviar_mensagem(conversa, texto/template)`
(best-effort, respeita a janela de 24h), `marcar_lida`.

**Webhook** público (`/whatsapp/webhook/`, csrf-exempt, verify token) — recebe eventos da
Meta → grava a mensagem → **notifica o vendedor dono** → aplica a regra "quem responde
primeiro assume o lead".

**Interface (no card/detalhe do lead do funil):** painel de chat (histórico) + campo de
resposta + **respostas rápidas** (chips) + seletor de **template** (fora das 24h) +
indicador da janela de 24h. Reaproveita **atribuição, SLA e o botão «Ganhar → reserva»**
que já existem. Ver `mockup_crm_whatsapp.html`.

## 2.1 Respostas Rápidas (independente da API — dá para fazer já)

Os **textos pré-salvos** (respostas rápidas) **não dependem da API do WhatsApp** — são um
recurso standalone que já entrega valor hoje e vira a base para quando o chat entrar.

- Model **`RespostaRapida`**: título (rótulo do chip) + texto + atalho opcional + ordem.
  A equipe cria/edita em **Comercial → Respostas rápidas**.
- **Variáveis** que se preenchem sozinhas com os dados do lead: `{nome}`, `{checkin}`,
  `{checkout}`, `{noites}`, `{valor}`, `{vagas}` — "Confirmar disponibilidade" já sai com
  o nome e as datas reais.
- **Hoje (sem WhatsApp):** aparecem como **chips com "Copiar"** no detalhe do lead — copia
  e cola no WhatsApp do celular (1 toque em vez de digitar).
- **Depois (com o chat):** os mesmos chips passam a **inserir o texto direto** no campo de
  resposta do funil — zero mudança de cadastro.
- **Por que já:** padroniza o discurso do time, acelera a resposta (fator nº 1 de
  conversão) e deixa a base pronta para a integração. É barato (um model + uma tela).

## 2.2 Enviar proposta + sinal (Safrapay) — template p/ implementar no futuro

Ação no lead que **gera o link de pagamento do sinal** e o **envia no WhatsApp** com a
proposta. O hóspede paga o adiantamento e a data trava. **Ainda não construído** — este é
o template de implementação (a base já existe no módulo Pagamentos).

### O que já existe (reaproveitar)
- `pagamentos.services.criar_cobranca(operador, *, valor, metodo, descricao,
  finalidade=Cobranca.Finalidade.SINAL, pagador=…, reserva_id=…)` — cria a cobrança e
  chama o gateway (Safrapay/simulado).
- **Link público de pagamento:** rota `pagamentos:pagar` → `/crm/pagamentos/pagar/<token>/`
  (sem login; Pix copia-e-cola + cartão). `Cobranca.token` (UUID) é o identificador.
- `pagamentos.services.confirmar_pagamento` (idempotente) → sinal pago dispara
  `reservas.confirmar_reserva` (quando há reserva vinculada).
- `Oportunidade.cobranca_sinal_id` (campo já existe) para ligar o lead à cobrança.

### Fluxo a construir
1. **Ação "Enviar proposta + sinal"** no rail do lead (botão dourado do mock-up).
2. **Serviço** `gerar_link_sinal(oportunidade, usuario, valor=None, metodo="pix")`:
   - Degrada se `modulo_ativo(PAGAMENTOS)` for falso (mensagem clara).
   - `valor = valor or 30% de op.valor_estimado`.
   - `cobranca = criar_cobranca(usuario, valor=valor, metodo=metodo,
     descricao=f"Sinal — {op.titulo}", finalidade=SINAL, pagador=op.pessoa, reserva_id=<ver B>)`.
   - Grava `op.cobranca_sinal_id = cobranca.id`; registra atividade ("Proposta + sinal enviada").
   - Monta a URL pública: `request.build_absolute_uri(reverse('pagamentos:pagar', args=[cobranca.token]))`.
   - **Envia no WhatsApp** via `enviar_mensagem_whatsapp` com a proposta + o link (ou insere
     no campo de resposta para o vendedor revisar antes).
3. **Resposta rápida "Enviar proposta + pagamento"** passa a incluir a variável `{link_sinal}`
   resolvida por este serviço.

### A decisão do "travar a data" (duas variantes)
- **(A) MVP — link avulso:** cobrança de sinal **sem reserva** (`reserva_id=None`). O
  hóspede paga; o vendedor confirma com **"Ganhar → criar reserva"**. Simples, entrega já.
- **(B) Completa — trava sozinha:** criar uma **pré-reserva** (retenção, sem marcar ganho)
  para as datas/tipo, vincular a cobrança a ela (`reserva_id`), e no pagamento
  `confirmar_pagamento → confirmar_reserva` fecha e marca o lead como ganho. Precisa das
  datas + tipo de quarto no lead (usa o mesmo form da conversão). É a experiência ideal.

### Pré-requisitos operacionais
- **Safrapay ligado** (`docs/Implementar_Safrapay.md`): Token + `.env` + webhook público.
  Até lá, o gateway **simulado** já permite testar o fluxo ponta-a-ponta.

### Entregáveis e testes (quando construir)
- `gerar_link_sinal` (best-effort, degrada sem Pagamentos) + view/botão no rail + variável
  `{link_sinal}` nas respostas rápidas.
- Testes: cria cobrança de sinal ligada ao lead; monta o link; envia no WhatsApp (simulado);
  degrada com Pagamentos inativo; (variante B) pagamento confirma a reserva.

## 3. Fases

**Fase 1 — MVP (gateway `simulado`, sem número real):**
- Models + painel de chat no card do lead + respostas rápidas + serviços.
- Um "modo simulado" que injeta mensagens de teste para ver a conversa caindo no funil.
- **Objetivo:** validar a experiência (conversa no funil, atribuição, proposta) **antes**
  de decidir o número real.

**Fase 2 — Ligar de verdade (Cloud API):**
- Número dedicado + verificação do negócio na Meta + 1–2 templates aprovados.
- Webhook público + envio real + status de entrega/leitura.
- Notificação em tempo real ao vendedor (ver PWA §5).

**Fase 3 — Refino:**
- Auto-resposta imediata ("recebi, já te respondo") fora do horário / enquanto sem dono.
- Métricas de **tempo de resposta** e SLA por vendedor; multi-atendente; relatórios.

## 4. Decisões operacionais (não é código)

- **Qual número vira o "número da pousada no CRM":**
  - **(A) Número novo dedicado** *(recomendado)* — o WhatsApp atual continua no celular
    normalmente; o novo número é o oficial do CRM. Zero risco.
  - **(B) Migrar o número atual** — concentra tudo, mas esse número **sai do app** (só
    pelo sistema).
- **Verificação do negócio** na Meta (pode levar dias).
- **Templates** aprovados para reengajar fora das 24h.
- **Direto pela Meta** (grátis da Meta, paga por conversa) **ou via BSP** (Twilio/360dialog
  — onboarding mais rápido, pequena margem por mensagem, bom para começar).

## 5. Anexo — CRM como aplicativo no celular (PWA)

Transformar o próprio CRM num **aplicativo instalável** (Progressive Web App) — **não é
outro app para manter**, é o mesmo sistema "vestido" de app. Esboço no
`mockup_crm_whatsapp.html`.

**O que entrega:**
- **Instala na tela inicial** (Android e iPhone), abre em tela cheia, **sem loja de apps**.
- **Notificação push** quando entra **lead quente** ou **mensagem no WhatsApp** — o
  vendedor responde na hora, de qualquer lugar. (É o par perfeito da integração WhatsApp.)
- **Funciona offline** o essencial (abre e mostra a última tela mesmo sem sinal).

**Como se faz (técnico, enxuto):**
- **`manifest.json`** (nome, ícones, cor tema Lampião, `display: standalone`) — torna o
  site instalável.
- **Service Worker** — cacheia o "app-shell" (offline) e recebe **push**.
- **Web Push** (VAPID) — o servidor dispara a notificação; no iPhone exige o app já
  "instalado" na tela inicial (suporte a push em PWA a partir do iOS 16.4).
- Botão **"Instalar app"** no CRM (evento `beforeinstallprompt` no Android; instruções
  "Adicionar à Tela de Início" no iPhone).

**Fases do PWA:** (1) instalável + offline básico; (2) push de lead quente / WhatsApp;
(3) ícones/atalhos e badge de não-lidos.

## 6. Entregáveis e testes
- Models + serviços (`receber`/`enviar`, idempotentes, best-effort) com gateway `simulado`.
- Webhook (verify token) + painel de chat no lead + respostas rápidas + templates.
- `manifest.json` + service worker + push (VAPID).
- Testes: recepção idempotente, atribuição pelo telefone, janela de 24h (bloqueia livre
  fora dela), envio simulado, webhook, e o PWA instalável (manifest válido).

## 7. Resumo
Um número passa a **morar no funil**: toda a conversa do WhatsApp vira histórico do lead,
a equipe responde junto (sem celular preso a uma pessoa), com respostas rápidas e proposta
com pagamento em 1 toque. O **PWA** coloca esse funil no bolso, com **push** de lead
quente. Começamos pelo **MVP simulado** (ver a conversa no funil antes de ligar o número),
no mesmo padrão de gateway plugável dos demais módulos.

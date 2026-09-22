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

---

# Anexo A — Custos da Meta, janela de 24h e templates

> Consolidado das definições de negócio (set/2026) para não perder o raciocínio de custo.
> Preço unitário citado é **aproximado** — confirmar o rate card oficial da Meta (Brasil,
> marketing ≈ US$ 0,05–0,0625/mensagem ≈ **R$ 0,40**).

## A.1 O que é um template
Mensagem **pré-aprovada pela Meta**, usada para **iniciar** conversa (janela fechada) ou
para qualquer mensagem que **a pousada** dispara primeiro. Anti-spam: não se manda texto
livre "frio".
- **Corpo fixo com variáveis:** `Olá, {{1}}! Você se inscreveu…` (o `{{1}}` vira o nome).
- Opcionais: cabeçalho (texto/imagem), rodapé e **botões** ("Sim, quero" / "Sair").
- **Categoria** define o preço: **Marketing** (oferta/novidade — o nosso caso), **Utility**
  (confirmação/lembrete — mais barato), **Authentication** (código).
- Submete → Meta revisa (minutos a ~1 dia) → aprovado, **reutiliza infinitas vezes**.

## A.2 Como a Meta cobra (modelo por mensagem, desde jul/2025)
| Categoria | O que é | Custo |
|---|---|---|
| **Marketing** | Novidade, oferta, convite (disparo aos fundadores, Natal) | **Pago** (~R$ 0,40) |
| **Utility** | Confirmação de reserva, lembrete, recibo | Pago (mais barato) |
| **Authentication** | Código de verificação | Pago |
| **Service** | Pousada **respondendo** o cliente, texto livre, dentro de 24h | **Grátis e ilimitado** |

Receber mensagem e verificar o número = grátis. Na prática, **paga-se só o marketing**.
**Regra de ouro:** cobra-se pelo nº de **disparos de template**, não pelo nº de mensagens
trocadas. Conversar muito não custa; **reiniciar** do zero é que custa.

## A.3 A janela de 24h (quem abre e quem renova)
- **Só o CLIENTE abre e renova** a janela: cada mensagem dele inicia/reinicia 24h.
- **Respostas da pousada NÃO abrem nem esticam** a janela — só a usam.
- **O template disparado também NÃO abre** a janela; ele só "toca a campainha". A janela
  abre quando o cliente **responde** (ex.: toca o botão "Sim").

Linha do tempo:
| Quando | Evento | Janela | Custo |
|---|---|---|---|
| Seg 10:00 | Pousada dispara o template (boas-vindas + botão) | fechada | **pago** |
| Seg 10:05 | Cliente toca "Sim" | **abre** até Ter 10:05 | grátis |
| Seg 15:00 | Pousada responde (texto livre) | segue até Ter 10:05 (não esticou) | grátis |
| Seg 20:00 | Cliente responde de novo | **renova** até Ter 20:00 | grátis |
| Qua 09:00 | Silêncio desde Ter 20:00 → janela **fechou** | fechada | — |
| Qua 09:00 | Para reiniciar, pousada manda template | — | **pago** |

## A.4 Custo aplicado ao nosso fluxo (captação → negociação)
Fluxo: lead entra pela LP → dispara boas-vindas com **botão Sim** → cliente responde →
conversa de dias até fechar a reserva.
- **Lead que engaja:** só o disparo inicial = **~R$ 0,40**. Toda a negociação = R$ 0.
- **Lead que esfria e é reativado:** +~R$ 0,40 por reativação (novo template).
- **Lead que nunca responde:** pagou só o template inicial (~R$ 0,40).

Estimativa mensal (fase "montando a base", ~R$ 0,40/template):
| Cenário | Templates pagos | Custo/mês |
|---|---:|---:|
| 24 fundadores de hoje + reativações leves | ~40 | ~R$ 16 |
| 100 leads/mês + ~30 reativações | ~130 | ~R$ 52 |
| 300 leads/mês + ~90 reativações | ~390 | ~R$ 156 |

## A.5 Otimizações de custo (embutir no fluxo)
1. **Sempre com botão** ("Sim, quero" / "Ver valores") → força a resposta e abre a janela
   grátis já no 1º toque.
2. **Não reiniciar à toa:** agrupar follow-ups num único template bem pensado.
3. **Reativação como Utility** quando couber (ex.: "sua condição de fundador está
   reservada até…") — mais barata que marketing.

## A.6 Template inicial (para aprovação)
> **Nome:** `boas_vindas_fundador` · **Categoria:** Marketing · **Idioma:** pt-BR
>
> Olá, {{1}}! Aqui é o *Vô Testa* 🎩 Que bom ter você na lista de *fundadores* da nossa
> pousada às margens do Lago, em Itá. Você vai saber de tudo primeiro — valores, pacotes e
> a condição de quem chegou antes de as portas abrirem. Posso te mandar as novidades em
> primeira mão por aqui?
>
> *(botões: "Quero sim" · "Sair da lista")*

## A.7 Voz vs. WhatsApp no mesmo número
A **linha telefônica** (operadora) e a **Cloud API** são independentes, mesmo sendo o
mesmo número:
- **Ligação de voz** → pela linha da operadora (telefonia normal). A API não interfere.
- **Mensagens WhatsApp** → pela Cloud API (internet). Ela não faz/recebe voz do WhatsApp.
- Única regra: **não instalar esse número no app do WhatsApp** (conflita com a API).

---

# Anexo B — Voz no CRM: discador, gravação, transcrição e BI

> Objetivo: ligar para o lead de dentro do CRM, gravar, transcrever e transformar as
> conversas em inteligência (melhorar o pitch dos vendedores e entender o cliente).
> **Princípio:** não construir telefonia do zero — **orquestrar** provedores por API.

## B.1 Consentimento / LGPD (aviso de gravação)
- **Pode gravar** (a pousada é parte da conversa — legal no Brasil). **Avisar no início** é
  a boa prática e cumpre a transparência da LGPD.
- Informar **finalidade** ("gravada para qualidade e melhoria do atendimento"), guardar
  com **acesso restrito**, definir **retenção** (sugestão: 12 meses) e permitir
  **acesso/exclusão** a pedido. Não reutilizar para outra finalidade.
- **Implementação:** áudio automático no começo da ligação ("Esta ligação será
  gravada…") ou script fixo do vendedor; o CRM **registra o consentimento** junto da
  gravação. Sem aceite → segue **sem gravar**.

## B.2 Arquitetura (4 camadas plugadas ao CRM)
```
[CRM Django] --clique p/ ligar--> [Provedor de Voz/VoIP c/ API]
     ^                                   |
     |  webhook (áudio + status)         v
     |<-------------------------  grava a ligação (mp3)
     |
     |--envia áudio--> [Transcrição/STT] --texto--> salva no lead
     |                                                   |
     |--envia texto--> [IA (Claude)] --resumo/objeções/score--> ficha
     |                                                   |
     |----------- campos estruturados ----------> [Painel/BI]
```

1. **Ligar (click-to-call):** botão no lead → API do provedor. Opções: **softphone
   WebRTC** no navegador (vendedor fala pelo CRM, sem telefone físico — melhor UX) ou
   **dial pareado** (liga no celular do vendedor e conecta o cliente).
   - A linha VoIP da operadora sozinha não dá click-to-call/gravação; conecta-se via um
     **CPaaS** (Twilio, Telnyx, Plivo, ou BR Zenvia/Total Voice) que fornece número/SIP
     programável. Alternativa avançada: **Asterisk/FreePBX** self-hosted no SIP trunk da
     operadora (mais barato em escala, exige manter servidor).
2. **Gravar:** provedor grava no servidor e, ao fim, manda **webhook** com o link do
   áudio. O CRM salva como **atividade imutável** no lead (padrão de auditoria).
3. **Transcrever (áudio → texto):** enviar a gravação ao **STT** — Whisper (OpenAI ou
   local) / Deepgram / AssemblyAI (todos bons em pt-BR). Guardar o transcript no lead.
4. **Analisar + BI:**
   - **Por ligação:** IA (**Claude**) lê o transcript e extrai **estruturado**: resumo,
     objeções, o que funcionou, próximos passos, aderência ao script, nota. Fica na ficha.
   - **BI:** como a IA devolve campos padronizados, agregam-se objeções comuns, motivos de
     perda, temas citados, sentimento por vendedor, conversão por abordagem. Começa nos
     gráficos atuais (Chart.js); se crescer, **Metabase** direto no Postgres.

## B.3 Como pluga no CRM
Novo módulo `apps/telefonia` (contratável, no padrão do projeto): services públicos
(`iniciar_ligacao`, `registrar_gravacao`, `transcrever`, `analisar`); cada ligação vira
`AtividadeComercial` no funil; gravação/transcrição **append-only**; tudo na auditoria;
zero acoplamento com os outros módulos.

## B.4 Plano faseado
1. **Fase 1 — Discar + gravar:** click-to-call + gravação salva no lead.
2. **Fase 2 — Transcrição automática** ao encerrar.
3. **Fase 3 — Análise por IA** (resumo/objeções/score) na ficha.
4. **Fase 4 — BI agregado** (objeções, motivos, sentimento, ranking de pitch).

## B.5 Custo aproximado (volume de pousada = baixo)
- **Voz:** ~R$ 0,10–0,30/min (CPaaS BR).
- **Transcrição:** ~US$ 0,006/min (Whisper) — centavos por ligação.
- **Análise IA:** poucos centavos por ligação.
- Ex.: 100 ligações de 5 min/mês ≈ **R$ 50–150 de voz + ~R$ 20 STT/IA**.

## B.6 Decisões em aberto
1. **Provedor de voz:** CPaaS pronto (**Twilio** = mais fácil em Django) vs. **Asterisk +
   SIP da operadora** (mais barato/complexo). Para estrear rápido: **Twilio**.
2. **Softphone no navegador** ou dial para o celular do vendedor?
3. **STT:** Whisper (barato/flexível) vs. serviço gerenciado (Deepgram/AssemblyAI).
4. **Retenção** das gravações (sugestão 12 meses) + política LGPD.

**Recomendação para estrear rápido e barato:** Twilio (voz + gravação + softphone WebRTC)
→ Whisper (transcrição) → Claude (análise) → dashboard atual (BI). Faseado, começando por
"discar + gravar".

> **⚠️ Atualização (14/09/2026) — plano refinado para a equipe de vendas remota.** Com a
> equipe em **Concórdia** (a central UnniTI é da pousada, em **Itá**) e a **Vupt já
> contratada (R$ 59,90/mês)**, a decisão mudou: **manter a Vupt como operadora** e usar
> **Asterisk** (PBX open-source numa VM, **custo zero de licença**, controlado por Python
> via **ARI**) + **SIP.js** (softphone no navegador) — em vez do Twilio (celular BR caro,
> Vupt sem uso). O plano executável (arquitetura, papéis, custos e **passo a passo**) está
> em **`docs/Implementar_Telefonia_Vendas.md`**. As fases Whisper/Claude/BI deste anexo
> seguem valendo.

---

# Anexo C — Estado da implementação (Trilha B) + go-live

> Atualizado em 10/09/2026. Código **implementado, testado e no ar** (modo `simulado`).
> Vira `cloud` só preenchendo o `.env` de produção com as credenciais do número.

## C.1 O que já está pronto no CRM (commits na `main`)
- **GatewayCloud real** (`apps/comercial/whatsapp_gateways.py`): envia **texto** (janela
  24h) e **template** via Graph API (urllib, sem dependência nova); `normalizar_telefone`
  em E.164 (país 55).
- **Webhook público** `POST/GET /whatsapp/webhook/` (`views_whatsapp.py`): verify-token no
  GET; no POST processa **mensagens + status + opt-out**, idempotente por `wamid`, e
  **valida a assinatura `X-Hub-Signature-256`** quando `WHATSAPP_APP_SECRET` está setado.
- **Trava de janela de 24h** no envio livre (fora do simulado); status `failed` **nunca
  reverte**.
- **Disparo em lote** (`services.disparar_campanha_whatsapp` + comando
  `manage.py enviar_campanha_whatsapp`) com throttle e opt-in.
- **Consentimento por canal:** `Pessoa.aceita_whatsapp` (migração 0034, com backfill dos
  leads já opt-in). O "sair" no WhatsApp desliga só o WhatsApp.
- **Resiliência:** mensagem recebida anexa à oportunidade mais recente (não exige ABERTA)
  — reply de quem já reservou não se perde.

## C.2 Variáveis de ambiente (produção)
| Var | O que é |
|---|---|
| `WHATSAPP_GATEWAY=cloud` | liga o provedor real (padrão `simulado`) |
| `WHATSAPP_CLOUD_TOKEN` | token permanente (System User) da Meta |
| `WHATSAPP_CLOUD_PHONE_ID` | Phone Number ID do número na WABA |
| `WHATSAPP_VERIFY_TOKEN` | segredo do handshake do webhook (você escolhe) |
| `WHATSAPP_APP_SECRET` | App Secret da Meta — valida a assinatura do webhook |
| `WHATSAPP_WABA_ID` | (futuro) gestão de templates |
| `WHATSAPP_API_VERSION` | default `v21.0` |

## C.3 Checklist de go-live (amanhã, com o número)
**Lado Meta (portfólio "Pousada Vô Testa"):**
- [ ] Registrar o número novo na **WABA do portfólio Pousada Vô Testa** (via
      `business.facebook.com/settings` → Contas → Contas do WhatsApp → Adicionar) —
      **não** instalar o número no app comum do WhatsApp.
- [ ] Aprovar o template **`boas_vindas_fundador`** (categoria Marketing, pt-BR).
- [ ] Gerar **token permanente** + anotar **Phone Number ID** e **App Secret**.
- [ ] Configurar o webhook: URL `https://www.pousadavotesta.com.br/whatsapp/webhook/`,
      **Verify Token** = o mesmo do `.env`, assinar o campo `messages`.

**Lado CRM:**
- [ ] Preencher o `.env` de produção (tabela C.2) e deployar.
- [ ] Teste: `manage.py enviar_campanha_whatsapp --template boas_vindas_fundador
      --slug fundador --limite 1` → depois sem `--limite`.

## C.4 Ainda NÃO feito (fast-follow futuros)
- Painel de campanha na UI (hoje o disparo é por comando/serviço).
- Rastrear `delivered`/`read` como estados próprios (hoje viram "enviada").
- Gestão de templates pela API (WABA_ID).
- Verificação de negócio na Meta: **só quando for escalar** (aumentar limites); fazer no
  portfólio **Pousada Vô Testa** por *Autorizações e verificações*.

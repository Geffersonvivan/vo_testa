# Gestor de Impulsionamento (Anúncios) — Comercial

> **Estado (implementado):** Fases **A, B e C** construídas no Comercial
> (`/crm/comercial/impulsionamento/`), com `MIDIA_GATEWAY=simulado` por padrão. Para
> ligar de verdade: **Meta** (Conversions API + Insights) precisa de `META_CAPI_TOKEN` +
> `META_PIXEL_ID` (+ permissão `ads_read` para a Fase C); **Google** é stub até sair o
> developer token. Modelos: `Campanha`, `GastoDiario`, `ConversaoEnviada`. Comandos:
> `enviar_conversoes_pendentes`, `sincronizar_gastos_midia`.

> Plano de implementação em **3 fases** (A, B, C). Fecha o ciclo do tráfego pago:
> saber **de qual anúncio veio cada lead**, **devolver a venda real** às plataformas
> (para o algoritmo otimizar por quem paga) e **medir custo por lead/reserva e retorno**.
> Sem abreviaturas: toda sigla vem escrita por extenso na primeira vez.
> Documentos irmãos: `Gestor_LPs.md`, `Plano_Marketing_Inauguracao.md`.

## 0. Glossário

- **Impulsionamento / Tráfego pago:** anúncios pagos (Meta Ads = Instagram/Facebook,
  Google Ads, etc.) que levam pessoas à Página de Captação.
- **Parâmetros de origem (UTM):** pedaços na URL (`utm_source`, `utm_medium`,
  `utm_campaign`, `utm_content`, `utm_term`) que dizem de qual campanha/anúncio veio o clique.
- **Identificador de clique:** código único do clique — `fbclid` (Meta) e `gclid`
  (Google) — que permite casar a venda futura com o anúncio exato.
- **Conversão:** ação de valor (preencher a lista = *Lead*; reserva paga = *Compra*).
- **Conversão Offline / Interface de Conversões (Conversions API / Offline Import):**
  devolver ao Meta/Google um evento que aconteceu **fora do navegador** (a reserva paga,
  dias depois, no CRM), com valor em reais.
- **Custo por Lead (CPL):** gasto ÷ leads. **Retorno sobre Investimento em Anúncio
  (ROAS):** receita gerada ÷ gasto.
- **Gateway plugável:** padrão já usado no projeto (FNRH, Pagamentos, Fiscal) — um
  provedor `simulado` por padrão e provedores reais (`meta`, `google`) quando configurados.

## 1. O ciclo completo

```
Criativo → Anúncio (Meta/Google) → Clique(+utm+fbclid/gclid) → Página de Captação
   → Lead no funil (etiquetado com campanha) → Reserva paga (ganho)
        ↑                                              │
        └─────────  devolve a conversão + R$  ─────────┘   (Fase B)
   painel: gasto × leads × reservas × custo por lead × retorno   (Fase A/C)
```

**Hoje temos:** Página de Captação com Pixel do Meta + tag do Google; lead etiquetado
com a Página (`pagina_captacao`); funil com dono/score/conversão em reserva.
**Falta:** origem fina (UTM + identificador de clique), devolver a venda às plataformas,
registrar gasto e o painel.

## 2. Arquitetura (segue o padrão do projeto)

**É um item DENTRO do Comercial — não é um módulo contratável à parte.** Fica na barra
lateral como sub-link **"Impulsionamento"**, ao lado de "LP Páginas", "Caçador" e
"Instagram"; rotas sob `/crm/comercial/impulsionamento/…`; mesma permissão
`@requer_modulo(Modulo.COMERCIAL)` (quem tem o Comercial vê o gestor). Pertence ao
Comercial porque depende do **funil** (`Oportunidade`) e das **Páginas de Captação**
(`PaginaCaptacao`), que já são do Comercial, e fecha o ciclo Anúncio → LP → Lead → Venda
todo dentro dele. O código pode morar no próprio `apps/comercial` (como as LPs) ou num
`apps/midia` que funciona só como **motor** exposto sob o menu do Comercial — de qualquer
forma, **para o usuário é um item do Comercial**, com o mesmo controle de acesso.

**Gateway plugável** `MIDIA_GATEWAY` no settings: `simulado` (padrão, gasto manual) /
`meta` / `google` — mesmo molde de FNRH/Pagamentos/Fiscal.

Models (núcleo do gestor):
- **`Campanha`** — uma campanha de anúncio; liga a uma `PaginaCaptacao` (destino) e a um
  provedor (meta/google/outra). Guarda nome, objetivo, verba e o identificador externo
  (id da campanha na plataforma, quando houver).
- **`GastoDiario`** — gasto por campanha por dia (digitado ou sincronizado). Base do
  custo por lead.
- **`ConversaoEnviada`** — trilha do que foi devolvido às plataformas (idempotência).
- Reaproveita **`Oportunidade`** (o lead) e a atribuição já existente.

Serviços (interface pública): `registrar_gasto()`, `metricas_campanha()`,
`enviar_conversao(evento, oportunidade)`, `sincronizar_gastos()`.

---

# FASE A — Atribuição fina + gasto manual + painel

**Objetivo:** saber de qual campanha/anúncio veio cada lead e medir custo por lead e por
reserva — **sem depender de aprovação de nenhuma plataforma** (a atribuição vive no nosso
banco). É o "gerenciador de impulsionamento" mínimo viável.

### A.1 Capturar origem no lead
- A Página de Captação passa a **ler da URL** os parâmetros `utm_source`, `utm_medium`,
  `utm_campaign`, `utm_content`, `utm_term` e os identificadores `fbclid` / `gclid`.
- Guardados em **campos novos** na `Oportunidade` (ou numa tabela `OrigemLead` 1:1):
  `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `fbclid`, `gclid`,
  `landing_url`, `referer`. O `capturar_lead_site` ganha esses parâmetros (a view pública
  os extrai de `request.GET`/formulário oculto).
- **Persistência via campo oculto no formulário** (o navegador perde os parâmetros ao
  postar): a Página lê o `request.GET` no carregamento e injeta `<input type="hidden">`
  com cada valor; e/ou um cookie de primeira parte para sobreviver à navegação.

### A.2 Campanha e gasto
- Cadastro de **`Campanha`** ligada a uma `PaginaCaptacao` + provedor + verba.
- **`GastoDiario`** com lançamento manual (data, valor). Um formulário simples "lancei R$
  X no dia Y na campanha Z".

### A.3 Painel (o gestor)
- Por campanha: **gasto**, **leads** (contando `Oportunidade` pela campanha/UTM),
  **reservas geradas** (leads ganhos), **custo por lead**, **custo por reserva**,
  **retorno** (receita das reservas ÷ gasto).
- Filtro por período (reusa o seletor mês/ano de Relatórios).
- Liga cada campanha à sua Página de Captação (visitas/conversão que já temos).

### A.4 Entregáveis da Fase A
- Migração com os campos de origem na `Oportunidade` (+ `Campanha`, `GastoDiario`).
- `capturar_lead_site(..., origem=...)` gravando UTM/click-ids.
- Página de Captação capturando e repassando os parâmetros (hidden inputs + cookie).
- Telas: lista de campanhas, lançar gasto, painel de métricas.
- Testes: parâmetros gravam no lead; custo por lead calcula certo; reserva conta como
  conversão da campanha.

### A.5 Dependências
**Nenhuma externa.** Só código. Funciona no dia seguinte.

---

# FASE B — Conversões Offline (devolver a venda às plataformas)

**Objetivo:** avisar Meta e Google que **o clique virou hóspede pagante de R$ X**, para o
algoritmo delas otimizar por **quem paga** (não por quem só preenche formulário). É o
maior multiplicador de eficiência da verba enxuta.

### B.1 O que se envia e quando
- **Evento `Lead`** — quando o lead entra na lista (já disparamos no navegador via Pixel;
  aqui passamos a mandar **também pelo servidor**, mais confiável — não sofre bloqueador
  de anúncio nem limitação de navegador).
- **Evento `Compra`/Reserva** — quando a `Oportunidade` vira **ganho** (reserva paga),
  com o **valor em reais**. É o elo que hoje falta.
- Disparo a partir dos serviços que já existem: no `capturar_lead_site` (Lead) e no
  `confirmar_reserva`/conversão do funil (Compra), de forma **best-effort** (nunca trava
  a operação) e **idempotente** (registra em `ConversaoEnviada`).

### B.2 Como casar a venda ao anúncio
- **Meta — Conversions API:** envia o evento com o **`fbclid`** (capturado na Fase A) e/ou
  dados do cliente **com hash (SHA-256)** — e-mail e telefone criptografados, nunca em
  texto puro. Autenticação por **token de usuário de sistema** do Business Manager + ID do
  Pixel/Conjunto de Dados.
- **Google — Offline Conversion Import (Google Ads API):** envia o **`gclid`** + a ação de
  conversão + valor. Autenticação por OAuth2 + **developer token** + ID da conta.

### B.3 Privacidade (obrigatório)
- Dados pessoais enviados **sempre com hash** (padrão exigido pelas plataformas).
- Consentimento do lead (marca de aceite no formulário — encaixar com a LGPD).
- Nada de PII em texto puro em log/trilha; `ConversaoEnviada` guarda só ids e status.

### B.4 Entregáveis da Fase B
- Provedores `meta` e `google` do `MIDIA_GATEWAY` implementando `enviar_conversao`.
- `services.enviar_conversao(evento, oportunidade)` idempotente + best-effort, chamado na
  captura (Lead) e na conversão em reserva (Compra).
- Hash de e-mail/telefone; `ConversaoEnviada` (trilha).
- Comando de reprocessamento (`enviar_conversoes_pendentes`) para falhas transitórias.
- Botão "reenviar conversão" no detalhe do lead (como o "Reenviar" da FNRH).
- Testes com provedor **simulado** (não bate na rede): idempotência, hash, best-effort.

### B.5 Dependências e complexidade
- **Meta:** App no Meta for Developers + token de usuário de sistema (Business Manager);
  a Conversions API em si **não exige revisão** para eventos próprios do Pixel. Médio.
- **Google:** **developer token** exige aprovação do Google (pode levar dias/semanas).
  Médio-alto. Enquanto não sai, o provedor `simulado`/manual cobre.

---

# FASE C — Puxar gasto e desempenho automaticamente

**Objetivo:** eliminar o lançamento manual de gasto — o painel busca **spend, impressões,
cliques e custo por resultado** direto das plataformas, por campanha.

### C.1 O que se lê
- **Meta — Marketing API (Insights):** gasto, impressões, cliques, custo por resultado,
  por campanha/conjunto/anúncio, por dia.
- **Google — Google Ads API (relatórios):** métricas equivalentes por campanha.
- Grava em `GastoDiario` (mesmo model da Fase A) via `sincronizar_gastos()` — um comando
  de cron diário (padrão dos outros crons do projeto).

### C.2 Entregáveis da Fase C
- `sincronizar_gastos()` nos provedores `meta`/`google`.
- Cron diário `sincronizar_gastos_midia`.
- Painel passa a mostrar gasto real sem digitação; alertas ("campanha sem conversão há
  X dias — cortar").

### C.3 Dependências e complexidade
- **Meta:** permissões `ads_read` exigem **revisão do app** (dias a semanas).
- **Google:** mesma dependência do developer token da Fase B.
- **Alta** no total — por isso é a última. O lançamento manual da Fase A resolve enquanto
  as aprovações não saem.

---

## 3. Credenciais necessárias (resumo)

| Plataforma | Para conversões (Fase B) | Para ler gasto (Fase C) |
|---|---|---|
| **Meta** | App + token de usuário de sistema + ID do Pixel/Conjunto de Dados | + permissão `ads_read` (revisão do app) + ID da conta de anúncios |
| **Google** | OAuth2 + **developer token** (aprovação) + ID da conta + ação de conversão | mesmas credenciais |

Todas ficam em variáveis de ambiente (`.env`), como os outros gateways. Padrão do sistema:
`MIDIA_GATEWAY=simulado` até as credenciais existirem.

## 3.1 Em aberto — Meta (Instagram/Facebook) e Google Ads

> O **código já está pronto** (gateway `meta`/`google`). O que falta é **operacional**:
> gerar as credenciais nas plataformas e colar nas variáveis de ambiente. Passo a passo.

### 🟦 Meta (Instagram/Facebook) — dá para ligar já
Você precisa de dois valores: o **ID do Pixel** e um **token da Conversions API**.

**Passo 1 — Pré-requisitos (uma vez):** conta no **Gerenciador de Negócios**
(business.facebook.com) com a **Página** do Instagram/Facebook da pousada conectada.

**Passo 2 — Pegar o ID do Pixel** → `META_PIXEL_ID`
1. Abrir o **Gerenciador de Eventos** (business.facebook.com/events_manager).
2. Se não existir: **Conectar fonte de dados → Web → Meta Pixel**, criar (nome "Vô Testa").
3. Copiar o **ID do Pixel** (número no topo, ex.: `123456789012345`).
   - É o **mesmo número** do campo "Meta Pixel (ID)" da LP (rastreio no navegador);
     aqui serve também para o envio pelo servidor.

**Passo 3 — Gerar o token da Conversions API** → `META_CAPI_TOKEN`
1. No Gerenciador de Eventos, selecionar o Pixel → **Configurações**.
2. Rolar até **API de Conversões → Gerar token de acesso**. Copiar (é secreto).
   - Alternativa "raiz": Configurações do Negócio → **Usuários do sistema** → criar →
     atribuir o Pixel como ativo → **Gerar token** com `ads_management`.

**Passo 4 — Ligar (variáveis de ambiente):**
```
META_PIXEL_ID=123456789012345
META_CAPI_TOKEN=<o token longo>
MIDIA_GATEWAY=meta
META_CAPI_TEST_CODE=<opcional, só para testar>
```

**Passo 5 — Testar antes de valer:**
1. Gerenciador de Eventos → aba **Testar eventos** → copiar o `test_event_code` →
   colar em `META_CAPI_TEST_CODE`.
2. Fazer uma reserva/lead de teste (LP com `?fbclid=teste`) → ver o evento
   **Lead/Purchase** chegando em tempo real.
3. Funcionou? **Apagar** `META_CAPI_TEST_CODE` (para os eventos contarem de verdade).

**Fase C (gasto automático) no Meta:** o token precisa de permissão **`ads_read`**
(revisão do app) + a campanha com **`id_externo`** = ID da campanha no Gerenciador de
Anúncios. Até lá, lançar o gasto manualmente na tela da campanha.

### 🟥 Google Ads — mais lento (deixar para depois do Meta)
1. Conta do **Google Ads** → **Ferramentas → Central de API** → solicitar
   **developer token** (começa em teste; pedir **acesso básico** — aprovação do Google,
   pode levar dias).
2. Projeto no **Google Cloud** + credenciais **OAuth2** (client id/secret + refresh token).
3. Criar uma **ação de conversão** de importação offline no Google Ads.
4. Preencher `GOOGLE_ADS_CUSTOMER_ID` e `GOOGLE_ADS_CONVERSION_ACTION`.
> Enquanto o token não sai, fica `simulado`/`meta`. Como o motor é o Instagram, o Meta
> já cobre a maior parte do valor.

### 📍 Onde colar as variáveis
- **Produção (Railway):** projeto `Site_CRM_Pousada_Vo_Testa` → serviço `web` →
  **Variables** → adicionar as chaves (o deploy reinicia sozinho).
- **Testar local:** no `.env` (com `MIDIA_GATEWAY=meta` + `META_CAPI_TEST_CODE`),
  rodar o servidor e conferir na aba "Testar eventos".

### ✅ Pendências (checklist)
- [ ] Meta: ter Gerenciador de Negócios + Página conectada.
- [ ] Meta: copiar o **ID do Pixel** (`META_PIXEL_ID`) — mesmo da LP.
- [ ] Meta: gerar o **token da Conversions API** (`META_CAPI_TOKEN`).
- [ ] Meta: `MIDIA_GATEWAY=meta` no Railway + teste com `test_event_code`.
- [ ] Meta (Fase C): permissão `ads_read` + preencher `id_externo` nas campanhas.
- [ ] Google: solicitar **developer token** (acesso básico) — processo lento.
- [ ] Google: OAuth2 + ação de conversão + `GOOGLE_ADS_CUSTOMER_ID/CONVERSION_ACTION`.

## 4. Ordem recomendada e por quê

1. **Fase A primeiro** — barata, sem burocracia, e **já entrega o gerenciador** (custo por
   lead e por reserva por campanha). Habilita a Fase B (captura o `fbclid`/`gclid`).
2. **Fase B depois** — é o que **faz a verba render 2–3×** (otimiza por quem paga). Começar
   pelo **Meta** (Instagram é o motor da campanha; sem revisão para as conversões próprias).
3. **Fase C por último** — conforto (gasto automático); o manual da Fase A cobre até lá.

## 5. Riscos e cuidados
- **Privacidade/LGPD:** dados pessoais só com hash; consentimento no formulário; sem PII
  em log. Alinhar com o time e, idealmente, um aviso de cookies na Página de Captação.
- **Best-effort:** envio de conversão nunca trava a operação (padrão FNRH/Pagamentos).
- **Idempotência:** cada conversão enviada uma única vez (`ConversaoEnviada`).
- **Aprovações demoram:** developer token do Google e revisão do Meta podem atrasar — o
  modo `simulado`/manual mantém o gestor útil enquanto isso.

## 6. Resumo
O ciclo fecha com: **(A)** capturar de qual anúncio veio o lead + gasto + painel;
**(B)** devolver a venda real às plataformas (o elo que falta, maior retorno);
**(C)** puxar o gasto sozinho. Tudo no padrão de **gateway plugável** já usado no projeto,
degradando para o modo manual sem nenhuma integração externa.

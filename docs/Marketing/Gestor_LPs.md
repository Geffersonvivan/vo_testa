# Gestor de Páginas de Captação (Landing Pages) — Comercial

> Plano de implementação. Uma **Página de Captação** ("Landing Page") vira **dado
> editável** dentro do módulo Comercial: você cria, publica, acompanha, e os cadastros
> caem no **funil** que já existe. Sem abreviaturas: "Página de Captação" = página única
> de campanha; "funil" = o Kanban de `Oportunidade`.

## Objetivo

Transformar a Página "Fundador" (hoje um protótipo) em um **recurso do produto**:
- **Criar** uma página preenchendo um formulário (sem programar).
- **Publicar** e obter uma URL pública (`/captacao/<slug>/`) para colar na bio do Instagram.
- **Acompanhar** visitas, leads, conversão e reservas geradas.
- **Cada cadastro cai no funil** já etiquetado com a campanha que o gerou.

## Por que é barato

O Comercial já tem `Oportunidade` (card do funil), `EtapaFunil`, score, metas e o serviço
`capturar_lead_site(...)` que **já cria a oportunidade a partir de um lead do site**. Só
falta a camada de "página" por cima e o **carimbo** do lead com a página de origem.

---

## Arquitetura da Fase 1

### 1. Model novo — `PaginaCaptacao` (em `apps/comercial/models.py`)
Uma linha por campanha, com conteúdo editável:
- Identidade: `nome` (interno), `slug` (URL), `status` (rascunho/publicada/encerrada),
  `tema` (começa com "fundador").
- Destino do lead: `tipo_interesse` (hospedagem/evento/day use) — cai na régua certa.
- Conteúdo: `selo_texto`, `hero_titulo`, `hero_subtitulo`, `historia_titulo`,
  `historia_texto`, `oferta_titulo`, `oferta_texto`, `cta_texto`, `vagas_restantes`,
  `data_evento` (para o contador regressivo).
- Metas e medição: `meta_leads`, `visitas` (contador).
- Auditoria: `criado_por`, `criado_em`, `atualizado_em`, `publicada_em`.
- Propriedades: `publicada`, `url`, `leads`, `conversao`.

### 2. Atribuição lead ↔ página
Campo `pagina_captacao` (FK, opcional) em `Oportunidade`. O `capturar_lead_site` ganha o
parâmetro `pagina=` e carimba cada captura. É o que permite medir "reservas por campanha".

### 3. Medição de visitas
Contador `visitas` incrementado a cada acesso público (via `F()`), para calcular
**conversão = leads ÷ visitas**.

### 4. Página pública (fora do `/crm/`)
Rota `/captacao/<slug>/` (módulo `apps.comercial.urls_publicas`, montado na raiz em
`config/urls.py`). Template **standalone** com a fonte Neco, o logo, a roda d'água e a
paleta reais do site (Noturno/Madeira/Lampião/Pergaminho/Musgo). O formulário posta para
a própria rota → `capturar_lead_site(pagina=..., tipo_interesse=...)` → agradecimento.
Página em rascunho retorna 404 (não vaza).

### 5. Telas de gestão (dentro do Comercial, `@requer_modulo(COMERCIAL)`)
- **Lista** (`comercial:paginas`): nome, status, visitas, leads, conversão, link copiável.
- **Nova / Editar** (`comercial:pagina_nova` / `pagina_editar`): o formulário.
- **Detalhe** (`comercial:pagina_detalhe`): métricas + **QR Code** + link + os leads
  daquela campanha (cards do funil) + publicar/despublicar/encerrar.
- Sub-link "Páginas" no menu do Comercial (ao lado de Caçador e Instagram).

### 6. Semente
Comando `manage.py popular_lp_fundador` cria a página "Fundador" da inauguração se não
existir (idempotente), já publicada, com os textos aprovados no protótipo.

### 7. Testes
- Página em rascunho → 404; publicada → 200 e conta visita.
- POST no formulário → cria `Oportunidade` no funil com `origem=site`,
  `pagina_captacao` = a página e `tipo_interesse` correto.

---

## Fora do escopo (Fase 2, depois do lançamento)
- Vários temas/modelos e blocos reordenáveis (construtor visual).
- Parâmetros de rastreio de origem (de qual anúncio/post veio o lead) e teste A/B.
- Custo por lead amarrado ao gasto de mídia; puxar os quartos da vitrine real na página.
- Visitas por dia (série temporal) para gráfico de conversão no tempo.

---

## Como usar (operação)
1. Comercial → **Páginas de Captação** → **Nova** (ou rode `popular_lp_fundador`).
2. Preencha os textos e a oferta → **Publicar**.
3. Copie o link (`/captacao/fundador/`) → cole na **bio do Instagram** e nos vídeos.
4. Acompanhe **visitas · leads · conversão**; os cadastros aparecem no **funil**.

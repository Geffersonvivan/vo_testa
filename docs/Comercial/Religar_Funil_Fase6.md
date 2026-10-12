# Religar o Funil à Fase 6 (motor de preço + políticas) + layout

> Plano aberto (11/10/2026). O painel **"Quartos para este lead"** (WIP *Descritivo de
> Quartos*, `apps/comercial/quartos.py` + `templates/comercial/_painel_quartos.html` /
> `_comparar_quartos.html`) foi escrito **antes** da Fase 6 e nunca foi religado ao motor
> de preço, à trava de colchões nem à política de cancelamento. Também destoa do design
> system. Este doc é o plano de correção.

## Diagnóstico (o que está defasado)

- **Preço plano (R$ 500 fixo):** `quartos.py._preco_periodo` usa
  `reservas.diaria_media_unidade` (tarifa de **2 pax**). Ignora **pessoa adicional,
  criança (½/grátis), ISS 4% e taxa de turismo**. Mostra "R$ 500" (250×2) em vez do
  preço real da motor.
- **"Valor estimado R$ 0,00":** o painel exibe preços mas **não registra cotação** — o
  valor estimado só enche via "Registrar cotação" (que já passa pela motor). Desconectado.
- **Colchão/políticas antigos:** o aviso "⚠️ Antes de oferecer — *Colchão extra não cabe
  — espaço apertado*" vem do modelo **antigo** (colchão cobrava/"apertava"). No modelo
  novo o **colchão não cobra** (é só disponibilidade) e a restrição real é a **trava do
  pool por noite** (`conferir_arranjo`/`uhs_disponiveis(adultos=…)`). `comporta()` idem.
- **Layout à parte:** o painel tem estilo próprio (herança do mockup), fora dos tokens
  "Lampião" (`.cartao`/`.selo`/`.num`) do resto da oportunidade.

## Plano (fases)

### Fase A — Preço do painel pela motor  ✅ FEITA
- `quartos.py`: `_preco_periodo` → `_cotacao_periodo(uh, op)` + `_preco_item(uh, op)`,
  que chamam `precos.cotacao(...)` com a lotação real do lead (`faixas_oportunidade(op)`,
  agora pública, deriva adultos/0-5/6-15 de `idades_criancas`). Usados em
  `quartos_para_lead`, `comparar` e `texto_oferta`.
- Cada card traz `diaria` (por pessoa) + `total` (com **ISS + taxa de turismo**) +
  `hospedagem`/`iss`/`taxa_turismo` para o detalhamento (ou "a partir de" 2 pax sem
  datas). `texto_oferta` mostra hospedagem + taxas (quitadas no check-out) + total.
- Teste: `PainelQuartosLeadTests.test_card_precifica_pela_motor_com_pessoa_adicional_e_taxas`
  (card = recepção/site: 3 ad + 2 crianças 6-15 → 580/noite + taxas). 307 testes verdes.
- **Nota p/ Fase D:** as chaves novas (`hospedagem`/`iss`/`taxa_turismo`) já existem no
  item; o template vai exibi-las no layout novo.

### Fase B — Disponibilidade/colchão no modelo novo  ✅ FEITA
- `quartos.py._colchoes_info(uh, op)`: arranjo sugerido (`colchoes.sugerir_arranjo`) +
  status do pool por noite (`conferir_arranjo`) para a lotação do lead. A disponibilidade
  do card agora é **fisicamente livre E com colchão no pool** — um quarto que comporta mas
  sem colchão extra na noite cai em "Indisponíveis" com `motivo="sem_colchao"` (não "ocupado").
- O aviso "Antes de oferecer" vira **computado** (bloqueio/atenção do pool) + os pontos da
  ficha; o texto antigo **"Colchão extra não cabe — espaço apertado"** foi removido do seed
  (`popular_fichas_comerciais`, 01/02 → `[]`) e limpo do banco. Colchão não é custo.
- `item["arranjo"]` (casais/solteiros/sofá/extra) exposto para a Fase D.
- Testes: disponibilidade respeita o pool (serve com pool, cai em indisponível sem pool).

### Fase C — Conectar painel → cotação (motor) + proposta  ✅ FEITA
- `oferecer_quarto` (view): no POST, além de logar a oferta, **registra a cotação**
  (`registrar_cotacao`, motor + taxas) quando há datas e a op está aberta → **Valor
  estimado preenche** e move a etapa para "Cotação enviada". Sem datas, só a oferta
  (degrada). Devolve `cotou` no JSON.
- `texto_oferta` já traz **preço itemizado + taxas** (Fase A) e agora a **política de
  cancelamento** (`cancelamento.descricao_politica()` — 7 dias / 10%).
- "Comparar" usa os preços da motor (Fase A).
- Testes: "Enviar ao cliente" com datas cria Cotacao + preenche `valor_estimado`; o texto
  traz "Cancelamento".

### Fase D — Layout condizente (design system)  ✅ FEITA
- O CSS `pq-*` (inline na `oportunidade.html`) já usava os tokens; o que faltava era o
  layout **refletir os dados novos**:
  - **Montagem de camas** por card (`item.arranjo.montagem` — "1 cama de casal + 1 de
    solteiro + sofá · 1 colchão extra"), via `_montagem_texto`.
  - **Preço itemizado** na ficha (hospedagem + ISS + taxa de turismo + **total**, com `.num`
    tabular) + nota "quitados no check-out"; subtítulo da diária no preço do card.
- Polidas as cores hard-coded do aviso para os tokens (`--alerta`/`--alerta-bg`).
- `tiny-text` do painel (micro-texto denso pré-existente) suprimido com disclosure
  (`.impeccable/config.json`, escopo do arquivo).

**🏁 Funil religado à Fase 6** (A preço + B colchão/disponibilidade + C cotação/proposta +
D layout) — **804 testes verdes**.

### Fase E — Testes
- `comercial/tests.py`: card precifica pela motor (= site); "Enviar ao cliente" cria
  cotação e preenche `valor_estimado`; quarto sem colchão na noite sai dos "servem"/vira
  aviso; `texto_oferta` traz política + taxas.

## Ordem e esforço
A → B → C → D → E. A/B/C = correção funcional (preços e políticas); D = visual. Reusa
`precos`, `cancelamento`, `uhs_disponiveis`, `registrar_cotacao` — nenhuma lógica de
dinheiro nova.

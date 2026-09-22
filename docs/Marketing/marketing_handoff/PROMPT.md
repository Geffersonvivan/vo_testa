# Marketing — corrigir o layout para bater com o protótipo

Cole tudo no Claude Code. Este arquivo substitui qualquer instrução de layout
anterior do módulo de Marketing.

---

O módulo de Marketing foi implementado com a lógica certa e o layout errado.
Várias telas foram reconstruídas com estrutura diferente da especificada. Sua
tarefa é **corrigir o layout**, sem tocar na lógica que já funciona.

## Passo zero: veja o protótipo rodando

Abra `marketing_handoff/preview/ABRIR-Marketing.html` **com duplo clique**.
Arquivo único, autocontido, funciona por `file://`.

Se você tentou antes e viu página em branco, era o outro arquivo
(`Kanban Marketing.dc.html`), que importa `dados.js` por módulo ES — bloqueado
em `file://`. Use o `ABRIR-`.

**Navegue pelas quatro abas e abra uma ficha antes de escrever código.** O que
está nesse arquivo é a especificação. Onde a implementação divergir dele, a
implementação está errada.

Inspecione no DevTools e **copie a estrutura**: hierarquia de divs, medidas,
raios, pesos de fonte, espaçamentos. Os estilos estão inline no protótipo
justamente para serem lidos assim. Não releia descrição — leia o DOM.

---

## Parte 1 — Divergências estruturais

### 1.1 Calendário está como grade de dias

Está como grade mensal com bolinhas nas células. Deve ser **linha do tempo**:
uma linha por campanha, com uma **barra** cobrindo o período de vigência.
Campanha é intervalo, não evento de um dia — a grade não mostra que a Réveillon
vai de 20/12 a 05/01.

- Coluna fixa de 200px à esquerda: nome e período da campanha
- Trilha à direita com as barras posicionadas em porcentagem
- Peças são pontos sobre a barra, no dia em que saem
- Linha vertical vermelha marcando hoje
- Barra hachurada = planejado; cheia = realizado
- Marcos (Natal, Dia das Mães…) como linhas tracejadas verticais com rótulo
- Escala Mês e escala Ano, alternadas por pílula

### 1.2 Ficha da campanha deve ser gaveta, não página

Está como página inteira com formulário empilhado. Deve ser **gaveta lateral de
520px**, entrando pela direita sobre o quadro, fundo escurecido atrás. O usuário
abre, edita e fecha sem perder o quadro de vista. Não existe "← voltar ao
quadro".

### 1.3 Controles nativos do navegador

`<select>` de Mês e Ano no Relatório, `<input>` sem estilo, checkbox padrão.
Nenhum controle do CRM tem aparência padrão de navegador.

- Seleção de mês: **pílulas** em linha (`.seg-filtro`), não dropdown
- Todo `input` e `textarea`: borda `--fio`, raio 12px, foco com anel âmbar
- Checklist: um círculo que alterna ao clicar, não dois botões por linha

### 1.4 Ocupação sem dado

Todas as semanas em 0%, e "campanha ativa e vazio" repetido em toda linha. Com
0% em tudo o diagnóstico perde sentido — confira se a consulta de reservas está
filtrando pelo período certo.

---

## Parte 2 — A faixa de urgências (topo do Quadro)

Hoje "Próximos dias" ocupa a tela inteira e empurra o kanban para fora da
primeira dobra. É uma tira de contexto; o quadro é a tela.

### 2.0 São dois cartões lado a lado, não uma lista

A faixa é um grid de duas colunas:

```css
display: grid;
grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
gap: 14px;
margin-bottom: 18px;
```

À esquerda **Próximos dias** (cartão branco, borda `--fio`); à direita
**Atrasado** (borda `#F3DCCB`, cabeçalho `#FDF6F1`, título e resumo em
`--perigo`). Cada um com no máximo três a quatro linhas visíveis. Juntos não
passam de ~500px de altura, e o kanban aparece logo abaixo.

Em tela estreita o `auto-fit` empilha sozinho — não escreva media query.

### 2.1 A consulta não filtra por data

Aparecem 14 itens, **sete marcados "sai hoje"** — sete peças de campanhas
diferentes não saem todas no mesmo dia. O resto mostra "24/09", que é ontem.

Só peças de hoje até domingo, não prontas:

```python
hoje = timezone.localdate()
ate = hoje + timedelta(days=7)
pecas = (Peca.objects
    .filter(data__gte=hoje, data__lte=ate)
    .exclude(status="pronta")
    .select_related("campanha")
    .order_by("data"))
```

Peça com data no passado **não** entra aqui: é atraso, e tem painel próprio.

### 2.2 Falta o cartão de atrasos

O segundo cartão da faixa lista peça vencida e campanha parada há mais de duas
semanas. É ele que recebe o "24/09", não o de próximos dias.

Cada linha traz um selo **PEÇA** à esquerda (fundo `#FDEDE4`, texto `--perigo`,
10px, raio 99px), depois nome e canal em negrito, e abaixo campanha ·
responsável · há quanto tempo venceu. No cabeçalho, à direita: **"2 pendências
atrasadas"**.

Se não houver atraso, o cartão não aparece e Próximos dias ocupa a faixa toda.

### 2.3 Linhas grandes demais

Cada linha tem ~76px. No protótipo tem **51px**:

- Linha: `padding: 9px 12px`, raio 12px, fundo `--superficie-2`, borda `--fio`
- Nome da peça: 12.5px, peso 700
- Subtítulo: **campanha · canal · responsável**, 11px, `--tinta-suave`
- Ambos com `text-overflow: ellipsis`
- Selo de prazo à direita: 10.5px, raio 99px. Hoje vem em âmbar (`#FDF3E0` /
  `--alerta`) com o texto **"sai hoje"**; os demais em cinza com a data `25/09`

### 2.4 Falta teto de altura

Com semana cheia, mesmo linhas compactas empurram o quadro. A lista tem
`max-height: 232px; overflow-y: auto` — cerca de quatro linhas visíveis, o resto
rola dentro do cartão.

### 2.5 Falta o resumo no cabeçalho

À direita do título, 11.5px `--tinta-suave`: **"1 hoje · 2 até domingo"**. Sem
isso é preciso contar as linhas para saber o volume.

Resultado esperado: a faixa inteira em ~250px de altura, kanban logo abaixo. No
protótipo, "Próximos dias" tem 239px com 3 itens.

---

## Parte 3 — Tokens e medidas

**Nenhuma cor nova.** O protótipo usa os valores literais equivalentes aos
tokens do projeto:

| No protótipo | No projeto |
|---|---|
| `#F7F5F1` fundo da página | `--canvas` |
| `#FFFFFF` / `#FDFCFA` cartões | `--superficie` / `--superficie-2` |
| `#EFEBE3` / `#E8E3DA` filetes | `--fio` |
| `#2C2722` tinta principal | `--tinta` |
| `#756D62` tinta secundária | `--tinta-suave` |
| `#9A4429` / `#B25837` ação e destaque | `--terra` |
| `#3F5A3F` / `#4A6B44` positivo | `--musgo` |
| `#8E3B18` alerta e atraso | `--perigo` |
| `#7A5A1E` atenção | `--alerta` |
| Cabin | `--fonte-titulo` |

**Medidas:**

- Cartão: raio 18–20px, borda 1px `--fio`, sombra
  `0 1px 2px rgba(58,47,38,.04), 0 24px 48px -34px rgba(58,47,38,.55)`
- Pílula de aba e filtro: raio 99px, ativa com fundo `#2C2722` e texto claro
- Coluna do quadro: 268px, cabeçalho grudado no topo ao rolar
- Cartão de campanha: raio 14px, arrastável, com barra fina de checklist
- Gaveta da ficha: 520px, entra pela direita
- Botão primário: gradiente `#B25837 → #9A4429`, texto branco, raio 14px

**Contraste é requisito.** Todo texto abaixo de 18px precisa de 4,5:1 contra o
fundo real — inclusive nota de gráfico, id de card e rótulo de eixo. O protótipo
está em zero violações; clarear um cinza "para ficar mais leve" quebra isso.
Texto mínimo: 11px.

---

## Parte 4 — Decisões que têm motivo

Não são estéticas. Mantenha, ou traga um motivo melhor:

**Barra de ocupação em escala absoluta**, com trilho hachurado marcando a casa
cheia. Normalizar pelo pico faria 9% de ocupação desenhar barra cheia, dizendo o
oposto do que o painel existe para mostrar. O branco é a informação.

**Barra de comparação de campanhas em escala relativa ao pico** — ali a pergunta
é "qual rendeu mais". As duas escalas convivem porque as perguntas diferem.

**Dica instantânea** — balão posicionado por JS seguindo o ponteiro, não `title`
nativo e não pseudo-elemento CSS. O `title` demora ~1s e a leitura de calendário
é de varredura; o pseudo-elemento morre no `overflow` do container rolável. A
área de toque de uma linha de marco tem 9px, não 1px.

**Rótulo dentro da barra só quando cabe a palavra inteira.** No calendário anual
as barras são estreitas e o nome já está na coluna da esquerda.

**Rótulos de marco em duas linhas alternadas**; quem ainda colidir perde o texto
e mantém o tick com o nome no hover. Melhor um marco mudo que dois pela metade.

**Zero é zero.** Barra de ocupação vazia não tem piso de 2px — num painel cuja
tese é o espaço em branco, desenhar 2px onde não há ocupação é mentir.

**Coluna vazia diz por que está vazia.** Com "Só os meus" ligado: "Nada seu aqui
· 2 campanhas de outras pessoas". Vazio por filtro não pode parecer vazio de
verdade.

**Moeda formatada em repouso, crua em foco.** `R$ 5.200,00` parado, `5200` ao
focar; a máscara brigaria com quem digita.

**Nada de beco sem saída.** Todo estado terminal oferece próximo passo.

---

## Parte 5 — O que não fazer

- Não criar cor, sombra ou raio fora do `app.css`
- Não trocar a pílula segmentada por aba estilo pasta de navegador — é o
  vocabulário de navegação de toda tela multi-visão do CRM
- Não adicionar ícone onde o protótipo não tem
- Não usar emoji
- Não centralizar texto alinhado à esquerda, nem o contrário
- Não mexer em espaçamento "para respirar mais" — a densidade é a do CRM
- Não tocar na lógica que funciona: verba, checklist, aprovação, atribuição de
  leads, cálculo de ocupação
- Não editar migrações aplicadas nem o `app.css`

**Não reinterprete.** Se algo parecer estranho, o motivo provavelmente está na
Parte 4. Se depois de ler ainda parecer errado, **pergunte** em vez de decidir.

---

## Ao terminar

Abra as quatro abas lado a lado com o protótipo e compare: hierarquia
tipográfica, espaçamento, ordem dos elementos, textos de interface (copie as
frases — foram escritas com cuidado), estados vazios e de erro.

Rode uma varredura de contraste. Qualquer texto abaixo de 4,5:1, corrija antes
de seguir.

Onde o protótipo e o `app.css` divergirem, **o `app.css` ganha** — e registre a
divergência no roteiro.

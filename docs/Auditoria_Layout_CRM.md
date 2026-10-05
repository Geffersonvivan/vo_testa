# Auditoria de Layout — CRM Pousada Vô Testa

> **STATUS 05/10/2026 — TODAS as correções aplicadas e verificadas** (737 testes OK,
> `makemigrations --check` limpo, telas-chave reconferidas por screenshot desktop+mobile).
> Ainda **não commitado** (aguarda ordem). Resumo das correções no fim do documento.
>
> Relatório vivo. Auditoria **de layout/UI** (não de lógica), 03/10/2026.
> Método: multiagente (8 auditores — 7 clusters de telas + 1 do shell/tokens),
> julgando **pelo que renderiza** em screenshots reais **desktop (1440px) e mobile
> (390px)** + corroboração nos templates (`grep` de hex/raio/sombra hard-coded).
> Régua objetiva: tokens "Lampião" em `static/css/app.css`, o kit
> `templates/comercial/_estilo_elegante.html`, os princípios da skill `apple-design`
> e a seção "Design & UI" do `CLAUDE.md`.
> **Diagnóstico apenas — nenhum código foi alterado.**

## Como ler

Severidade: **alta** = quebra de uso visível · **média** = destoa do design system de
forma perceptível · **baixa** = refino. Achados marcados **[FIX-ÚNICO]** se corrigem muitas
telas de uma vez (maior alavancagem — começar por eles).

## Cobertura

60 telas internas + 5 públicas, cada uma em desktop e mobile (**120 screenshots**;
`fiscal` 404 = módulo inativo). Clusters: Shell/tokens · Dashboard+Núcleo ·
Reservas · Dinheiro/Gestão · Estoque+PDVs · Operação · Comercial+Marketing · Site público.

## Correção de régua (achado adversarial da síntese)

Vários agentes reportaram as tabelas de dados como **"alta — colunas somem no mobile,
dado inacessível, sem scroll"**. **Isso está parcialmente errado.** Em
`@media (max-width:820px)` o `.tabela` vira `display:block; overflow-x:auto;
white-space:nowrap` (`app.css:2432-2437`) — ou seja, **as tabelas rolam
horizontalmente no mobile; o dado não some**, só não aparece no screenshot full-page.
O defeito real é **falta de *affordance* de rolagem** (sem sombra/indicação) **e a 1ª
coluna não é sticky** (perde-se a referência da linha ao rolar). Por isso o achado foi
**rebaixado para média** e consolidado em **S1** — exceto onde a rolagem está realmente
bloqueada (manutenção, calendário) ou onde esconde o CTA primário (governança), que
seguem **alta**.

---

## 🔴 Alta (quebra de uso)

### A1 — Manutenção: a página inteira estoura no mobile
`templates/manutencao/painel.html:19` usa `.colunas.colunas-2-1` (`app.css:2115` =
`grid 2fr 1fr`), mas a regra de colapso mobile (`app.css:2427`) só lista
`.colunas, .colunas.form-cartao` — **não inclui `.colunas-2-1`**. Resultado: em 390px a
página mede ~743px (overflow horizontal da página toda), o form "Nova OS" fica ao lado
da tabela e a coluna Bloqueio é cortada.
**Correção [FIX-ÚNICO]:** adicionar `.colunas-2-1` (e qualquer `.colunas-*`) à regra de
`app.css:2427`. Resolve manutenção e qualquer outra tela 2-1.

### A2 — Calendário de Marketing: gantt inutilizável no mobile
`templates/marketing/calendario.html:19` — a `<section>` da timeline tem
`overflow:hidden` e o eixo tem 31 colunas flex; em 390px os dias viram uma tira de
dígitos sobrepostos e as barras somem. **Diferente das tabelas, aqui NÃO há scroll**
(`overflow:hidden`). Bônus: o template é quase todo `style="..."` inline com hex/raio
crus.
**Correção:** no mobile trocar `overflow:hidden` por `overflow-x:auto` no wrapper e dar
`min-width` fixo (~720px) ao miolo do gantt, para rolar legível (como o Kanban faz).

### A3 — Governança: botões de ação escondidos pelo scroll sem pista (caso agudo de S1)
`templates/governanca/painel.html:43` — no mobile as colunas finais Camareira e **Ação**
(CTAs "Iniciar limpeza"/"Abrir faxina"/"Inspecionar", o ponto da tela) ficam fora da
viewport. A tabela rola (S1), mas **sem affordance** o operador não descobre. Como aqui
o que some é o CTA primário da operação, trata-se como alta.
**Correção:** além do fix de affordance (S1), no mobile mover a Ação para fora da linha
(cartão empilhado por quarto) ou coluna Ação `position:sticky` à direita.

### A4 — Sidebar recolhida: ~10 módulos com o mesmo ícone (desktop)
`templates/base.html:97` usa **um único `<svg>` placeholder** para todo item de
`menu_modulos`. No rail recolhido (padrão no desktop), onde só o ícone aparece, os
módulos ficam **visualmente indistinguíveis**. (No mobile ≤820px o rail expande com
rótulos, então afeta sobretudo o desktop.)
**Correção:** mapa `codigo_do_módulo → svg` próprio, como já existe para os itens fixos.

---

## 🟡 Média — sistêmicos (FIX-ÚNICO, máxima alavancagem)

### S1 — Tabelas de dados sem affordance de scroll nem coluna-referência sticky no mobile
49 templates usam `.tabela`. No mobile elas rolam (`app.css:2432`), mas sem sombra/pista
de que rolam e sem fixar a 1ª coluna → **parece dado cortado** e perde-se a referência
da linha. Telas afetadas: pessoas, hospedes, fornecedores, agencias, funcionarios,
temporadas, reservas_lista, reservas_grupos, fin_contas, fin_lancamentos, caixa_sessoes,
conciliacao_manual, conciliacao_painel, loja_vendas, estoque_posicao, estoque_produtos,
comercial_respostas, comercial_paginas, nps, governança (ver A3).
**Correção [FIX-ÚNICO]:** no `.tabela` em overflow — (a) gradiente/sombra lateral de
scroll-hint; (b) `position:sticky; left:0` na 1ª coluna (th+td). Um ajuste em `app.css`
cobre as 49 telas.

### S2 — Colunas de dinheiro/número sem `.num` (desalinham à esquerda)
A régua exige `.num` (`app.css:2369` = `text-align:right` + `tabular-nums`) em toda
coluna de valor/quantidade — faltando em várias telas, inclusive **de dinheiro**:
- `estrutura.html:15-33` — A partir de, Tarifa base, Lotação, Quartos
- `nucleo/caixa_sessoes.html:12,21-25` — **Diferença** (dado-chave de caixa)
- `nucleo/contas.html:20,29` — **Valor**
- `nucleo/lancamentos.html:32,42` — **Valor**
- `reservas/lista.html:30,39-40` — Noites, Diária
- `estoque/posicao.html:28,36-39` — Saldo, Mínimo, Custo médio, Valor
- `estoque/produtos.html:20,29-31` — Custo médio, Preço venda, Saldo
- `loja/vendas.html:14,23` — Total
- `pessoas.html:45-46` / hospedes — Documento (CPF/CNPJ)
- `escala/minha.html:17,22` e `escala/turnos.html:16,20` — Horário
**Correção:** adicionar `class="num"` ao `<th>` **e** `<td>` dessas colunas (padrão que o
BOH já faz certo em `reservas/partials/boh_quadro.html`).

### S3 — Cores hard-coded / paletas paralelas em vez de tokens
Vários vermelhos/dourados/laranjas fora da paleta — "dois de cada" no sistema:
- `#8C2B1B` **7×** (`app.css:210,934,949,1012,1076,1494,1498`) — vermelho paralelo ao
  token `--perigo #9A3B1E` (login .error, .texto-alerta, selo cancelada, mural).
- `dashboard.html:229-238,297,313` — paleta de gráficos toda em hex cru (`#051C2C`,
  `#D7A048`, `#2E483E`, `#4F2C1D`…) ≠ tokens. **Ler via
  `getComputedStyle(...).getPropertyValue('--lampiao')`** em vez de hex.
- `_estilo_elegante.html:23,51,52` — fallbacks de dourado divergentes (`#c8912f`,
  `rgba(200,145,47)`) ≠ `--lampiao #E2A84A` → Comercial tem um dourado diferente do shell.
- `app.css:705` `.selo-em_andamento/.selo-em_limpeza { #B5591C / rgba(200,98,30) }` —
  laranja cru (manutenção/governança). Usar `--alerta`/`--alerta-bg`.
- `app.css:1068-1076` cores de status do mapa de reservas (pré-reserva/hospedada/
  cancelada) em hex cru; `app.css:2123-2126` fundos de prioridade em `rgba()` cru.
- `comercial/funil.html:26-37` chips de temperatura/parado/wpp em hex ≠ semânticas.
- `app.css:381` topbar `background: rgba(241,236,225,.82)` cru em vez de
  `color-mix(in srgb, var(--canvas) 82%, transparent)`.
- Hex idênticos ao token mas desacoplados: `#04151F` (=`--noturno`) em
  `app.css:1889,1900`.
**Correção [FIX-ÚNICO]:** substituir pelos tokens semânticos; para os gráficos, expor os
valores de `:root` ao JS.

### S4 — Links sem classe caem no azul sublinhado do navegador
Fora da marca por falta de estilo:
- `relatorios/index.html:16-18` — classes `.cartao-atalho/.atalho-titulo/.atalho-seta`
  **não existem** no CSS → títulos e setas "→" viram link azul sublinhado.
- `conciliacao/manual.html:12` — "← voltar ao painel" azul default.
- `comercial/tarefas.html:11-13` — abas "Minhas/Da equipe" usam `<a>` dentro de
  `.pdv-seg`, mas `app.css:2062` só estiliza `.pdv-seg button` → renderiza
  **"MinhasDa equipe"** colado e azul.
**Correção:** definir as classes faltantes (ou reusar `.cartao`/`.botao-mini`); trocar a
regra para `.pdv-seg button, .pdv-seg a`.

---

## 🟡 Média — por tela

- **Lavanderia** (`painel.html:27`): `<input type="date">` cru renderiza date-picker
  nativo `mm/dd/yyyy` (americano), destoa dos campos da marca e do pt-BR. Estilizar +
  formato dd/mm.
- **Conciliação** (`painel.html:45,59`): `<input type=file>` nativo ("Choose File") sem
  estilo. Envolver em label + botão `.botao-neutro`.
- **Comercial — Caçador** (`cacador.html:17`): grid fixo `92px 1fr` mantido no mobile →
  score ocupa 1/3 e o texto fica espremido. Colapsar p/ 1 coluna em tela estreita.
- **Escala — grade** (`partials/grade_conteudo.html:7`): bloco de validação "Cobertura
  abaixo do mínimo" é uma parede de texto numa linha só (medida ≫66ch). Quebrar em
  lista/chips por dia.
- **Escala — minha** (`minha.html:14`): estado vazio é frase solta num canvas enorme.
  Envolver em `.cartao` com ícone/CTA.
- **Pagamentos — painel** (`painel.html`): lista de ~50 cobranças sem paginação, rolagem
  longuíssima. Paginar/limitar.
- **Comercial — painel** (`painel.html:74-75`) e **Pagamentos conciliação**
  (`conciliacao.html:17-20`): inputs/KPIs sem a classe de campo/`.letreiro` do sistema
  (borda fina default; rótulos sem tracking). Padronizar.
- **Estilos inline recorrentes**: `manutencao/painel.html:48`, `nps/painel.html:13-50`,
  `registration/login.html:26`, `funcionario_form.html:43` (`font-size:.58rem` no selo),
  `marketing/calendario.html` (inteiro). Mover p/ classes utilitárias com tokens.

---

## 🟢 Baixa (refino)

- **Dashboard**: estados vazios "Chegadas/Saídas de hoje" são texto cru em cartões
  grandes (espaço morto); legenda do donut "Mix de pagamento" com R$ à esquerda sem
  `.num`.
- **BOH** (`partials/boh_quadro.html:3,5`): título repetido como `<h2>` e como `<th>` da
  1ª coluna. Usar rótulo curto no `<th>`.
- **Restaurante — mesas / Lavanderia / Escala-turnos / Estoque**: status "Ativa/Ativo"
  como texto puro em vez de `.selo .selo-sucesso` (inconsistente com os demais status).
- **Estoque — inventários** (`inventarios.html:24`): empty-state sem CTA (outros do
  módulo têm "Cadastre o primeiro").
- **Shell**: `.topbar-dir/.avatar-topo` (`app.css:410-411`) são CSS órfão — o avatar não
  é renderizado na topbar; no rail recolhido o usuário some. Remover o CSS morto ou
  renderizar o avatar.
- **Modulos_central** (mobile): parágrafo intro largo e de baixo contraste
  (`--tinta-suave` em fonte pequena); botões Ativar/Desativar com toque apertado.

---

## 🌐 Site público (Tailwind — ruleset próprio, fora dos tokens Lampião)

Avaliado por consistência interna, contraste e responsividade (não pelos tokens do CRM).

- **[média] Contraste** — `site/sections/quartos.html` e `quartos_todos.html` usam
  `text-pergaminho/50` e `/40` (cinza desbotado sobre noturno) em descrição, preço,
  capacidade e pills → abaixo de ~4.5:1 WCAG para fonte pequena. Subir p/ ≥/70 (preço e
  rótulos em pergaminho sólido).
- **[média] LP Fundador** (`comercial/captacao_publica.html:9-16`): paleta **própria
  divergente** (`--noturno:#051C2C`, `--lampiao:#D7A048`, `--pergaminho:#EFDBB2`) + fonte
  `Neco`, enquanto o site usa `#04151F`/`#E2A84A`/Fraunces+Hanken. Dourado, pergaminho e
  tipografia visivelmente diferentes. Reusar os tokens/fontes do site.
- **[média] `.fade-section{opacity:0}`** (`animations.css:37`): seções só aparecem via
  IntersectionObserver (JS). Sem JS, conteúdo some. Fallback `.js .fade-section{…}` ou
  `<noscript>`.
- **[baixa] `prefers-reduced-motion`** (`animations.css:112-118`): só desliga
  view-transitions; engrenagens/`pulse`/`float`/slide-in continuam. Zerar todas.
- **[baixa] Cards de quarto** (`quartos_todos.html:22-41`): nome do quarto repetido 3×
  (placeholder de foto + título + `descricao_curta` igual ao nome). Placeholder neutro +
  esconder descrição redundante.
- **[baixa] CTA "Reservar"** (`quartos_todos.html:55-57`): `bg-lampiao/10 text-lampiao`
  → afford ância fraca. Usar dourado sólido `bg-lampiao text-noturno`.

---

## Recomendação de execução (por alavancagem)

1. **Fixes únicos primeiro** (poucas linhas, muitas telas): A1 (`.colunas-2-1` no
   colapso), S1 (scroll-hint + 1ª coluna sticky), S2 (`.num` nas colunas de dinheiro),
   S3 (`#8C2B1B`→`var(--perigo)` e paleta de gráficos via tokens), S4 (classes de link).
2. **Quebras isoladas**: A2 (gantt), A3 (ação sticky na governança), A4 (ícones da
   sidebar).
3. **Médias por tela** e depois **baixas/refino**.
4. **Site**: contraste e unificação da LP de fundador.

> Observação: o **site público** usa **Tailwind compilado** — mudanças de classe só valem
> após rebuild (`npx tailwindcss@3 …`); os tokens do CRM (`app.css`) propagam direto.

---

## ✅ Correções aplicadas (05/10/2026)

Tudo resolvido; **sem commit** (aguarda ordem). WIP "Descritivo de Quartos" não foi tocado.

**Altas:** A1 manutenção (`.colunas-2-1` no colapso mobile — página não estoura mais) ·
A2 calendário de marketing (gantt rola na horizontal e fica legível no mobile) ·
A3 governança (coluna de ação `.col-acao` **sticky à direita** no mobile — CTA sempre
visível) · A4 ícones (`templates/componentes/icone_modulo.html` — ícone próprio por módulo
na sidebar recolhida).

**Sistêmicos (fix-único no `app.css`):** S1 tabelas no mobile ganharam **sombra de rolagem +
1ª coluna sticky** (vale para as 49 telas) · S2 `.num` adicionado às colunas de dinheiro/
número (estrutura, caixa_sessoes, contas, lançamentos, reservas/lista, estoque, loja, pessoas,
escala) · S3 cores hard-coded → tokens (`#8C2B1B`→`--perigo`; laranja "em andamento"
promovido a token **`--andamento`**; gráficos do dashboard lêem `getComputedStyle` dos tokens;
mapa/prioridade/topbar/porta via tokens) · S4 links sem classe corrigidos (classes
`.cartao-atalho/.atalho-*` criadas; `.pdv-seg a` passou a herdar a pílula).

**Médias/baixas:** inputs de data/arquivo estilizados · estados vazios elegantes (classe
compartilhada `.estado-vazio` + dashboard/estoque/escala) · validação da escala em lista
(wired no `escala/services.py`) · selos de status (restaurante/lavanderia/escala) · chips do
funil tokenizados · grid do caçador colapsa no mobile · inputs da meta comercial · BOH sem
título duplicado · KPIs de conciliação com `.letreiro`/unidade · CSS órfão removido ·
barras do relatório de marketing com fill para meses com gasto.

**Site público:** contraste `text-pergaminho/40-50 → /70` (preço sólido) · fallback no-JS do
`.fade-section` (gate `html.js`) · `prefers-reduced-motion` desliga todas as animações ·
cards de quarto com placeholder neutro + descrição só quando difere do nome · CTA "Reservar"
dourado sólido · **Tailwind rebuildado**.

**Falso-positivo corrigido na execução:**
- **#2 LP Fundador (paleta/fonte divergente)** — **NÃO procede.** O site público tem paleta
  própria no `tailwind.config.js` (`noturno #051C2C`, `lampiao #D7A048`, `pergaminho #EFDBB2`,
  fonte **Neco**), **diferente** do shell do CRM (`#04151F`/`#E2A84A`/Fraunces). A LP **já usa
  exatamente os valores do site** — está consistente. A auditoria original comparou a LP ao
  shell do CRM por engano. Nenhuma mudança feita (aplicar o "fix" teria quebrado a
  consistência com o site).

**Não endereçado (deliberado):**
- Legenda do donut "Mix de pagamento" (dashboard) é renderizada pelo **Chart.js no canvas** —
  `.num` não se aplica sem reescrever o gráfico (baixa).
- `modulos_central`: o parágrafo usa o `.subtitulo` padrão (max-width 66ch, `--tinta-suave`
  passa ~4.6:1 WCAG AA) — consistente, mantido.

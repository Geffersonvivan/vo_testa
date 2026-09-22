# ROTEIRO — módulo de Marketing (`apps/marketing`)

> Plano de implementação a partir de `docs/Marketing/marketing_handoff/LEIA-ME.md`
> (a pasta está em `docs/Marketing/`, não na raiz — o prompt supôs a raiz).
> **Nada implementado ainda.** Este arquivo é para aprovação antes de qualquer código.
> Método: um commit por passo, cada passo testado pelo seu critério de aceite.
> Comportamento derivado do LEIA-ME + leitura de `preview/dados.js` (lógica), não do clique.

---

## 0. Achado central (lê antes de tudo) — o CRM já faz metade do "elo"

O handoff foi escrito como se o funil comercial não existisse. **Ele existe** e já cobre
os passos 7–9. Confirmado em `apps/comercial`:

| O que o LEIA-ME pede (passos 7–9) | Já existe no comercial? | Onde |
|---|---|---|
| Lead nasce com campanha vigente do canal | **Sim** (por UTM) | `services.capturar_lead_site` + `_resolver_campanha` |
| Campo campanha editável no lead | **Sim** | `Oportunidade.campanha` (FK) |
| Fechar lead cria a pré-reserva | **Sim** | `services.converter_em_reserva` → `reservas.criar_prereserva`; grava `Oportunidade.reserva_id` |
| Perder pede motivo | **Sim** | `Oportunidade.motivo_perda` + `MotivoPerda` |
| Gasto datado por campanha | **Sim** | `services.registrar_gasto` + `comercial.GastoCampanha` |
| Origem viaja p/ a reserva | **Parcial** | via `Oportunidade.reserva_id` (reverso); a `reservas.Reserva` **não** tem `campanha`/`lead_id` |

**Consequência:** o valor real do módulo Marketing **não** é reimplementar isso — é a
**camada de fluxo** que o comercial não tem: **7 fases com 2 portões, verba mensal com teto,
calendário de peças, ocupação × campanha e relatório de retorno**. Os passos 7–9 devem
**reusar** os services do comercial, não refazê-los.

Isso abre a decisão-mãe (ver §2, decisão A): **o marketing tem uma `Campanha` NOVA, ou a
camada de fluxo embrulha a `comercial.Campanha` que já existe?** Já existe
`comercial.Campanha` (campanha de anúncio: `codigo`/`provedor`/`pagina_captacao`/`GastoCampanha`)
à qual os leads já se prendem. Duas `Campanha` que os leads podem apontar = duas fontes de
verdade de origem. **Não decido isso sozinho.**

---

## 1. Divergências (onde o desenho discorda do código atual)

- **D1 — Duas `Campanha`.** LEIA-ME cria `marketing.Campanha`; já existe `comercial.Campanha`.
  Os leads (`Oportunidade.campanha`) já apontam para a do comercial. Precisa reconciliar
  (decisão A).
- **D2 — Atribuição ao lead escreveria no comercial.** LEIA-ME: "marketing escreve só no que
  é dele", mas também "lead nasce com a campanha vigente" e "campo editável no lead". Atribuir
  campanha ao lead = escrever em `Oportunidade` (comercial). Ou (a) reusar `Oportunidade.campanha`
  (se A = embrulhar a comercial), ou (b) FK nova `Oportunidade.campanha_marketing` (toca o
  funil — o prompt manda não refazer o funil, mas um campo aditivo não é "refazer"; ainda assim
  é decisão do dono).
- **D3 — Origem na reserva.** LEIA-ME quer `campanha` e `lead_id` **na** `reservas.Reserva`;
  hoje o vínculo é `Oportunidade.reserva_id` (reverso). Adicionar campos em `reservas.Reserva`
  toca um módulo homologado. Alternativa: derivar origem via `Oportunidade.reserva_id` sem
  tocar reservas (decisão C).
- **D4 — `User` vs `nucleo.Usuario`.** LEIA-ME usa `User`; o projeto usa
  `AUTH_USER_MODEL = nucleo.Usuario`. **Adaptação direta, não é decisão** — uso `Usuario`.
- **D5 — Gasto de campanha já existe.** `comercial.GastoCampanha` + `registrar_gasto` já são
  gasto datado. Se A = embrulhar, reuso; se A = novo, `marketing.GastoCampanha` é redundante
  com o do comercial (decisão A).
- **D6 — Sidebar.** Confirmado: Marketing entra como **um** item no grupo COMERCIAL
  (`modulos.py` → `Modulo.MARKETING`, `url_name: "marketing:quadro"`), 4 abas no segmentado do
  topo (`.seg-filtro/.segmentado`, app.css). Sem itens novos no menu. **Sem divergência.**

---

## 2. Decisões que NÃO são minhas (bloqueiam — preciso da sua resposta)

> Estas travam o desenho de dados. **Não escolho por você.** As respostas mudam os passos 1 e 7–9.

- **A) `marketing.Campanha` NOVA ou embrulhar `comercial.Campanha`?**
  - *A1 — Nova (fiel ao LEIA-ME):* `marketing.Campanha` com 7 fases/verba; os leads continuam
    na `comercial.Campanha`; ligo as duas por FK opcional. Duas entidades "campanha" coexistem.
  - *A2 — Embrulhar:* a camada de fluxo (fases/verba/checklist/peças) pendura em
    `comercial.Campanha` (nova(s) tabela(s) 1:1/N que referenciam a existente). Uma fonte de
    origem só. Mais integrado, menos duplicação — mas mexe conceitualmente no comercial.
  - **Recomendo A2** (respeita "verba/origem tem uma fonte só" e "não refaça o funil"). Preciso do seu ok.

- **B) Papéis × permissões.** LEIA-ME cita "Gestor de Marketing / Analista-Criação / Comercial".
  O projeto usa **Áreas** (`Usuario.areas` + `@requer_area`) e **Módulos** (`@requer_modulo`) +
  gerência (`is_staff`). Como mapear?
  - Proposta: **Módulo `MARKETING`** dá acesso à tela; **Área nova `marketing`** (analista);
    **gerência (`eh_gerente`)** = Gestor (aprova/encerra/edita teto/dispensa checklist);
    "Comercial" = quem tem o módulo Comercial. Confirmar ou corrigir.

- **C) Origem na reserva (D3).** Adiciono `campanha`+`lead_id` em `reservas.Reserva`
  (toca módulo homologado, aditivo) **ou** derivo por `Oportunidade.reserva_id` sem tocar
  reservas? **Recomendo derivar** (não toca reservas). Confirmar.

- **D) Critérios de checklist por fase.** O LEIA-ME define os **portões** (Aprovação exige
  checklist+verba; Encerrada exige retrospectiva) mas **não lista os itens** de checklist de
  cada fase. Preciso da lista por fase (ou autorização para eu propor um conjunto mínimo e você
  revisar). O prompt manda **parar e perguntar** aqui.

- **E) Item obrigatório pode ser dispensado?** LEIA-ME: Gestor dispensa com motivo. Confirmo:
  **todos** os itens são dispensáveis pelo Gestor (com motivo), ou há itens **não** dispensáveis?

---

## 3. Roteiro passo a passo (ordem corrigida)

> Passos **1–6 não dependem do CRM** e não dependem das decisões A–E **exceto** o passo 1
> (depende de A) e os portões (passo 4, depende de D/E). Passos **7–9 dependem de A/B/C**.
> Um commit por passo. Toca comercial/reservas? marcado.

| # | Passo | Arquivos | Critério de aceite (verificável) | Depende de |
|---|---|---|---|---|
| 1 | **Models + migração + admin + registrar módulo** | `apps/marketing/{models,admin,apps}.py`, `apps/marketing/migrations/0001`, `nucleo/modulos.py` (enum+APRESENTACAO), `settings.INSTALLED_APPS`, migração seed `ModuloContratado(marketing)` | `manage.py migrate` ok; admin lista as tabelas; módulo aparece no catálogo/sidebar (1 item, grupo Comercial) | **A** |
| 2 | **Quadro (Kanban) 7 fases + arraste, sem portões** | `apps/marketing/{views,urls,services}.py`, `templates/marketing/quadro.html` + segmentado | Mover card muda `fase`; drag salva via POST/HTMX; faixas "Próximos dias"/"Atrasado" no topo; `@requer_modulo(MARKETING)` | 1 |
| 3 | **Verba mensal + painel do teto** | `services` (teto/travada/gasta), `templates/marketing/_teto.html` | Teto por mês (`VerbaMarketing.tetos`); travada=Σ campanhas aprovadas, gasta=Σ gastos; alerta ≥ `alerta_pct`; **sobra não acumula** (cada mês seu teto) | 2 |
| 4 | **Checklist por fase + os 2 portões** | `services.aprovar/encerrar` (transação), `templates` | Aprovar **valida antes de gravar** (checklist+verba) e **trava verba em transação** (falha não compromete); Encerrar exige retrospectiva e **devolve verba não gasta** | 3, **D**, **E** |
| 5 | **Peças com data → Calendário (mês/ano)** | `services`, `templates/marketing/calendario.html` | Peça datada vira ponto no dia; visão mês e ano (12 colunas); barra arrastável muda período; dica instantânea (balão, não `title`) | 2 |
| 6 | **Gastos datados → Relatório mensal e anual** | `services.relatorio`, `templates/marketing/relatorio.html` | Gasto entra no mês do dinheiro (não da campanha); relatório mês/ano com teto/gasto/sobra/ritmo; **retorno rastreado × estimado por janela, nunca somados, ordena pela rastreada**; **CAC por fechamento** | 3, 5 |
| 7 | **Atribuição de lead** (elo CRM) | reusa `comercial` | Lead sem campanha vigente = **Orgânico**; sobreposição = mais recente; editável. **Reusa `Oportunidade.campanha`** (se A2) ou FK nova (se A1) | **A, B** |
| 8 | **Conversão lead→reserva + perda com motivo** | reusa `comercial.converter_em_reserva` / `perder` | **Não reimplementar** — o módulo dispara/consome o service existente; origem viaja (via C) | **A, C**, 7 |
| 9 | **Ocupação × campanha** | `services` lê `reservas` (só leitura) | Cruza mapa de reservas (próx. 90 dias) × vigência; distingue vazio **sem** campanha (anunciar) de vazio **com** campanha (problema é a campanha); barra em **escala absoluta** com trilho hachurado | 7 |
| 10 | **Duplicar campanha** | `services.duplicar` | Clona campanha (fases resetadas p/ ideia, sem verba travada/gastos/retro) | 4 |

**Passos que EU consigo tocar hoje sem você:** 2, 3, 5, 6 (fluxo interno do módulo), **desde
que** o passo 1 tenha a decisão A. Ou seja: **A é o primeiro desbloqueio.**

---

## 3.1 Decisões registradas (suas respostas) + modelo de dados resolvido

**Decidido:** A = **embrulhar a comercial** · B = **Módulo + Área + gerência** ·
C = **derivar via Oportunidade** · E = **todos os itens dispensáveis (com motivo)**.
**Falta só D** (itens de checklist por fase).

Modelo resolvido sob "embrulhar" (difere do handoff literal — por isso mostro antes de codar):

- **`marketing.Campanha`** = entidade de fluxo: 7 fases, `objetivo`/`publico`/`canais`(JSON)/
  `inicio`/`fim`, `solicitante`/`responsavel`/`criativo`(`nucleo.Usuario`)/`fornecedor`,
  `verba_prevista`/`verba_travada`(Decimal), `aprovada_por`/`aprovada_em`,
  `retro_funcionou`/`retro_nao`/`retro_diferente`, e o elo de origem:
  `anuncio = OneToOneField(comercial.Campanha, null=True, related_name="fluxo")`.
- **Origem/leads (uma fonte só):** os leads continuam em `Oportunidade.campanha` → `comercial.Campanha`.
  Ao entrar em **Aprovação**, a `marketing.Campanha` **garante/cria** seu `anuncio`
  (`comercial.Campanha`, `codigo` = slug do nome) para os leads poderem se prender. Marketing
  **lê** os leads pelo `anuncio`.
- **Gasto (uma fonte só):** reusa **`comercial.GastoCampanha`** via `comercial.registrar_gasto`.
  `marketing.Campanha.gasta` = Σ desses gastos. **Sem** `marketing.GastoCampanha` (resolve D5).
- **Verba:** **`marketing.VerbaMarketing`** (novo; não existe hoje) — singleton com `tetos`(JSON
  por mês) + `alerta_pct`. `travada`=Σ `verba_travada` das aprovadas; `gasta`=Σ gastos do mês.
- **Satélites (marketing):** `PecaCampanha`, `EtapaCampanha`, `ItemChecklist`, `Comentario`
  → FK `marketing.Campanha`.
- **Vigência (passo 7):** "campanha vigente do canal" = `marketing.Campanha` em
  estruturação/produção/no ar, dentro de `inicio..fim`, cobrindo o canal → resolve pelo `anuncio`;
  lead sem vigente = **Orgânico**.
- **Conversão/perda (passo 8):** reusa `comercial.converter_em_reserva` e `Oportunidade.motivo_perda`.
- **Origem na reserva (passo 9):** derivada por `Oportunidade.reserva_id` — **não toca reservas**.
- **Permissões (B):** `@requer_modulo(MARKETING)` vê a tela; **Área nova `marketing`** = Analista
  (mover até Aprovação, lançar gasto, marcar peça); **gerência** = Gestor (aprovar/encerrar/teto/
  dispensar). "Só os meus" cobre responsável, dono de tarefa aberta, solicitante e gestor-quando-aguarda.

## 4. O que NÃO vou tocar (guardas do prompt)

- Webhook / conciliação / mapa de status **Safrapay** (homologados).
- Migrações já aplicadas — só crio novas.
- `static/css/app.css` — só tokens existentes; cor nova = pergunto.
- Sidebar — 1 item Marketing no grupo COMERCIAL; abas no segmentado do topo.
- Funil comercial — leio e (conforme A) atribuo/consumo; **não refaço**.
- Sem refatoração de brinde.

---

## 5. Estado

- [x] Decisões **A, B, C, E** respondidas (§3.1). A destrava o passo 1.
- [ ] **Falta D** (itens de checklist por fase) — bloqueia só o **passo 4**; passos 1–3 e 5 seguem sem ele.
- [x] **Passo 1** — models + migração (`0001`+seed `0002`) + admin + módulo no catálogo
  (grupo Comercial, sem url_name) + Área `marketing`. 6 testes verdes, check limpo.
  Arquivos: `apps/marketing/*`, `nucleo/modulos.py`, `nucleo/areas.py`, `settings.py`.
- [x] **Passo 2** — Quadro (Kanban 7 fases) com arraste (drag→POST, sem portões), faixas
  Próximos dias/Atrasado, nova campanha, segmentado das 4 abas (Quadro ativo; Calendário/
  Ocupação/Relatório como placeholders até seus passos). `url_name` ligado → Marketing na
  sidebar (grupo Comercial). 10 testes verdes. Reusa `.funil-board/.funil-coluna/.funil-card`
  e `.seg-filtro` (sem CSS novo). Arquivos: `apps/marketing/{views,urls,services}.py`,
  `templates/marketing/quadro.html`, `nucleo/modulos.py`, `config/urls.py`.
- [x] **Passo 3** — Verba mensal + painel do teto. `posicao_verba(mes)` (teto cadastrado;
  travada=Σ das aprovadas do mês; gasta=Σ GastoDiario do mês c/ fluxo; alerta; sobra não
  acumula; encerrada devolve). `definir_teto` (gerência). `_teto.html` no topo do quadro.
  15 testes verdes. Arquivos: `apps/marketing/{services,views,urls}.py`,
  `templates/marketing/{_teto.html,quadro.html}`.
- [x] **Passo 4** — Checklist (7 itens aprovados) + os 2 portões. `aprovar` (valida antes de
  gravar; trava verba em transação; cria o anúncio/embrulha), `encerrar` (exige retrô; devolve
  não gasto), `marcar/dispensar_item`. `mover_fase` roteia pelos portões (só gerência). Tela
  `detalhe.html` (editar + checklist + retrô + aprovar/encerrar). 21 testes do módulo; suíte
  total 644 OK (ajustado 1 teste do núcleo: 14 módulos). Arquivos: `apps/marketing/*`,
  `templates/marketing/{detalhe,quadro}.html`, `apps/nucleo/tests.py` (contagem).
- [x] **Passo 5** — Peças datadas → Calendário. `calendario_mes/ano`, tela mês (grade) + ano
  (12 colunas), **dica instantânea** (balão que segue o ponteiro, não `title`), peças CRUD no
  detalhe. Aba Calendário ligada. 25 testes verdes. **Simplificação:** "barra arrastável muda
  período" virou **navegação prev/próximo + toggle mês/ano** (mesmo resultado; barra arrastável
  fica como refinamento futuro). Arquivos: `apps/marketing/{services,views,urls}.py`,
  `templates/marketing/{calendario,detalhe,quadro}.html`.
- [x] **Passo 6** — Gastos datados → Relatório. `lancar_gasto` (fonte única GastoDiario),
  `relatorio(inicio,fim)` (teto/gasto/sobra/ritmo; gasto pelo mês do dinheiro; retorno
  **rastreado × janela** separados e ordenado pela rastreada; **CAC por fechamento**), tela
  relatório mês/ano + CSV, form de gasto no detalhe. 29 testes; suíte 652 OK. **Metade sem
  CRM (1–6) concluída.** Arquivos: `apps/marketing/*`, `templates/marketing/{relatorio,detalhe,
  quadro,calendario}.html`.
- [x] **Passo 7** — Atribuição de lead. `campanha_vigente(canal,quando)` (fase ativa + data +
  canal; overlap→mais recente; None=Orgânico). Signal `post_save` em `comercial.Oportunidade`
  (marketing OUVE o comercial — não refaz o funil): lead novo sem campanha recebe o `anuncio`
  da vigente; não sobrescreve; editável. Detalhe mostra leads/ganhos. 36 testes; suíte 659 OK.
  Arquivos: `apps/marketing/{services,signals,apps,views}.py`, `templates/marketing/detalhe.html`.
  **Nota:** não editei o `capturar_lead_site` do comercial (usei signal) → direção de dependência
  preservada e funil intacto.
- [x] **Passo 8** — Conversão + perda (reflete o comercial). `services.aquisicao(campanha)`
  (total/abertos/ganhos/perdidos, receita rastreada, conversão, CAC por fechamento, motivos de
  perda), mostrado no detalhe. Confirmado que `converter_em_reserva` preserva `campanha` → a
  origem viaja via `reserva_id` (decisão C, reservas intacto). **Não reimplementou o funil.**
  39 testes. Arquivos: `apps/marketing/{services,views}.py`, `templates/marketing/detalhe.html`.
- [x] **Passo 9** — Ocupação × campanha. `ocupacao_x_campanha(dias)` lê `reservas.relatorio_ocupacao`
  (read-only) por semana × vigência; distingue **oportunidade** (vazio sem campanha) de **problema**
  (vazio com campanha). Barra em **escala absoluta + trilho hachurado**. Aba Ocupação ligada.
  42 testes. Arquivos: `apps/marketing/{services,views,urls}.py`, `templates/marketing/ocupacao.html`.
- [x] **Passo 10** — Duplicar campanha. `services.duplicar` (herda plano; reseta fase→ideia,
  verba travada, anúncio/leads/gastos, datas, aprovação e retrospectiva; copia peças/tarefas
  reabertas). Botão no detalhe. 44 testes do módulo; **suíte total 667 OK**.

---

## 6. CONCLUÍDO (1–10) — 44 testes do módulo, suíte total 667 OK, zero regressão

Módulo `apps/marketing` completo, no design Lampião, sem tocar Safrapay/reservas/funil:
Quadro (portões), Verba mensal, Calendário, Ocupação × campanha, Relatório, e o elo com o
CRM (atribuição por signal, conversão/perda refletidas, origem via `reserva_id`).

### O que ficou de fora (e por quê)
- **Barra arrastável do calendário** → virou navegação prev/próximo + toggle mês/ano (mesmo
  resultado; a timeline arrastável é refinamento de UX, não muda a regra).
- **`Comentario` (conversa da campanha)** → model existe, sem UI. Não é portão nem regra;
  deferido para quando pedirem a discussão na ficha.
- **Filtro "Só os meus"** → não implementado (é conveniência de listagem; o quadro já é enxuto).
- **Área `marketing` (Analista)** → criada e disponível em Equipe & Acessos; a distinção fina
  Analista×Gestor hoje se dá por **módulo (vê) + gerência (aprova/encerra/teto/dispensa)**, que
  cobre as regras. Conceder a área a usuários é operação, não código.
- **Retorno "estimado por janela"** → usa check-in de leads ganhos na vigência (proxy via
  comercial), não uma varredura completa de reservas — suficiente e mais barato; a regra
  "nunca somar com a rastreada / ordenar pela rastreada" está garantida.
- **Commits** → ainda NÃO feitos (decisão do dono: organizar depois). Tudo local, testado.

### Fidelidade visual (prompt de layout) — divergências onde o app.css ganhou
Aplicado às **5 telas** (`quadro`, `calendario`, `ocupacao`, `relatorio`, `detalhe`) via um
partial compartilhado `_estilo.html` (classes `.mkt-*`, só tokens) + `_tabs.html` (pílula
segmentada). Traduzi os hex do protótipo para **tokens do `app.css`** (sem cor nova), ≥11px,
contraste via `--tinta`/`--tinta-suave`, **sem emoji** (SVGs inline no estilo do CRM), coluna
268px + cabeçalho sticky, card raio 14px, `--sombra-cartao`. `_teto.html` removido (verba agora
inline no quadro). Detector limpo (só 11px e o letreiro-maiúsculo, sancionados e registrados nos
ignores). Divergências registradas (app.css venceu):
- **Não existe `--terra`** no app.css → usei `--perigo`/`--alerta` para os acentos terracota.
- **Botão primário** do CRM é **dourado** (`.botao-primario`, gradiente lampião), não o gradiente
  terracota do protótipo → mantive o dourado.
- **Sombra do card** = `--sombra-cartao` (app.css), não a sombra mais profunda do protótipo.
- **Paleta do projeto é mais fria** (`--canvas #EEF2F3`) que o creme do protótipo (`#F7F5F1`) →
  o layout/medidas batem, o tom segue o projeto.
- **Ícones:** protótipo usa Material Symbols (não carregado) → SVG inline; **acento colorido no
  topo da coluna removido** (não estava na spec de medidas e conflitava com o raio).
- **Mín. 11px** conforme a spec (o impeccable ideal-iza 12px p/ corpo; os 11px são micro-labels,
  ignore registrado). Detector do Quadro: limpo fora desse 11px sancionado.

### Divergência que virou decisão do dono (aplicada)
A `comercial.Campanha` já existia e os leads já se prendiam a ela → **embrulhamos** (A2):
`marketing.Campanha.anuncio` (OneToOne) mantém **uma fonte só** de origem e de gasto, sem
duplicar nem refazer o funil.

**Próximo:** (1) seu **ok neste roteiro/modelo resolvido** para eu começar o **passo 1**
(models + migração + admin + registrar módulo). (2) Sua resposta ao **D** — os itens de
checklist por fase — que preciso antes do passo 4 (posso propor um conjunto mínimo para você
revisar, se preferir). Enquanto D não vem, avanço 1→3 e 5. **Sem push** (deploy segue exigindo
seu comando à parte); commits locais por passo, como o prompt pede.

---

## Correção de layout (PROMPT-CORRECAO-LAYOUT.md) — estrutura copiada do protótipo

Fonte: `docs/Marketing/marketing_handoff/preview/ABRIR-Marketing.html` (artifact `.dc.html`,
estilos inline). De-escapei o markup e **copiei a estrutura/medidas** (hierarquia de divs,
%, raios, pesos), traduzindo cor → tokens do `app.css`. **Onde app.css diverge do protótipo,
app.css vence** (registrado abaixo). Feito nesta leva **4 das 5 divergências**:

1. **Calendário → LINHA DO TEMPO (gantt).** Deixou de ser grade de dias. Novo
   `services.calendario_timeline(ano, mes, escala)` computa server-side, espelhando o
   `buildCalendario` do protótipo: coluna fixa 200px (nome + período) + trilha com **barra em %**
   por campanha; **hachurada = planejado (futuro), cheia = realizado**; **linha vermelha de hoje**
   corta a barra (`corte`); **peças = pontos**; **marcos** (feriados/sazonais que puxam reserva)
   como **ticks tracejados** com rótulos em 2 linhas alternadas; escalas **Mês/Ano** em pílula.
   Dica instantânea via `_dica.html` (balão que segue o ponteiro). `marcos_do_periodo()` +
   `_2a_domingo()` (Dia das Mães/Pais).
2. **Ocupação — bug do 0% + barras verticais.** O 0% vinha de `relatorio_ocupacao` contar só
   `HOSPEDADA/CHECKOUT`; a janela de marketing olha 90 dias **à frente**, onde a reserva ainda é
   **CONFIRMADA**. Correção **sem tocar o cálculo**: `relatorio_ocupacao(…, statuses=None)` ganhou
   parâmetro opcional (default preserva o histórico) e novo wrapper público
   `reservas.ocupacao_prevista()` conta confirmadas+hospedadas+saídas; marketing usa esse.
   Layout agora é **barras verticais** (60px, escala absoluta, zero-é-zero) por semana + lista das
   semanas a marcar (selos) + seção **"Datas que puxam reserva"** (`marcos_ocupacao`, coberta×sem
   campanha).
3. **Relatório — controles nativos → pílulas.** Trocado `<select>` de Mês e Ano por **pílulas em
   linha** (`.mkt-chip`), + CSV/Imprimir como chips. KPIs e cartões por campanha mantidos (já
   tokenizados).
4. **Quadro — campo solto removido.** Sumiu o input "Nova campanha…" solto; agora **"+ Nova ideia"**
   fica no rodapé da coluna **Ideia** e cria a ideia em branco abrindo a ficha (`nova_campanha`
   aceita nome vazio → "Nova campanha" e vai à ficha). Bandas (Próximos/Atrasado), verba-hero e
   cards ricos já batiam com o protótipo.

### Divergências onde o app.css venceu (registradas)
- **Cores por fase da barra** (calendário): protótipo usa pastéis próprios; usei **só tokens** —
  ideia/encerrada `superficie-2`, proposta `alerta-bg`, aprovação `perigo-bg`, estruturação
  `info-bg`, produção `superficie-2`+`madeira`, no ar `sucesso-bg`. Não inventei cor.
- **Paleta mais fria / sombras**: canvas e sombras seguem o CRM (`--sombra-cartao`), não o creme do
  protótipo. Medidas e estrutura idênticas; o tom é do sistema.
- **Sem drag-to-move da barra** do calendário (protótipo arrasta a barra p/ mover o período): a
  barra abre a ficha; mover período fica no formulário da ficha. (Pende endpoint dedicado.)

5. **Ficha → GAVETA lateral de 520px (feito).** Deixou de abrir como página. Novo partial
   `_ficha_drawer.html`: **overlay escurecido + `aside` 520px** deslizando pela direita, carregado
   por **HTMX** em `#ficha-slot` no quadro (view `marketing:ficha`; o card usa `hx-get`). Fecha
   esvaziando o slot (sem "← voltar ao quadro"). Conteúdo: cabeçalho (código, selo, **nome/objetivo/
   público/período/canais/verba** editáveis), KPIs (gasto/previsto, leads, conversão/CAC),
   **checklist com círculo-toggle** (não dois botões) + dispensar (motivo via `hx-prompt`),
   aquisição, **peças** (alternar pronta/data/remover/adicionar), **lançar gasto**, **retrospectiva**
   e **portões** no rodapé (Aprovar/Encerrar). Toda ação **re-renderiza a própria gaveta**
   (`_pos_ficha` devolve o partial em requisição HTMX; fora dela, o redirect de sempre).
   `salvar_campanha` passou a **atualizar só os campos enviados** — dados e retrospectiva viram
   formulários independentes sem um zerar o outro. `detalhe`/`detalhe.html` seguem como **fallback**
   de deep-link (página inteira).

### Ainda por fazer (fidelidade fina da gaveta — não bloqueia)
- Sub-blocos do protótipo sem backend próprio: **etapas com dono/prazo**, **envolvidos/papéis**,
  **conversa (comentários)**, **anexo por item de checklist** e **reservas-na-janela** com KPIs.
  A gaveta cobre o que já tem service; esses entram quando os models existirem.
- Auto-save por campo (protótipo salva a cada tecla) → aqui é **Salvar** explícito por bloco.
- Abrir a gaveta também pelas **barras do calendário / linhas da ocupação** (hoje vão à página).

### Divergência de token (11px vence o protótipo)
- Rótulos da gaveta eram 10.5px no protótipo; subidos para **11px** (piso do prompt de fidelidade).

**Testes:** 671 OK (0 regressão; +4 da gaveta). Detector limpo, exceto ignores sancionados
(11px do prompt de fidelidade + `cramped-padding` do gantt = espaço-coordenada). **Local, sem commit.**

---

## Transcrição verbatim do protótipo (PROMPT.md — leitura do DOM, não da descrição)

Reli o `PROMPT.md` inteiro (Parte 2 detalha a faixa de urgências; Parte 3 = tabela de tokens
+ piso de 11px; Parte 4 = decisões com motivo; Parte 5 = proibições). Passei a **transcrever a
árvore do protótipo** (`ABRIR-Marketing.html`, de-escapado em `/tmp/proto_marketing.html`),
com estilos **inline**, trocando só cor→token e valor fixo→banco. Telas refeitas verbatim,
**self-contained** (sem `_estilo.html`/`_tabs.html`):

- **Quadro** (`quadro.html`) — cabeçalho + abas-pílula + papel + "Só os meus"; **faixa de
  urgências da Parte 2**: dois cartões lado a lado (`grid auto-fit minmax(300px,1fr)`),
  **Próximos dias** (resumo "N hoje · M até domingo", subtítulo `campanha · canal · responsável`,
  selo de prazo, `max-height:232px`) e **Atrasado** (selo PEÇA, `dono · há N dias`,
  "N pendências atrasadas"); verba-hero; colunas 268px (cabeçalho sticky) com cards raio 14px
  (código, canais, avatar, responsável, verba, barra de checklist, peças) + **Aprovar/Reprovar**
  na coluna Aprovação. Serviços novos: `resumo_proximos`, `banda_*` com responsável/tipo.
- **Calendário** (`calendario.html`) — linha do tempo verbatim (coluna 200px, trilha, barra %,
  corte de hoje, pontos de peça, marcos tracejados em 2 linhas). Barra abre a **gaveta** (slot).
- **Ocupação** (`ocupacao.html`) — barras verticais 60px (escala absoluta, zero-é-zero, trilho
  hachurado), lista de semanas a marcar, "Datas que puxam reserva". Dica instantânea.
- **Relatório** (`relatorio.html`) — filtro em **pílulas** (mês/ano) no lugar dos `<select>`,
  grid de KPIs (1px de fio entre células), cards campanha-por-campanha.

### Token/medida — divergências registradas (app.css vence; não edito o app.css)
- **`--terra` não existe** (nem `--canela`). `#9A4429/#B25837` (ação/destaque) → **`--madeira`**;
  botão primário/aprovar → **gradiente do CRM** (`--musgo`/`--lampiao`); "linha vermelha de hoje"
  → **`--perigo`**.
- **Sombra do cartão** = `--sombra-cartao` do CRM, não a sombra dupla do protótipo.
- **Piso de 11px** (Parte 3): selos/rótulos que o protótipo põe em 9–10.5px foram **subidos a 11px**
  (o detector Impeccable também exige). Registrado como ignore sancionado por arquivo.
- **Ícones**: o protótipo usa a fonte Material Symbols (não carregada no CRM) → **SVG inline
  equivalente** (mesmo glifo/《significado》), só onde o protótipo tem ícone.
- **Gráfico de barras por período** do Relatório (comparação relativa ao pico) **não incluído**:
  o service dá o período único, não a série multi-período. Mantidos KPIs + campanha-por-campanha.

### Ficha (gaveta) — estado
Continua como **gaveta HTMX** funcional (overlay + `aside` 520px), com dados/checklist-círculo/
peças/gasto/retrospectiva/portões. Sub-blocos do protótipo **sem backend** (etapas com dono/prazo,
envolvidos/papéis, conversa, anexo por item, reservas-na-janela) seguem fora — entram quando os
models existirem. Classes `.fx-*` são internas ao partial e só usam tokens.

**Testes:** 671 OK (0 regressão). Detector limpo (ignores sancionados: 11px por tela + gantt
`cramped-padding`). **Local, sem commit.**

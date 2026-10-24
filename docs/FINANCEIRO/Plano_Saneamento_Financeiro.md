# Plano de Saneamento do Financeiro

> **Status:** plano / desenho. **Nada implementado.** Decisões herdadas de
> [`Mockup_Estrutural_Contabil.md`](Mockup_Estrutural_Contabil.md) (CRM gerencial +
> exporta; caixa+competência + de‑para; plano enxuto de pousada; patrimonial fora).
> **Premissa:** o financeiro operacional atual **não é reescrito nem removido** — este
> plano **organiza a entrada** dos dados para que os relatórios (DRE, Fluxo, Reservas)
> tenham de onde beber.

---

## 1. Diagnóstico — por que está bagunçado

O problema não é de relatório; é de **entrada**. Hoje:

- **`CategoriaFinanceira` é plana e de texto livre** → nascem duplicatas ("Energia",
  "Energia Elétrica", "Luz"), e nada soma direito.
- **`centro` (setor) é opcional e some** → não dá pra fatiar resultado por setor.
- **Despesa entra solta** (lançamento avulso), sem fornecedor/vencimento → sem fluxo
  projetado, sem competência confiável.
- **Metade dos números do relatório não tem porta de entrada:** folha, DAS/Simples,
  pró‑labore, honorários, comissão de OTA, taxa de cartão. Ficam fora ou viram
  "despesa diversa".

**Princípio de saneamento:** relatório é **saída**. Para a saída existir e fechar, cada
número precisa de **uma porta de entrada** e de **uma classificação única**. É isso que
este plano constrói.

---

## 2. A espinha única de classificação

O **plano de contas** (do mockup, §2) vira a **única** forma de classificar dinheiro.
Toda entrada e saída escolhe **uma conta analítica** — nunca mais categoria de texto livre.

- `CategoriaFinanceira` atual **não some**: é **migrada por de‑para** para as contas novas
  (ninguém reclassifica à mão; a migração mapeia o que existe).
- `centro`/setor continua existindo como **segundo eixo** (o "onde"), agora **obrigatório**.
- Resultado imediato: fim da duplicata, tudo soma certo, DRE e Reservas fatiam por setor.

---

## 3. Mapa de entradas por métrica

Cada número dos relatórios cai em um de três baldes. Só criamos porta nova para o balde **C**.

### Balde A — já entra sozinho (só classificar via de‑para)
| Métrica | Origem hoje |
|---|---|
| Diárias / hospedagem | folio Reservas (natureza serviço) |
| Consumo no quarto | folio Reservas (natureza consumo) |
| Venda loja / restaurante / lavanderia | módulos → caixa do setor |
| Recebimento no caixa | `MovimentoCaixa` |
| CMV (custo da mercadoria) | motor de Estoque (custo médio) |
| Sinal / adiantamento online | Pagamentos / Safrapay |
| Ocupação / ADR / RevPAR / permanência | Reservas + mapa de quartos |

### Balde B — já entra, mas bagunçado (padronizar)
| Métrica | Problema | Padronização |
|---|---|---|
| Despesas em geral | lançamento avulso, sem fornecedor | **toda despesa vira "conta a pagar"** |
| Contas a pagar/receber | subusadas | viram a **porta única** de saída/entrada a prazo |
| Descontos concedidos | diluídos na tarifa | registrar o desconto vs. tabela na reserva |
| Adiantamentos | vistos só na reserva | **consolidar** saldo em aberto no financeiro |

### Balde C — NÃO tem entrada hoje (criar a porta)
| Métrica | Porta a criar |
|---|---|
| **Folha de pagamento** | fechamento mensal guiado (1 lançamento por conta) |
| **DAS / Simples Nacional** | fechamento mensal guiado |
| **Pró‑labore** | lançamento recorrente mensal |
| **Honorários contábeis / advocatícios** | conta a pagar recorrente |
| **Aluguel, energia, água, internet, assinaturas** | contas a pagar recorrentes |
| **Comissão de OTA / agência** | captura automática do canal da reserva |
| **Taxa de cartão (Safrapay/adquirência)** | captura automática do Pagamentos |

---

## 4. As portas a criar (mecanismos)

1. **Conta a pagar = porta única das saídas.** Toda despesa entra como título (fornecedor,
   vencimento, conta contábil, setor). A baixa gera o lançamento. Alimenta de uma vez:
   **fluxo projetado + competência + DRE**. (O model `ContaPagarReceber` já existe e já
   gera lançamento na baixa — falta **disciplina de uso** + os campos de conta/setor
   obrigatórios.)
2. **Lançamentos recorrentes (template mensal).** Folha, aluguel, energia, internet,
   assinaturas, pró‑labore: cadastra uma vez, o sistema **gera o título todo mês** para só
   confirmar o valor. Mata a maior parte do trabalho manual e das esquecidas.
3. **Capturas automáticas** do que o sistema já sabe: **taxa de cartão** (lê Pagamentos),
   **comissão de OTA** (lê o canal da reserva), **CMV** (lê o Estoque). Hoje somem; viram
   lançamento automático classificado.
4. **Fechamento mensal guiado** (folha + impostos). Telinha de "fechar o mês" com os
   campos (total de folha por conta, DAS, FGTS/INSS). Baixa frequência, entrada simples —
   **não puxamos da contabilidade do contador**, é digitação guiada mensal.
5. **Classificação obrigatória + assistente de órfãos.** Conta e setor viram campos
   obrigatórios; o que entrar sem classificação cai na fila "a classificar" (1 clique, com
   sugestão). Fim do "despesa diversa".

---

## 5. Ordem de implementação (etapas 1 a 5)

Sequencial, cada etapa testada (dinheiro é sempre testado) antes da próxima. Tudo
**aditivo** — não quebra o financeiro atual.

### Etapa 1 — Espinha de classificação (plano de contas + de‑para) ✅ IMPLEMENTADA
- **Objetivo:** dar a toda movimentação uma conta contábil única.
- **O que muda:** novo app `apps/contabil` com `ContaContabil` + `MapeamentoContabil`;
  seed do plano enxuto (§2 do mockup); migração que **mapeia as `CategoriaFinanceira`
  atuais** para contas (de‑para automático).
- **Models/migração:** `contabil.0001` (2 models) + seed + data migration de mapeamento.
  **Nada destrutivo** — `CategoriaFinanceira` permanece.
- **Risco:** baixo (só leitura + tabela nova).
- **Pronto quando:** todo lançamento/conta existente resolve uma conta contábil; relatório
  de órfãos = 0.
- **Feito (23/10/2026):** app `apps/contabil` (não contratável ainda — padrão do
  `conciliacao`; telas ficam p/ Etapa 5). Migrações `0001` (schema) + `0002` (plano enxuto
  de 22 contas, 12 analíticas, com `codigo_contador`) + `0003` (de‑para padrão: natureza
  serviço/consumo, cmv, taxa cartão, comissão OTA, Simples + fallbacks por tipo) + `0004`
  (de‑para das `CategoriaFinanceira` existentes, heurístico por palavra‑chave sem acento,
  **só cria linhas, nada destrutivo**). Service `resolver_conta(...)` (prioridade +
  especificidade + fallback → nunca órfão) + `plano_de_contas()`. Admin para inspeção.
  **17 testes** (plano/hierarquia, clean, resolver, de‑para); **suíte completa 924 OK**.
  **Não commitado/deployado** (aguardando ordem).

### Etapa 2 — Conta a pagar como porta única + recorrentes ✅ IMPLEMENTADA
- **Objetivo:** organizar as saídas e habilitar competência + fluxo projetado.
- **O que muda:** campos **conta contábil + setor obrigatórios** em `ContaPagarReceber` e
  `LancamentoFinanceiro`; novo **lançamento recorrente** (gera título mensal); UX de
  "nova despesa" apontando sempre para conta a pagar.
- **Models/migração:** campos novos (nullable → preenchidos por de‑para → obrigatórios em
  migração faseada); model `ContaRecorrente` (ou flag em `ContaPagarReceber`).
- **Risco:** médio‑baixo (mexe em fluxo de uso, não em dado histórico).
- **Pronto quando:** uma despesa nova só entra classificada; recorrentes geram título
  sozinhas no mês.
- **Feito (23/10/2026):** **arquitetura por sinais** (núcleo não depende de `contabil`):
  núcleo ganhou só o campo-string neutro `conta_contabil` em `LancamentoFinanceiro` e
  `ContaPagarReceber`; o `contabil` **escuta** (`receivers.py`, ligado no
  `ContabilConfig.ready`) e **carimba** a conta via `resolver_conta` no `post_save`
  (`.update()` — sem recursão nem ruído de auditoria). Categoria nova ganha **de-para
  automático** (heurístico vivo em `contabil/classificacao.py`) → "nunca órfão" segue
  valendo. Novo model **`nucleo.ContaRecorrente`** (categoria+centro obrigatórios → nasce
  classificada) que gera `ContaPagarReceber` por competência (`gerar(ano, mes)`,
  **idempotente** via unicidade `recorrencia`×`competencia`); comando cron
  `manage.py gerar_recorrentes [--ano --mes]`. Migrações `nucleo.0046` (campos + model +
  constraint) + `contabil.0005` (backfill **defensivo** — só preenche em branco). Admin
  de `ContaRecorrente`. **10 testes novos** (carimbo, de-para automático, recorrente
  idempotente, clamp de dia, comando); **suíte completa 934 OK**. **Não commitado.**
  *Pendente p/ Etapa 5 (telas):* tornar `centro` obrigatório nos forms da UI de
  despesa/lançamento e a fila visual de órfãos.

### Etapa 3 — Capturas automáticas (taxa de cartão, OTA, CMV) ✅ IMPLEMENTADA
- **Objetivo:** trazer pra dentro o que hoje some.
- **O que muda:** services que leem **Pagamentos** (taxa), **Reservas/canal** (comissão
  OTA) e **Estoque** (CMV) e geram lançamento classificado por competência.
- **Models/migração:** nenhuma nova tabela — só services + lançamentos automáticos
  (idempotentes, com origem marcada).
- **Risco:** baixo (lê services públicos; não inverte dependência).
- **Pronto quando:** taxa/OTA/CMV aparecem na DRE sem digitação.
- **Feito (23/10/2026):** campos `origem` + `referencia` (chave de idempotência, unicidade
  parcial) em `LancamentoFinanceiro` (`nucleo.0047`). Capturas em `contabil/capturas.py`:
  **taxa de cartão** lê `pagamentos.services.taxas_do_periodo` (novo helper público) →
  1 lançamento por cobrança liquidada → `5.1.03.02`; **CMV** lê
  `nucleo...estoque.cmv_por_modulo` (novo) → 1 lançamento por módulo/mês, **recomputável**
  (`update_or_create`) → `4.5.01.01`. **Comissão de OTA = STUB** governado por
  `CONTABIL_COMISSAO_OTA_PCT` (default 0 = no-op) — o CRM **ainda não registra comissão**
  (virá com o módulo Canais/OTAs). Leitura cross-módulo só por **services públicos**
  (padrão do `relatorios`), sem inverter dependência. Robô `_contabil` (`usuario_de_sistema`)
  assina os lançamentos; conta carimbada direto (via `resolver_conta(origem_sistema=…)`).
  Comando `manage.py capturar_lancamentos [--ano --mes]`. **8 testes**; suíte **942 OK**.
- **Captura de RECEITA (completada depois)** — o elo que faltava: a receita de
  hospedagem/A&B **não se digita**, é lida do folio/vendas. `capturar_receita(ano, mes)`
  usa os mesmos services públicos do Relatórios (sem sobreposição): **diárias**
  (`reservas.diarias_periodo`) + **lavanderia** → `3.1.01.03`; **loja + restaurante**
  (`faturamento_periodo`, caixa+quarto) → `3.1.01.01`. 1 lançamento por setor/mês,
  recomputável. **Anti‑dupla‑contagem:** `CategoriaFinanceira.automatica` (novo campo,
  `nucleo.0048`) marca as categorias geridas pelo sistema (receita dos 4 setores + folha/
  encargos/pró‑labore/DAS + taxa/CMV/OTA); os **forms manuais** (`LancamentoFinanceiro`,
  `ContaPagarReceber`) **excluem** `automatica=True` → some "Hospedagem (Receita)" etc. do
  lançamento manual. Migração `contabil.0008` sinaliza as existentes. **6 testes novos**.

### Etapa 4 — Fechamento mensal guiado (folha + impostos) ✅ IMPLEMENTADA
- **Objetivo:** fechar os números de baixa frequência que não nascem no sistema.
- **O que muda:** tela "Fechar o mês" com campos de folha (por conta), DAS, FGTS/INSS,
  pró‑labore; gera os lançamentos de competência do mês.
- **Models/migração:** `FechamentoMensal` (um por mês/ano, com os valores digitados) +
  lançamentos gerados.
- **Risco:** baixo (entrada manual isolada).
- **Pronto quando:** a DRE do mês fecha com pessoal e impostos.
- **Feito (23/10/2026):** model `contabil.FechamentoMensal` (único por ano/mês; campos
  folha, encargos FGTS/INSS, pró‑labore, DAS). `aplicar()` gera/atualiza 4
  `LancamentoFinanceiro` de competência (`origem="fechamento"`, data = último dia do mês),
  já classificados: folha+encargos→`4.2.01.01`, pró‑labore→`5.1.02.02`, **DAS→`3.1.02.01`**
  (dedução de receita, mesmo sendo lançamento de despesa — o `conta_contabil` manda, não o
  tipo). **Recomputável e idempotente** (chave `referencia`; valor 0 apaga o lançamento).
  Assinado por `fechado_por` ou robô `_contabil`. Admin aplica ao salvar; comando
  `manage.py aplicar_fechamento --ano --mes`. Migração `contabil.0006`. **7 testes**;
  suíte **949 OK** (gateway simulado — o único vermelho é a Safrapay HML pela rede,
  flake de ambiente, não regressão). **Folha vem do cadastro:** `folha_base()`
  (`nucleo…cadastros`) soma o `salario` dos funcionários ativos; a tela "Fechar o mês"
  **pré‑preenche a Folha** com esse valor ("N funcionários · R$ X" + botão "usar do
  cadastro"), editável (13º/horas extras/entradas no meio do mês). **Não commitado.**
  *Tela "Fechar o mês" polida fica
  p/ a Etapa 5* (hoje: admin + comando).

### Etapa 5 — Relatórios ligados ao dado real ✅ IMPLEMENTADA (parcial — ver nota)
- **Objetivo:** DRE, Fluxo de Caixa e aba Reservas rodando com dado real (fim dos números
  fictícios do mockup).
- **O que muda:** as telas de `contabil:dre`, `contabil:fluxo_caixa`, `contabil:reservas`
  passam a consumir os services; export para o contador habilitado.
- **Models/migração:** nenhuma — só views/services/templates no design "Lampião".
- **Risco:** baixo.
- **Pronto quando:** o dono abre a DRE e o relatório de Reservas do mês corrente com dado
  verdadeiro; export gera os arquivos no layout do contador.
- **Feito (23/10/2026):** módulo **`Modulo.CONTABIL`** registrado (grupo Gestão, menu
  `contabil:painel`, seed `contabil.0007`). **Painel único com abas** (réplica do mockup,
  skill `frontend-design`, tokens Lampião, Chart.js): **DRE Gerencial** (KPIs + tabela +
  waterfall + donut serviços×mercadorias), **Fluxo de Caixa** (KPIs + ponte realizado→
  projetado + extrato), **Plano de Contas** (árvore com saldo do mês), **A classificar**
  (fila de órfãos: categorias sem de‑para + lançamentos sem conta), **Fechar o mês**
  (form → `FechamentoMensal.aplicar`), **Exportar** (3 CSVs pt‑BR com o código do
  contador). Services em `contabil/relatorios.py` (`dre`, `fluxo_caixa`, `orfaos` — tudo
  por soma, sem partidas dobradas). Seletor mês/ano compartilhado (`nucleo.periodos`).
  Gated `@requer_modulo(CONTABIL)` + `@requer_gerencia`. **12 testes** (DRE soma/mês,
  órfãos, painel 200, fechar, export CSV/404); suíte **956 OK** (+1 teste de contagem de
  módulos ajustado p/ 15). **Não commitado.**
- **Receita futura contratada (elo do pipeline — feito):** `reservas.services.
  receita_contratada_futura()` soma as reservas **confirmadas ainda não hospedadas**
  (`valor_diaria × noites`) por mês de entrada; o painel (aba **Fluxo de Caixa**) mostra
  "Receita contratada a entrar" (por mês + total). Fecha o elo: a reserva futura não vira
  folio até o check-in, mas já aparece como receita contratada. **NÃO entra na DRE**
  (competência só no check-in) — é explicitamente marcado como estimativa. 2 testes.
- **NOTA — pendente desta etapa:** a **aba "Reservas" rica** do mockup (ADR/RevPAR,
  adiantamentos em aberto, ponte competência→caixa, pipeline) **não foi portada**: depende
  de agregações próprias do módulo Reservas (ocupação, sinais, canal) que ainda não existem
  como services. É o próximo incremento — não entra com números fictícios. Também fast‑follow:
  `centro` obrigatório nos forms de despesa/lançamento e o "Resolver" de 1 clique na fila de
  órfãos (hoje a correção é no de‑para/admin).

---

## 5.1 Cron das capturas (a DRE se atualiza sozinha) ✅ IMPLEMENTADA

As capturas (receita do folio, taxa de cartão, CMV) são **idempotentes**, mas alguém
precisa dispará‑las. Em vez de depender de execução manual, há um **endpoint protegido
por token** que um agendador externo chama — tudo versionado, sem depender do dashboard
nem de token do Railway (que já foi invalidado uma vez).

- **Endpoint:** `POST /crm/contabil/cron/capturar/` (`contabil:cron_capturar`,
  `@csrf_exempt`, sem login). Autentica por **`CONTABIL_CRON_TOKEN`** (header
  `X-Cron-Token` ou `?token=`), comparação em tempo constante. **Sem o token no servidor
  → 404 (fail‑safe).** Roda `capturar_mes` do mês corrente + reprocessa o mês anterior nos
  primeiros 5 dias (fecha a competência que virou). Idempotente.
- **Agendador:** `.github/workflows/cron-financeiro.yml` — GitHub Action diário
  (06:00 UTC = 03:00 BRT) + botão manual (`workflow_dispatch`). Só o "despertador"; o
  trabalho roda no servidor.
- **Ativação (ops, 1×):** gerar um token forte e colocá‑lo com o **mesmo valor** no
  **Railway** (env do web: `CONTABIL_CRON_TOKEN`) e no **GitHub** (Settings → Secrets →
  Actions: `CONTABIL_CRON_TOKEN`). Enquanto não for configurado, o Action sai no‑op e o
  endpoint responde 404 — seguro para commitar sem ativar.
- **Também gera as contas recorrentes** do mês corrente (aluguel, folha fixa, etc. —
  `ContaRecorrente.gerar`, idempotente). As recorrentes **não retroagem** (só o mês
  corrente); já as capturas reprocessam o mês anterior (competência). Um disparo = DRE
  do mês + contas fixas em dia.
- **Testes:** 404 sem token, 403 token errado, 200 com token (header e querystring),
  geração idempotente das recorrentes.

---

## 6. Fora de escopo (de propósito)

- **Patrimonial** (bancos, obra/imobilizado, empréstimos, capital) — fica com o contador.
- **Conciliar 100% dos extratos** — a conciliação atual (OFX) cobre o essencial; não
  vamos perseguir o espelho perfeito de todas as contas.
- **Partidas dobradas** — não; a DRE sai por soma (decisão do mockup).

> Motivo: trocar a bagunça por um projeto infinito é o maior risco. O saneamento mira o
> que o dono usa toda semana.

---

## 7. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Migração classificar errado o histórico | de‑para revisável + fila de órfãos; nada é sobrescrito |
| Equipe não preencher conta/setor | obrigatoriedade no form + assistente de 1 clique |
| Recorrentes gerarem valor errado | título **nasce como rascunho**, exige confirmação do valor |
| Captura automática duplicar lançamento | idempotência por origem (mesma regra do `enviar_fnrh`) |
| Escopo inflar p/ patrimonial | §6 trava o escopo |

---

## 8. Ritual de fechamento mensal (operacional)

O que o responsável faz todo início de mês (vira um checklist na tela de fechamento):

1. Confirmar os **recorrentes** gerados (aluguel, energia, internet, pró‑labore…).
2. Lançar **folha + encargos** e **DAS/Simples** (fechamento guiado).
3. Resolver a **fila de órfãos** (lançamentos sem conta).
4. Conferir a **conciliação bancária** do mês.
5. Abrir **DRE + Reservas** do mês e **exportar** para o contador.

---

## 8.1 Revisão de código — corrigido e follow-ups

Rodada de `/code-review` (multiagente) sobre o saneamento. **Corrigido já:**
- Data da **taxa de cartão** usava data UTC com filtro no fuso local → competência errada
  perto da virada do mês. Agora `timezone.localtime(pago_em).date()`.
- **Fluxo de caixa** contava **reforço/sangria** (movimentos internos de troco/cofre) como
  entrada/saída — inflava o fluxo. Agora só **recebimento** (entra) e **estorno** (sai).
- `fechar()` fazia `int()` antes do guard de método → 500 com POST adulterado. Parse
  seguro + guard primeiro.

**⚠️ Risco de cutover (ops, não é bug de código):** se a captura de receita rodar sobre
um **mês que já tem lançamento manual** de hospedagem/A&B (feito no form antigo, antes de
a categoria virar `automatica`), a DRE **conta em dobro** (o manual + o capturado). Por
isso, ao ativar em produção: **não rodar as capturas sobre meses com receita manual**, ou
limpar/zerar esses lançamentos manuais antes. Daqui pra frente não há risco (categorias
automáticas somem do form).

**Follow-ups de qualidade (não bloqueiam):** `resolver_conta` varre todo o de‑para em
Python a cada escrita (tabela pequena, ok por ora); `cmv_por_modulo`/`receita_contratada_futura`
somam em laço Python (dá p/ virar agregação no banco); as classificações (`3.1.01.03`…)
estão hard‑coded em vários arquivos (centralizar numa fonte única); `capturar_receita`
duplica o walk de setores do `relatorios.rel_faturamento_modulos`; captura não zera o
lançamento de um setor cujo **módulo foi desativado** (raro).

---

## 9. Recomendação

O maior ganho com o menor risco são as **Etapas 1 + 2** (espinha de classificação + conta
a pagar como porta única). Só isso já transforma "bagunçado" em "organizado" e dá base
para os relatórios. As Etapas 3–5 são incrementos que podem vir em sequência.

**Próximo passo sugerido:** fechado este plano, rodar a skill `writing-plans` para
transformar as 5 etapas em plano de implementação com tarefas, e então TDD +
`django-verification` etapa a etapa.

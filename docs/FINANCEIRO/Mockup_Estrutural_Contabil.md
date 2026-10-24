# Mockup estrutural — Camada Contábil/Gerencial do Financeiro

> **Status:** proposta / mockup. **Nada implementado.** Documento de desenho para
> validação antes de qualquer código.
> **Decisões de escopo (validadas com o usuário em 23/10/2026):**
> 1. **Papel do CRM:** gerencial + **exporta** para o contador (a contabilidade
>    oficial segue no software dele).
> 2. **Mecânica:** mantém o modelo atual (caixa + competência) e adiciona uma
>    **camada de de‑para** categoria→plano de contas. **Sem partidas dobradas.**
> 3. **Plano de contas:** **enxuto de pousada** (podado do template genérico que ele mandou).
> 4. **Patrimonial** (bancos, imobilizado, empréstimos, capital): **fora por ora** —
>    foco em **DRE** + **Fluxo de Caixa**. (Balanço completo continua com o contador.)

---

## 1. Por que esta camada existe

O contador entregou o esqueleto de uma **contabilidade societária completa** (Ativo,
Passivo+PL, Receitas, Custos, Despesas) num **plano de contas hierárquico de 5 níveis**
(`1` › `1.1` › `1.1.01` › `1.1.01.01` › `1.1.01.01.001`), alimentado por uma
**movimentação** (razão de Caixa/Banco) e consolidado num **balancete** (débito/crédito).

O CRM hoje já captura **o fato gerador** (reserva → diária + consumo → recebimento no
caixa; contas a pagar/receber; conciliação bancária), mas numa estrutura **plana**
(`CategoriaFinanceira` = só receita/despesa) e em **regime de caixa**.

**O buraco não é de dados — é de forma.** Temos os números; falta:

1. **Classificá‑los no vocabulário do contador** (plano de contas hierárquico);
2. **Mostrar ao dono um resultado gerencial** (DRE por competência, por setor);
3. **Exportar** no layout que o contador importa — sem redigitação, sem planilha paralela.

Esta camada é **de leitura/classificação/exportação**. Ela **não substitui** nada do
financeiro atual: fica **por cima**, lendo o que já existe.

```
      O QUE JÁ EXISTE (operacional)                 A CAMADA NOVA (classificação)
┌───────────────────────────────────┐        ┌────────────────────────────────────┐
│ Reservas → folio (serviço/consumo) │        │                                    │
│ MovimentoCaixa (imutável)          │──lê──▶ │  De‑Para (Mapeamento Contábil)     │
│ LancamentoFinanceiro (competência) │        │     categoria/módulo → conta        │
│ ContaPagarReceber (baixa)          │        │            │                        │
│ Pagamentos online (Safrapay)       │        │            ▼                        │
│ Loja / Restaurante / Lavanderia    │        │  Plano de Contas (hierárquico)      │
└───────────────────────────────────┘        │            │                        │
                                              │   ┌────────┴─────────┐              │
                                              │   ▼                  ▼              │
                                              │  DRE gerencial   Export p/ contador │
                                              │  Fluxo de caixa  (balancete layout) │
                                              └────────────────────────────────────┘
```

---

## 2. Plano de Contas — enxuto de pousada

O plano que ele mandou é um **template genérico industrial** (tem "Entrada de Madeira
p/Corte", "Remessa p/Abate", "Industrialização", "Receitas de Transporte/Construção
Civil"). **Podado** para pousada, mantendo os **códigos de classificação dele** para o
export casar com o balancete:

### 3 — RECEITAS
```
3.1.01.01  REVENDA DE MERCADORIAS            → Loja, Restaurante (parte consumo)
   .001    Revenda de Mercadorias A Vista
   .002    Revenda de Mercadorias A Prazo
3.1.01.03  PRESTAÇÃO DE SERVIÇOS             → Diária/Hospedagem, Day use, Eventos, Lavanderia
   .001    Prestação de Serviços A Vista
   .002    Prestação de Serviços A Prazo
3.1.02.01  (-) TRIBUTOS S/ VENDAS E SERVIÇOS → deduções da receita bruta
   .001    Simples Nacional                  (regime atual da pousada)
   .002    ISS                               (quando fora do Simples)
   .003    PIS / COFINS                      (idem)
3.1.02.02  (-) DEVOLUÇÕES / ABATIMENTOS      → estornos, no‑show reembolsado
```

### 4 — CUSTOS DOS SERVIÇOS E DAS MERCADORIAS
```
4.2.01.01  GASTOS COM PESSOAL (operação)     → recepção, governança, A&B, manutenção
   .001    Salários · Férias · 13º · FGTS · INSS · Alimentação · Uniformes ·
           Vale Transporte · EPIs · Treinamento · Serviços de Terceiros
4.2.01.02  MATERIAIS APLICADOS NOS SERVIÇOS  → amenities, enxoval consumido, produtos de
   .001    limpeza, insumos de A&B aplicados
4.2.01.03  GASTOS GERAIS DOS SERVIÇOS        → água, energia, internet, manutenção de
   .001    bens/equipamentos/sistemas, combustíveis, seguros, material de consumo
4.5.01.01  CUSTO DAS MERCADORIAS VENDIDAS    → CMV (Loja/Restaurante)
   .001    Estoque Inicial · (+) Compras · (-) Estoque Final · Fretes · (-) Devoluções
           (alimentado pelo motor de Estoque — custo médio ponderado já existe)
```

### 5 — DESPESAS OPERACIONAIS
```
5.1.01.02  DESPESAS COM VENDAS (comercial)   → propaganda/publicidade, comissões de OTA,
   .001    despesas promocionais e brindes, participação em eventos
5.1.02.02  OUTROS GASTOS ADMINISTRATIVOS     → pró‑labore, honorários contábeis/advocatícios,
   .001    certificação digital, assinaturas/mensalidades (sistemas), impostos e taxas
           diversas, impressos e material de expediente
5.1.03.01  RECEITAS FINANCEIRAS              → rendimento de aplicações, juros recebidos
5.1.03.02  DESPESAS FINANCEIRAS              → juros, comissões bancárias,
   .001    TAXAS DE CARTÃO / ADQUIRÊNCIA (Safrapay)  ← novo, vem do módulo Pagamentos
```

> **Patrimonial (grupos 1 e 2) fica fora do CRM por ora** (decisão 4). Se um dia entrar,
> o lugar natural é `1.1.01.02 Bancos` (saldo das contas conciliadas) e
> `1.2.04 Imobilizado` (obra). Hoje o CRM só gera **resultado** (3/4/5), não patrimônio.

---

## 3. Modelo de dados proposto

Novo app `apps/contabil` (módulo contratável, grupo **Gestão**), com **2 models novos**.
**Não toca** nos models financeiros existentes — só os **lê**.

```
┌─────────────────────────────┐        ┌──────────────────────────────────────┐
│ ContaContabil               │        │ MapeamentoContabil  (o "de‑para")      │
│─────────────────────────────│        │────────────────────────────────────────│
│ classificacao  "3.1.01.03"  │◀──────┐│ conta_contabil   FK ContaContabil      │
│ codigo_contador  1561  (int)│       ││ ── origem (um dos abaixo) ──           │
│ nome  "Prestação Serviços"  │       │└ categoria     FK CategoriaFinanceira?  │
│ grupo  receita/custo/despesa│       │  centro        módulo? (hospedagem,…)   │
│ natureza  devedora/credora  │       │  natureza_folio serviço/consumo?        │
│ tipo  sintetica/analitica   │       │  origem_sistema "pagamento_taxa", …     │
│ conta_pai  FK self (hierarq)│       │  prioridade    int (regra mais específica│
│ ativa  bool                 │       │                 vence a genérica)        │
└─────────────────────────────┘       └────────────────────────────────────────┘
        ▲                                         │
        │  resolve a conta                         │
        └──────────────────────────────────────────┘
                 lê, não altera
   ┌───────────────┬──────────────────┬─────────────────────┬──────────────────┐
   │ Lancamento    │ MovimentoCaixa   │ ContaPagarReceber   │ folio Reservas   │
   │ Financeiro    │ (imutável)       │ (baixa)             │ (serviço/consumo)│
   │ (competência) │                  │                     │                  │
   └───────────────┴──────────────────┴─────────────────────┴──────────────────┘
          EXISTENTES — permanecem exatamente como estão
```

**`ContaContabil`** — o plano de contas. Semente (`manage.py seed_plano_contas`) cria as
contas da seção 2, já com o `codigo_contador` para o export casar 1:1 com o balancete.

**`MapeamentoContabil`** — a regra que diz "lançamento/movimento X → conta contábil Y".
Resolução por **prioridade** (regra específica vence genérica):
1. Por `categoria` financeira (ex.: categoria "Honorários Contábeis" → `5.1.02.02.001`).
2. Por `natureza_folio` + `centro` (ex.: consumo no Restaurante → `3.1.01.01.001`).
3. Por `origem_sistema` (ex.: taxa de cartão do Pagamentos → `5.1.03.02.001`).
4. **Fallback** por `centro`/módulo (uma conta "guarda‑chuva" por setor), para nunca
   ficar lançamento órfão.

> **Por que não partidas dobradas:** o DRE sai de **somar** `LancamentoFinanceiro`
> (competência) agrupado pela conta mapeada. O fluxo de caixa sai de `MovimentoCaixa`.
> Nenhum lançamento vira "débito numa conta + crédito noutra" — preservamos tudo o que
> já está testado. O contador recebe os **saldos por conta** e fecha as partidas no
> sistema dele.

### Dimensão "Centro" (setor) — já existe, vira eixo do gerencial
`LancamentoFinanceiro.centro` e `MovimentoCaixa.modulo` já guardam o **setor**
(hospedagem/recepção, restaurante, loja, lavanderia, …). Isso dá uma **DRE por setor**
(coluna por centro) de graça — algo que o balancete do contador **não** entrega e que o
dono quer ver. A conta contábil é o **o quê**; o centro é o **onde**.

---

## 4. Conexão com Reservas (o coração do elo)

A reserva é a principal **fonte de receita**. O caminho hoje já existe no código
(`reservas.services.lancar_na_conta`, folio com naturezas serviço×consumo, recebimento
via caixa/adiantamento). A camada contábil só **classifica** cada etapa:

```
LINHA DO TEMPO DE UMA RESERVA            NATUREZA        CONTA CONTÁBIL        REGIME
──────────────────────────────────────────────────────────────────────────────────────
1. Sinal/adiantamento (pré‑reserva)      recebimento   [Passivo] Adiant. de    CAIXA
   pago no site (Safrapay) ou recepção                  Clientes*               (entra $)
                                                        *fora de escopo agora;
                                                         hoje fica no folio

2. Hospedagem — diárias                  serviço       3.1.01.03.001           COMPETÊNCIA
   (lançadas noite a noite no folio)                    Prestação de Serviços   (dia a dia)

3. Consumo — restaurante/loja            consumo       3.1.01.01.001           COMPETÊNCIA
   lançado no quarto                                    Revenda de Mercadorias

4. Serviço — lavanderia                  serviço       3.1.01.03.001           COMPETÊNCIA
                                                        Prestação de Serviços

5. Check‑out — recebimento do saldo      recebimento   debita Caixa/Banco      CAIXA
   (caixa Reservas, recepção)                           (fora de escopo p/ora)  (entra $)

6. Taxa do cartão (se cartão/Safrapay)   despesa       5.1.03.02.001           COMPETÊNCIA
                                                        Taxas de Cartão         (deduz)

7. Tributo sobre a receita               dedução       3.1.02.01.001           COMPETÊNCIA
   (Simples Nacional)                                   (-) Simples Nacional    (deduz)
```

**Pontos finos que o mockup resolve:**

- **Competência vs. caixa separados corretamente.** A diária entra na DRE **na noite em
  que foi consumida** (competência), mesmo que o hóspede pague tudo no check‑out (caixa).
  O adiantamento **não é receita** quando entra o dinheiro — vira receita na competência.
  Isso é exatamente o que o contador precisa e o que o regime de caixa puro perde hoje.
- **O consumo já carrega a natureza** (`serviço`/`consumo`) no folio — o de‑para usa isso
  direto, sem precisar adivinhar.
- **O CMV fecha com o Estoque.** Cada item de loja/restaurante vendido já baixa
  estoque a custo médio ponderado (motor do núcleo). A receita vai pra `3.1.01.01` e o
  **custo** correspondente pra `4.5.01.01` — a margem bruta por setor sai automática.
- **A taxa de cartão** (adquirência Safrapay) é uma despesa financeira real que hoje some;
  a camada a captura em `5.1.03.02.001` lendo o módulo Pagamentos.

---

## 4.1 Relatório de Reservas (aba dedicada)

Além de alimentar a DRE, o módulo Reservas merece um **relatório financeiro próprio** —
é a principal fonte de receita e tem perguntas que só fazem sentido no contexto da
hospedagem. Tela `contabil:reservas` (ou dentro de Reservas), seletor mês/ano. Organizado
em 6 grupos, com **3 destaques no topo**.

**Destaques (topo):** `Ocupação / ADR / RevPAR` · `Adiantamentos em aberto` ·
`Ponte competência → caixa`. Respondem, numa olhada: *a pousada está cheia?*, *quanto do
caixa ainda é de hóspede futuro?* e *quanto da receita do mês já entrou?*

### Grupo 1 — Receita da hospedagem (competência)
- **Por natureza:** diárias (serviço) × consumo no quarto (restaurante/loja) × lavanderia
  (serviço) × day use/eventos — a quebra já vem do folio.
- **Por canal:** Site · OTA · Agência · Balcão/recepção.
- **Por faturamento:** particular · agência · empresa (quem paga ≠ quem se hospeda).
- **Indicadores hoteleiros:** **ADR** (diária média), **RevPAR** (receita por quarto
  disponível), **ocupação %**, quarto‑noites vendidas.

### Grupo 2 — Adiantamentos / sinais
- **Saldo em aberto** no fim do mês (passivo "Adiantamento de Clientes", a reconhecer).
- **Recebidos no mês** × **consumidos** (viraram receita na competência) × **a devolver**
  (cancelamento).
- **Por origem:** Pagamentos online (Safrapay) × caixa recepção.
- **Confirmadas sem sinal** (risco) · **pré‑reservas aguardando sinal** ·
  **adiantamentos expirados** (retenção venceu, quarto voltou ao mapa).

### Grupo 3 — Fluxo do mês (caixa × competência)
- **Ponte competência → caixa:** receita reconhecida × a receber (folio aberto + a prazo)
  × efetivamente recebido no caixa Reservas.
- **Entradas na gaveta da recepção:** recebimento no check‑out + sinais + consumo pago na
  hora.
- **A receber futuro:** folios de hóspedes ainda hospedados + agência/empresa a prazo.
- **Pipeline de receita futura:** reservas confirmadas dos próximos meses (do mapa).

### Grupo 4 — Perdas, descontos e ajustes
- **No‑show** · **cancelamentos** (com/sem retenção de sinal) · **desconto médio vs.
  tabela** · **estornos/reaberturas** (auditados) · **comissões de OTA/agência** ·
  **taxas de cartão (Safrapay)** atribuídas às reservas pagas no cartão.

### Grupo 5 — Impostos e margem
- **Simples Nacional** rateado sobre a hospedagem · **margem da hospedagem** · **CMV do
  consumo** (fecha com o Estoque) · **margem do A&B**.

### Grupo 6 — Operacional que vira indicador financeiro
- **Permanência média** · **hóspedes‑noite** (base do BOH/Embratur) · **lead time** ·
  **ticket médio por reserva** · **gasto extra médio por hóspede** · **receita por
  temporada/feriado**.

> **Fonte de dados:** quase tudo já existe no módulo Reservas (folio serviço/consumo,
> adiantamentos, canais, tarifas, expiração de pré‑reserva, no‑show/cancelamento, BOH).
> O relatório é **leitura e agregação** — mesma filosofia da camada contábil, sem gravar
> nada novo. Mockup visual na aba **Reservas** do HTML.

---

## 5. Saída 1 — DRE Gerencial (dentro do CRM, pro dono)

Tela `contabil:dre`, seletor mês/ano (reusa `apps/nucleo/periodos.py`). Colunas por
**setor** opcionais. Exemplo ilustrativo (números fictícios):

```
┌─ DRE GERENCIAL · Setembro/2026 ──────────────────── [mês/ano ▾] [CSV] [Imprimir] ┐
│                                                                                   │
│  RECEITA BRUTA                                               R$ 148.200,00        │
│    Prestação de Serviços (hospedagem, day use, eventos)      R$ 121.500,00  82%   │
│    Revenda de Mercadorias (restaurante, loja)                R$  26.700,00  18%   │
│                                                                                   │
│  (-) Deduções da Receita                                     R$  (8.892,00)       │
│    Simples Nacional                                          R$  (8.892,00)  6,0% │
│                                                                                   │
│  = RECEITA LÍQUIDA                                           R$ 139.308,00        │
│                                                                                   │
│  (-) Custo dos Serviços e Mercadorias                        R$ (71.140,00)       │
│    Gastos com Pessoal (operação)                             R$ (42.300,00)       │
│    Materiais aplicados nos serviços                          R$  (9.850,00)       │
│    Gastos gerais (água, energia, internet, manut.)           R$ (11.200,00)       │
│    CMV — Custo das Mercadorias Vendidas                      R$  (7.790,00)       │
│                                                                                   │
│  = LUCRO BRUTO                                               R$  68.168,00  49%   │
│                                                                                   │
│  (-) Despesas Operacionais                                   R$ (39.420,00)       │
│    Despesas com Vendas (comercial, OTAs, propaganda)         R$  (8.900,00)       │
│    Despesas Administrativas (pró‑labore, honorários, …)      R$ (27.600,00)       │
│    Despesas Financeiras (juros, taxas de cartão)             R$  (2.920,00)       │
│    (+) Receitas Financeiras (aplicações)                     R$   1.100,00        │
│                                                                                   │
│  ══════════════════════════════════════════════════════════════════════════     │
│  = RESULTADO DO PERÍODO                                      R$  28.748,00  19%   │
│  ══════════════════════════════════════════════════════════════════════════     │
└───────────────────────────────────────────────────────────────────────────────┘

[ Ver por setor ▾ ]  Hospedagem · Restaurante · Loja · Lavanderia · Day use
```

**Visão "por setor"** (a que o contador não dá e o dono ama): mesma DRE com uma coluna por
centro — revela qual setor dá lucro e qual drena. Cruza `centro` × conta contábil.

---

## 6. Saída 2 — Fluxo de Caixa

Tela `contabil:fluxo_caixa`. **Realizado** vem de `MovimentoCaixa` (já imutável);
**projetado** vem de `ContaPagarReceber` em aberto (vencimentos futuros). Estrutura
idêntica à aba "Caixa"/"Sicoob" que ele mandou (`Data · Descrição · Doc · Entrada ·
Saída · Saldo`), agora **por conta/banco**:

```
┌─ FLUXO DE CAIXA · Setembro/2026 ───────────────────────────────────────────────┐
│  Conta: [ Todas ▾ ]  (Caixa recepção · Caixa setores · Banco Safra · Sicoob)    │
│                                                                                  │
│  Saldo anterior                                                   -32.436,44     │
│  ───────────────────────────────────────────────────────────────────────────   │
│  REALIZADO (MovimentoCaixa)                                                      │
│    02/09  Férias funcionário                        —      6.000,00   -38.436,44 │
│    05/09  Folha funcionários                        —     16.029,32   -54.465,76 │
│    14/09  Recebimento hospedagem (reservas)   24.100,00       —       -30.365,76 │
│    …                                                                             │
│  ───────────────────────────────────────────────────────────────────────────   │
│  PROJETADO (contas a pagar/receber em aberto)                      [tracejado]   │
│    28/09  A receber — Agência XPTO             6.400,00       —                   │
│    30/09  A pagar — Fornecedor Bianchini            —      3.016,32               │
│                                                                                  │
│  Saldo projetado fim do mês                                       ~ -12.900,00   │
└──────────────────────────────────────────────────────────────────────────────┘
```

> Observação: o CRM gera o fluxo **do que ele controla** (caixas operacionais +
> contas a pagar/receber). Os extratos bancários completos (Safra/Sicoob) já entram pela
> **Conciliação** (OFX) existente — dá pra cruzar realizado × extrato aqui.

---

## 7. Saída 3 — Export para o contador

O ponto que elimina a redigitação. Três arquivos, nos **layouts que ele já usa**:

| Export | Formato | Conteúdo | Casa com |
|---|---|---|---|
| **Movimentação** | XLSX (abas por conta/banco) | `Data · Descrição · Documento · Entrada · Saída · Saldo` | "Pousada Vo Testa 09.2026" |
| **Resumo por conta contábil** | XLSX/CSV | `Conta · Classificação · Nome · Débito · Crédito · Saldo` (do período) | Balancete (grupos 3/4/5) |
| **Lançamentos classificados** | CSV | linha a linha: data, histórico, valor, `codigo_contador`, centro | importação genérica |

Gerado por `contabil.services.exportar_para_contador(ano, mes, formato)`. Como guardamos
o `codigo_contador` em cada `ContaContabil`, o arquivo sai com **os códigos dele** — ele
importa sem de‑para manual.

---

## 8. Telas / navegação

Item **Financeiro ▸ Contábil** na sidebar (área `Area.FINANCEIRO`, gerência):

```
Financeiro
 ├─ Caixa (existe)
 ├─ Contas a pagar/receber (existe)
 ├─ Lançamentos (existe)
 ├─ Conciliação bancária (existe)
 └─ Contábil  ◀── NOVO
     ├─ DRE Gerencial            (§5)  — a tela que o dono abre todo mês
     ├─ Fluxo de Caixa           (§6)
     ├─ Plano de Contas          (§2)  — árvore, editar contas
     ├─ De‑Para (Mapeamentos)    (§3)  — regras categoria/setor → conta
     └─ Exportar p/ contador     (§7)
```

**Plano de Contas** = árvore recolhível (sintéticas com total, analíticas com saldo).
**De‑Para** = tabela com "regra → conta", mais um **assistente**: ao ver lançamentos
ainda não mapeados, sugere a conta e pede 1 clique ("órfãos a classificar: 3").

---

## 9. O que muda no código (resumo — para o plano futuro, não agora)

| Camada | Novo | Reusa / não toca |
|---|---|---|
| Models | `ContaContabil`, `MapeamentoContabil` (app `apps/contabil`) | `LancamentoFinanceiro`, `MovimentoCaixa`, `ContaPagarReceber`, folio de Reservas, Pagamentos, Estoque |
| Services | `resolver_conta(lancamento)`, `montar_dre(periodo, por_setor)`, `montar_fluxo_caixa(periodo)`, `exportar_para_contador(...)` | `reservas.services`, `relatorios.services`, `nucleo.export`, `nucleo.periodos` |
| Seeds | `seed_plano_contas` (contas da §2 + `codigo_contador`), de‑para inicial por setor | migração seed padrão |
| UI | 5 telas (§8), no design "Lampião" (tokens/`.quadro`/`.kpi`) | `_estilo_elegante.html` |
| Migrações | `contabil.0001` (2 models), seed | nenhuma migração destrutiva |

**Esforço estimado (ordem de grandeza, a confirmar no `writing-plans`):**
- Plano de contas + de‑para + seed: ~1 unidade.
- DRE gerencial (com por‑setor): ~1 unidade.
- Fluxo de caixa: ~0,5.
- Export pro contador: ~1 (os layouts XLSX dão trabalho).
- Testes de dinheiro (obrigatórios) + django‑verification: ~0,5.

**Nada é refatoração do que existe** — é camada aditiva. Risco baixo sobre o testado.

---

## 10. Pendências / perguntas que ficam para a implementação

1. **Regime tributário atual:** o balancete mostra **Simples Nacional** (bom — a dedução
   da receita é uma linha só). Confirmar a **alíquota efetiva** (anexo/faixa) para a
   linha de deduções da DRE sair certa, ou se puxamos o valor real do DAS pago.
2. **Pessoal (folha):** hoje a folha não está no CRM (vem do contador). Entra como
   **lançamento manual mensal** por conta (`4.2.01.01` / `5.1.02.02`) ou importamos um
   resumo? (Afeta se a DRE fecha com pessoal ou fica "sem custo de pessoal".)
3. **Granularidade do de‑para:** quão fino? (ex.: separar "energia" de "água" dentro de
   gastos gerais, ou agrupar?) Sugiro começar **grosso** (por conta analítica da §2) e
   refinar sob demanda.
4. **Taxa de cartão:** confirmar se o Pagamentos/Safrapay devolve a taxa por transação
   (para lançar em `5.1.03.02.001`) ou se é um acerto mensal da adquirente.
5. **Layout exato do import do contador:** pedir a ele **um modelo de arquivo** que o
   sistema dele importa (ou confirmar que digita a partir do nosso XLSX). Isso define o
   §7 com precisão.

---

## 11. Próximos passos sugeridos

1. **Você revisa este mockup** e ajusta o plano de contas da §2 / o fluxo da §4.
2. (Opcional) Rendo as telas §5/§6/§8 como **HTML navegável** com a skill `visualize`,
   para você "ver" antes de decidir.
3. Fechado o desenho → **`writing-plans`** transforma em plano de implementação por
   etapas → aí sim TDD + `django-verification`.
4. Se virar módulo recorrente, **criar uma skill de Contabilidade BR** (`skill-creator`)
   para a implementação sair correta nas regras fiscais.

> **Como tornar isto viável:** este mockup é a **saída**. Para os relatórios terem dado
> real, o financeiro precisa de portas de entrada e de uma espinha de classificação —
> ver [`Plano_Saneamento_Financeiro.md`](Plano_Saneamento_Financeiro.md) (etapas 1 a 5).
```


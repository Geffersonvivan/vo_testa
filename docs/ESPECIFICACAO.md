# Especificação — CRM/PMS Pousada Vô Testa

**Versão:** 0.2
**Data:** 03/07/2026
**Referências:**

- **Benchmark de mercado (consulta obrigatória):** <https://www.desbravador.com.br/produtos/hoteis-e-pousadas>
- `docs/REFERENCIA_DESBRAVADOR.md` (levantamento dos 9 produtos)
- `docs/apresentacao_easy_web.pdf`

> **Processo:** ao iniciar a construção de cada fase/módulo, consultar o link do
> Desbravador acima (e o levantamento) para verificar como o mercado resolve
> aquele módulo — funcionalidades, fluxos e telas — antes de desenhar o nosso.

---

## 1. Visão geral

Sistema de gestão completo (PMS/CRM) para a Pousada Vô Testa — 24 quartos diferenciados —
cobrindo reservas, hospedagem, financeiro, pagamentos, estoque, pontos de venda,
governança, lavanderia/rouparia, manutenção e escala de equipe.

**Decisão estratégica:** o sistema é construído como **núcleo + módulos contratáveis**,
para que no futuro possa ser vendido a outras pousadas/hotéis com contratação por módulo.
A Pousada Vô Testa é o cliente nº 1 do produto.

### Princípios de arquitetura

1. **Fonte de verdade única** — disponibilidade, dinheiro e estoque têm um dono cada
   (Reservas, Financeiro, Motor de Estoque). Nenhum módulo duplica essas regras.
2. **Módulos isolados** — cada módulo é um app Django; comunicação entre módulos
   somente por interfaces claras (services), nunca import cruzado de models internos.
3. **Degradação graciosa** — módulo funciona com dependências mínimas: a Loja sem o
   módulo Reservas vende apenas no balcão; com Reservas, também lança na conta do quarto.
4. **Registro de módulos** — tabela de módulos ativos controla menus, permissões e
   comportamentos. É a base do modelo comercial "contratado por módulos".
5. **Trilha de auditoria** — toda operação sensível (estorno, cancelamento, ajuste de
   estoque, reabertura de caixa) registra quem, quando e por quê.

---

## 2. Stack técnica

| Camada | Escolha | Justificativa |
|---|---|---|
| Backend | Python 3.12 + Django 5.x | Produtividade, admin gratuito, ecossistema maduro |
| Banco | PostgreSQL | `ExclusionConstraint` impede overbooking no nível do banco |
| Frontend interno | Templates Django + HTMX + Alpine.js | Sistema interno ágil sem SPA; corta a complexidade pela metade |
| API pública | Django REST Framework | Serve o módulo APP/Site (site hoje, app mobile amanhã) |
| Tarefas assíncronas | Celery + Redis (quando necessário) | Webhooks de pagamento, e-mails, tarefas agendadas |
| Pagamentos | Gateway brasileiro (Asaas/Mercado Pago/Pagar.me — a definir) | Pix, cartão, boleto, estorno via API |
| Deploy | Railway | Já configurado; MCP conectado |

---

## 3. Mapa de módulos

```
                        ┌─────────────── NÚCLEO ───────────────┐
                        │ Cadastros · Usuários/Permissões ·     │
                        │ Financeiro/Caixa · Dashboard ·        │
                        │ Motores (Estoque, PDV) ·              │
                        │ Registro de módulos · Logbook         │
                        └──────────────────┬────────────────────┘
                                           │
        ┌──────────┬──────────┬────────────┼───────────┬──────────────┐
        │          │          │            │           │              │
    RESERVAS    ESCALA     ESTOQUE    PAGAMENTOS   APP/SITE      (fase 2:
        │          │          │        ONLINE      (dep: Reservas  CRM Hóspede,
   ┌────┼────┐     │     ┌────┼──────────┬───────┐  + Pag.Online)  Canais/OTAs,
   │    │    │     │     │    │          │       │                 Fiscal)
GOVERN. MANUT. FRIGOBAR◄─┘  LOJA   RESTAURANTE  LAVANDERIA
   ▲                                 PISCINA        │
   └────────────── rouparia interna ────────────────┘
```

| # | Módulo | Depende de | Fase |
|---|---|---|---|
| — | Núcleo | — | 1 |
| 1 | Reservas | Núcleo | 1 |
| 2 | Governança | Reservas | 1 |
| 3 | Manutenção | Reservas | 1 |
| 4 | Escala | Núcleo | 1 |
| 5 | Estoque | Núcleo | 1 |
| 6 | Loja | Estoque | 1 |
| 7 | Restaurante Piscina | Estoque | 1 |
| 8 | Lavanderia | Estoque; integra Governança | 1 |
| 9 | Frigobar | Reservas + Estoque | 1 |
| 10 | Pagamentos Online | Núcleo | 1 |
| 11 | APP/Site | Reservas + Pagamentos Online | 1 (final) |
| 12 | CRM do Hóspede | Reservas | 2 |
| 13 | Canais/OTAs | Reservas | 2 |
| 14 | Fiscal (NF-e/NFS-e) | Núcleo | 2 |

### As três "veias" transversais

1. **Conta do quarto (folio)** — Loja, Restaurante, Lavanderia e Frigobar lançam consumo
   na conta da hospedagem. Hóspede paga tudo consolidado no check-out.
2. **Dinheiro** — toda cobrança de qualquer módulo passa pelo Financeiro do núcleo,
   pelo caixa do operador daquele módulo. Cada módulo é um centro de receita/custo.
3. **Estoque** — todo produto que entra/sai em qualquer módulo passa pelo motor de
   estoque. Transferências entre módulos são rastreadas dos dois lados.

---

## 4. Núcleo

### 4.1 Cadastros

- **Pessoa** (base única): nome, CPF/CNPJ, contatos, endereço. Especializações:
  **Hóspede** (documento, nascimento, preferências, histórico), **Cliente avulso**
  (compras na loja/restaurante sem hospedagem), **Fornecedor**, **Funcionário**
  (cargo, setor, admissão).
- **Estrutura**: **TipoUH** (nome, capacidade, tarifa base, fotos, descrição) e
  **UH** (número, tipo, andar/bloco, status operacional). 24 UHs diferenciadas.
- **Temporada**: calendário de períodos (baixa/média/alta/super alta + feriados)
  com vigência por data.

### 4.2 Usuários e permissões

- Login individual por funcionário (e-mail + senha). Sem login compartilhado.
- **Acesso por usuário × módulo, gerido pelo Admin** *(implementado na fase 0)*:
  o administrador atribui a cada usuário os módulos que ele pode acessar
  (`Usuario.modulos`). Superusuário acessa todos os módulos ativos. Toda view de
  módulo usa `@requer_modulo(...)`: módulo não contratado → 404; usuário sem o
  módulo atribuído → 403. Menu e dashboard só exibem o que o usuário pode acessar.
- **Perfis por módulo** (evolução): cada perfil define nível dentro do módulo
  (visualizar / operar / gerenciar). Ex.: "Recepção" opera Reservas e Frigobar;
  "Loja" opera Loja; "Gerência" gerencia tudo.
- Ações sensíveis (estorno, desconto acima de X%, reabertura de caixa, ajuste de
  estoque) exigem nível gerência — na tela, via aprovação com senha do gerente.

### 4.3 Financeiro & Caixa

- **Sessão de caixa por operador vinculado ao módulo**: funcionário abre o caixa do
  seu módulo com fundo de troco; registra recebimentos; faz reforços e retiradas
  (sangria); fecha com conferência cega (informa o contado, sistema aponta diferença).
- **Formas de pagamento**: dinheiro, Pix, cartão débito/crédito (com nº de parcelas),
  transferência, cortesia. Uma conta pode ser paga com múltiplas formas.
- **Adiantamento**: valor recebido antes do check-in, vinculado à reserva; vira
  crédito na conta da hospedagem. Pode ser recebido no balcão ou pelo APP/Site.
- **Estorno/Devolução**: reverso de pagamento com motivo obrigatório e permissão de
  gerência; se pagamento online, dispara estorno no gateway; sempre auditado.
- **Receitas e despesas**: lançamentos classificados por categoria e por
  **centro de receita/custo = módulo** (Hospedagem, Loja, Restaurante, Lavanderia...).
- **Contas a pagar/receber**: título, vencimento, fornecedor/cliente, baixa.

### 4.4 Motor de Estoque (engine interna)

- **Produto**: código (barras), nome, categoria, unidade, custo médio, preço de venda,
  estoque mínimo, ativo/inativo.
- **Local de estoque**: um por módulo que usa estoque (Loja, Restaurante, Frigobar
  central, Lavanderia/insumos, Rouparia) + Almoxarifado central.
- **Movimento de estoque** (kardex): tipo — entrada por compra, saída por venda,
  consumo interno, perda/quebra/vencimento, transferência entre locais, ajuste de
  inventário. Todo movimento registra produto, quantidade, local, custo, operador,
  data/hora e documento de origem.
- **Inventário**: contagem física por local com ajuste auditado.
- Alertas de estoque mínimo no dashboard.

### 4.5 Motor PDV/Comandas (engine interna)

- **Venda/Comanda**: itens, quantidades, preços, descontos, operador, módulo de origem.
- **Dois destinos de cobrança**:
  (a) **pagamento imediato** — cai na sessão de caixa do operador;
  (b) **conta do quarto** — lança na hospedagem ativa (exige módulo Reservas;
  identifica UH + hóspede; hóspede confirma/assina).
- Venda para **não-hóspede**: pagamento imediato com cliente avulso opcional.
- Comanda pode ficar **aberta** (restaurante) e ser fechada/transferida depois.

### 4.6 Dashboard & Relatórios

- Painel inicial: ocupação do dia e prevista, check-ins/outs pendentes e efetuados,
  UHs por status (livre/ocupada/limpeza/manutenção), caixas abertos, alertas
  (estoque mínimo, contas vencidas, pendências de auditoria).
- Indicadores: taxa de ocupação, diária média (ADR), RevPAR, receita por módulo.
- Cada módulo contratado pluga seus relatórios no menu central.

### 4.7 Logbook (livro de ocorrências)

- Registro diário compartilhado entre turnos: ocorrências, avisos, pendências.
- Entradas por usuário com data/hora; leitura obrigatória na abertura do turno.

### 4.8 Registro de módulos

- Tabela `ModuloContratado`: módulo, ativo desde/até, parâmetros.
- Menus, permissões e integrações consultam o registro — nunca hard-code.

---

## 5. Módulos — Fase 1

### 5.1 Reservas (o carro-chefe)

**Ciclo de estados da reserva:**

```
Orçamento → Pré-reserva → Confirmada → Hospedado → Check-out (encerrada)
                │             │            
                └──► Cancelada (motivo) ◄──┘        Confirmada ──► No-show
```

- **Orçamento**: cotação sem segurar UH; validade; conversão em reserva.
- **Pré-reserva**: segura a UH por tempo de retenção configurável (ex.: 48h ou até
  pagamento do sinal). Expirou sem sinal → libera automático.
- **Confirmada**: sinal recebido ou garantia registrada.
- **Cancelamento**: motivo obrigatório; política de reembolso do sinal conforme
  antecedência (parâmetros configuráveis).
- **No-show**: não chegou até horário limite; regra de cobrança configurável.

**Funcionalidades:**

- **Mapa de Reservas**: grade UH × dias; criar, mover, esticar/encurtar reserva;
  check-in e troca de quarto por arrastar; cores por status; mapa de calor de ocupação.
- **Mapa de UHs**: visão de status ao vivo (livre, ocupada, limpeza, manutenção).
- **Check-in**: da reserva ou **walk-in** (sem reserva); ficha do hóspede (FNRH);
  acompanhantes; abertura automática da conta da hospedagem.
- **Conta da hospedagem (folio)**: diárias lançadas automaticamente (rotina diária),
  consumos dos PDVs, serviços, descontos, adiantamentos como crédito; extrato completo.
- **Check-out**: confere conta, recebe saldo (múltiplas formas), encerra hospedagem,
  dispara tarefa de faxina (Governança) e libera a UH após limpeza.
- **Tarifas**: matriz TipoUH × Temporada; tarifa manual por reserva com permissão;
  (a refinar: variação por nº de ocupantes, café incluso — ver §9).
- **Wait list**: interessados sem disponibilidade, com prioridade e contato.
- **Overbooking**: bloqueado por constraint de exclusão no PostgreSQL —
  duas reservas ativas não podem ocupar a mesma UH em períodos sobrepostos.
- **FNRH**: geração do arquivo para envio ao e-FNRH (Ministério do Turismo).
- **Auditoria diária**: pendências — check-outs atrasados, diárias não lançadas,
  contas com saldo devedor antigo, pré-reservas expiradas.

### 5.2 Governança

- **Status de limpeza por UH**: suja → em limpeza → limpa → inspecionada;
  bloqueio para manutenção. Integrado ao Mapa de UHs e ao check-in
  (só entra hóspede em UH limpa/inspecionada).
- **Tarefas geradas por evento**: check-out → faxina completa; estadia longa →
  arrumação diária + troca de roupa de cama a cada N dias (configurável);
  pós-manutenção → limpeza.
- Atribuição de tarefa a camareira; registro de início/fim; checklist por tipo
  de faxina; inspeção pela governanta.
- Integração Lavanderia: faxina gera coleta de enxoval sujo e requisição de limpo.

### 5.3 Manutenção

- **Ordem de serviço**: UH ou área comum, descrição, prioridade, responsável,
  fotos, custo (peças via Estoque + mão de obra).
- **Bloqueio de UH** durante reparo (some da disponibilidade).
- **Manutenção preventiva com recorrência** (ex.: revisar ar-condicionado a cada
  6 meses) — agenda automática.

### 5.4 Escala (diferencial — Desbravador não tem)

- **Turnos** definidos por setor (recepção 24h? — ver §9).
- **Escala mensal/semanal**: funcionário × dia × turno; folgas; férias; trocas de
  turno com aprovação; visão de cobertura por setor.
- Publicação da escala (funcionário vê a sua); histórico para folha.
- Integração: tarefas de Governança/Manutenção atribuíveis a quem está de turno.

### 5.5 Estoque (módulo de gestão sobre o motor)

- Telas de: entrada de mercadoria (compra por fornecedor), transferência entre
  locais, ajuste/inventário, perda/quebra.
- Relatórios: kardex por produto, posição por local, giro, produtos abaixo do mínimo,
  custo do estoque.

### 5.6 Loja

- **PDV balcão**: busca por código de barras/nome, carrinho, desconto (com alçada),
  pagamento imediato (dinheiro/Pix/cartão) **ou** conta do quarto.
- Vende para **não-hóspedes** (cliente avulso opcional para nota/histórico).
- Caixa próprio por operadora da loja.
- Relatórios: vendas por período/produto/forma de pagamento, **margem por produto**
  (preço − custo médio), curva ABC.

### 5.7 Restaurante Piscina

- **Cardápio**: itens por categoria (pratos, porções, bebidas), preço, disponibilidade.
- **Comandas**: abertas por mesa, por hóspede (nº da UH + nome) ou por cliente avulso;
  itens lançados ao longo do dia; transferência entre comandas; fechamento com
  pagamento imediato ou conta do quarto.
- Consumo de insumos: baixa de estoque por venda (ficha técnica simples — item
  vendido consome N unidades de insumo; refinável depois).
- Atende **não-hóspedes** e day use (fase 2 do day use formal).
- Caixa próprio por operador do restaurante.

### 5.8 Lavanderia

**(a) Serviço ao hóspede:**
- Ordem de serviço: peças/kg, tabela de preços, prazo; status recebido → lavando →
  pronto → entregue; cobrança na conta do quarto (ou imediata para não-hóspede).

**(b) Rouparia interna (conecta Governança):**
- **Itens de enxoval**: lençol, fronha, toalha etc. por tamanho/tipo, com quantidade
  total do ativo.
- **Ciclo rastreado**: em uso (por UH) → suja (coleta na faxina) → lavando → limpa
  (estoque rouparia) → entregue para faxina. Movimentos com quantidade por item.
- Baixa por desgaste/dano; alerta de enxoval mínimo por item.
- Consumo de insumos de lavagem via Estoque.

### 5.9 Frigobar

- **Estoque por quarto**: composição padrão do frigobar por TipoUH.
- **Conferência**: na arrumação diária e no check-out, camareira/recepção registra
  consumo → lança na conta do quarto → gera lista de reposição.
- Reposição baixa do estoque central de frigobar.
- Check-out bloqueado até conferência do frigobar (configurável).

### 5.10 Pagamentos Online

- Integração com gateway brasileiro (a definir — ver §9): **Pix** (QR/copia-e-cola),
  **cartão de crédito** (com parcelas), **boleto**, **link de pagamento**.
- Usos: sinal de reserva (link enviado por WhatsApp/e-mail), pagamento no APP/Site,
  cobrança de saldo.
- **Webhooks**: confirmação automática → baixa o adiantamento/conta e confirma reserva.
- **Estorno via API** integrado ao fluxo de estorno do Financeiro.
- **Conciliação**: transações do gateway × lançamentos do sistema.

### 5.11 APP/Site

**Camada pública — sem lógica própria de reservas ou dinheiro** (consome Reservas e
Pagamentos Online por dentro; API REST serve site hoje e app mobile amanhã).

**Antes da estadia (público):**
- Vitrine da pousada: quartos (fotos, descrição), tarifas, políticas.
- Motor de reservas: consulta disponibilidade/preço em tempo real → pré-reserva com
  **tempo de retenção** (segura a UH por X minutos) → pagamento do sinal (Pix/cartão)
  → confirmação automática + e-mail/WhatsApp.

**Durante a estadia (logado/QR Code):**
- Extrato da conta em tempo real.
- Pedidos ao Restaurante Piscina (cai como comanda).
- Solicitações (limpeza extra, manutenção, itens) → viram tarefas nos módulos.
- Check-out expresso: confere conta e paga pelo celular.

**Segurança**: única superfície pública — rate limiting, autenticação por token,
API expõe somente o necessário (nunca dados internos/financeiros de outros hóspedes).

---

## 6. Módulos — Fase 2

| Módulo | Escopo resumido |
|---|---|
| **CRM do Hóspede** | Histórico consolidado de estadias e consumo, preferências, hóspede recorrente, pesquisa de satisfação pós-estadia, campanhas (aniversário, retorno) |
| **Canais/OTAs** | Sincronização Booking/Airbnb: começa com iCal (disponibilidade), evolui para channel manager via API (tarifas + reservas automáticas) |
| **Fiscal** | NFS-e/NF-e/NFC-e via intermediador (Focus NFe/eNotas); emissão no check-out e nos PDVs |
| Extensões | Day use/Day pass formal, eventos, fidelidade, BI histórico com origem de hóspedes |

---

## 7. Modelo de dados (entidades principais)

```
Pessoa ─┬─ Hóspede ──────────┐
        ├─ Funcionário ── Usuário (perfil por módulo)
        ├─ Fornecedor        │
        └─ ClienteAvulso     │
                             │
TipoUH ── UH ── Reserva ── Hospedagem ── ContaHospedagem (folio)
   │       │      │  │                        │
 Tarifa    │      │  └ Acompanhantes          ├─ Lançamento (diária, consumo,
   │       │      └ MotivoCancelamento        │   serviço, desconto, crédito)
Temporada  │                                  ├─ Pagamento ─ Estorno
           ├─ StatusLimpeza (Governança)      └─ Adiantamento
           ├─ TarefaGovernanca ── ChecklistItem
           ├─ OrdemManutencao (bloqueio de UH)
           └─ FrigobarComposicao / FrigobarConferencia

SessaoCaixa (operador × módulo) ── MovimentoCaixa (recebimento, reforço, sangria)
CategoriaFinanceira ── LancamentoFinanceiro (centro receita/custo = módulo)
ContaPagarReceber

Produto ── MovimentoEstoque (kardex) ── LocalEstoque (por módulo)
        └─ Inventario / ItemInventario

Venda/Comanda ── ItemVenda ── (destino: SessaoCaixa OU ContaHospedagem)
Mesa (restaurante) · FichaTecnica (item → insumos)

ItemEnxoval ── MovimentoRouparia (em uso → suja → lavando → limpa)
OSLavanderia (serviço ao hóspede)

Turno ── Escala (funcionário × dia × turno) ── TrocaTurno / Folga
Logbook ── EntradaLogbook
ModuloContratado · TrilhaAuditoria (genérica)
```

**Regras de integridade críticas:**

- `Reserva`: exclusion constraint (PostgreSQL) sobre (UH, período) para estados ativos
  — impossível overbooking, mesmo com dois operadores simultâneos.
- `MovimentoEstoque` e `MovimentoCaixa`: imutáveis (correção = movimento inverso,
  nunca update/delete).
- `Pagamento`/`Estorno`: nunca deletados; estorno referencia o pagamento original.
- Valores monetários: `DecimalField`, nunca float.

---

## 8. Fases de implementação

**Fase 0 — Fundação (primeira entrega):**
projeto Django + PostgreSQL + autenticação + layout base + registro de módulos +
deploy no Railway funcionando. CLAUDE.md com convenções.

**Fase 1 — MVP operacional (ordem de construção):**

1. **Núcleo**: cadastros, usuários/perfis, financeiro/caixa, dashboard básico, logbook
2. **Reservas**: mapa, ciclo completo, check-in/out, conta do quarto, tarifas, FNRH
3. **Estoque**: motor + telas de gestão
4. **Loja**: primeiro PDV completo (valida os dois motores)
5. **Governança + Lavanderia**: limpeza por evento + rouparia integrada
6. **Restaurante Piscina**: comandas, cardápio, ficha técnica
7. **Frigobar**: composição, conferência, reposição
8. **Escala**: turnos, escala mensal, trocas
9. **Manutenção**: OS, recorrência, bloqueio de UH
10. **Pagamentos Online**: gateway, webhooks, conciliação
11. **APP/Site**: API pública + motor de reservas + área do hóspede

Cada módulo só é iniciado com o anterior **funcionando, testado e validado por você**.
Critério de pronto: testes automatizados passando (regras de dinheiro e
disponibilidade obrigatoriamente testadas) → `/code-review` → validação em uso real
→ commit → deploy.

**Fase 2:** CRM do Hóspede, Canais/OTAs, Fiscal, extensões.

**Encerramento do projeto (go-live):** migração de dados reais, criação dos usuários
com perfis, backup automático do banco, período de operação assistida.

---

## 9. Perguntas em aberto (respostas definem parâmetros)

| # | Pergunta | Impacta |
|---|---|---|
| 1 | Quais os tipos dos 24 quartos? (nomes, quantos de cada, capacidade) | Cadastro TipoUH/UH |
| 2 | Horários de check-in/check-out? Cobra late check-out / early check-in? | Reservas, diárias |
| 3 | Tarifa varia por nº de pessoas? Café da manhã incluso? | Matriz de tarifas |
| 4 | Quais temporadas praticam hoje e quem define o calendário? | Temporadas |
| 5 | Política de sinal e cancelamento: % do sinal, prazos, reembolso? | Reservas, Pagamentos |
| 6 | Tamanho da equipe e funções? Recepção 24h? | Perfis, Escala |
| 7 | Preferência de gateway (Asaas, Mercado Pago, Pagar.me, Efí)? Comparar taxas | Pagamentos Online |
| 8 | Loja usará leitor de código de barras? Balança? | PDV Loja |
| 9 | Restaurante: comanda por mesa, por hóspede, ou ambos? | Restaurante |
| 10 | Já emitem nota fiscal hoje? Qual tipo/prefeitura? | Fiscal (fase 2) |
| 11 | Site atual existe? Domínio? Identidade visual da pousada? | APP/Site |
| 12 | Só R$ ou recebem moeda estrangeira? | Financeiro |

---

## 10. Segurança (resumo — detalhado na implementação)

- HTTPS obrigatório; senhas com hash forte (padrão Django); sessões com expiração.
- Permissões verificadas no servidor (nunca só esconder botão).
- Proteção CSRF/XSS/SQL injection (padrões Django + skill `django-security` em cada módulo).
- Segredos em variáveis de ambiente (nunca no código); `.env` fora do git.
- Backups automáticos diários do PostgreSQL; teste de restauração periódico.
- LGPD: dados de hóspedes minimizados, acesso auditado, retenção definida.

# Auditoria completa do CRM — ponta a ponta

Documento vivo. Objetivo: auditar **cada módulo** por 5 lentes e validar os **fluxos-mestre**
que cruzam módulos (onde moram os bugs). Marque `[x]` o que passar; registre achados no fim.

## Como rodar (ambiente)

- **Nunca em produção.** Usar homologação/local com dados semeados
  (`popular_demo`, `popular_reservas`/`popular_loja`/`popular_marketing`, etc.).
- **Baseline automatizado:** `.venv/bin/coverage run --source=apps manage.py test`
  → `.venv/bin/coverage report` (mapa de buracos abaixo).
- **E2E de integração** (repetível): `apps/reservas/tests_e2e.py` (fluxos-mestre).

## As 5 lentes (aplicar em cada módulo)

1. **Funcional** — happy path + casos de borda.
2. **Dinheiro** — `Decimal`; movimentos **imutáveis**; estorno = inverso; conferência bate.
3. **Disponibilidade** — overbooking barrado pela `ExclusionConstraint`; expiração de retenção.
4. **Permissões** — módulo inativo → 404; sem área/módulo → 403; superusuário passa.
5. **Cross-module + degradação** — handoff funciona e o módulo roda com os opcionais desligados.

---

## Mapa de cobertura (baseline 03/10/2026 — TOTAL 80%)

Prioridade = menor cobertura + maior criticidade (dinheiro/disponibilidade).

| Módulo | services.py | models.py | Prioridade de teste manual |
|---|---|---|---|
| **frigobar** | **39%** | 90% | 🔴 ALTA — maior buraco |
| governanca | 75% | 94% | 🟠 média |
| fiscal | 78% | 95% | 🟠 média (toca nota/dinheiro) |
| lavanderia | 78% | 93% | 🟠 média |
| reservas | 79% | 92% | 🟠 média (hub: 135 linhas sem cobrir) |
| conciliacao | 85% | 95% | 🟡 |
| pagamentos | 85% | 96% | 🟡 (dinheiro online) |
| loja | 85% | 93% | 🟡 |
| restaurante | 84% | 93% | 🟡 |
| manutencao | 83% | 97% | 🟡 |
| relatorios | 83% | — | 🟡 |
| comercial | 87% | 95% | 🟢 |
| escala | 90% | 95% | 🟢 |
| marketing | 92% | 92% | 🟢 |
| nucleo (financeiro) | 90% | — | 🟢 (caixa — cobrir o resto) |

---

## Fluxos-mestre E2E (um fluxo cobre vários módulos)

- [x] **#1 — Hospedagem + consumo (dinheiro ponta a ponta)**
  Reserva por unidade → confirmar → **antioverbooking** → check-in (diárias no folio) →
  consumo na **Loja** cai no folio + baixa estoque → **pagar o folio no caixa** →
  check-out (bloqueado com saldo; libera quitado) → **Governança** suja o quarto.
  → `apps/reservas/tests_e2e.py::FluxoMestre1E2ETests` — **verde 03/10**.
- [ ] **#2 — Site → CRM → pagamento online** (site cria pré-reserva → retenção/expiração →
  sinal via Pagamentos/webhook → confirma → recibo do canal).
- [ ] **#3 — Restaurante/Lavanderia/Frigobar no folio** (comanda e serviço lançam no folio;
  frigobar baixa estoque central; check-out concilia).
- [ ] **#4 — Fiscal** (NFS-e da diária a partir da parte SERVIÇO do folio; cancelamento).
- [ ] **#5 — Comercial → Reserva** (lead → cotação → conversão em reserva → hand-off).

---

## Checklist por módulo (fluxos-chave)

### Núcleo — Caixa & Financeiro 🟢
- [ ] Abrir caixa por operador×módulo (constraint uma-aberta); receber; conferência cega; fechar.
- [ ] Estorno/reabertura **auditados**; movimento é imutável (correção = inverso).
- [ ] Contas a pagar/receber; vencidas aparecem no dashboard "Precisa de atenção".

### Núcleo — Estoque 🟢
- [ ] Entrada (custo médio), saída (sem saldo negativo), transferência, ajuste, inventário — kardex imutável.

### Reservas 🟠
- [x] Ciclo pré→confirmada→hospedada→checkout; antioverbooking; folio diárias+consumo+serviço (via #1).
- [ ] FNRH: trava de check-in; pré-check-in no portal; BOH mensal + CSV.
- [ ] Troca de quarto (conta segue); mapa lê status de limpeza; grupos (sinal único).

### Loja / Restaurante / Lavanderia / Frigobar 🟡/🔴
- [x] Loja: venda no folio baixa estoque (via #1).
- [ ] Destino **caixa** (gaveta do setor) × **conta do quarto** (recepção recebe no check-out).
- [ ] Cancelamento devolve estoque + estorna; **Frigobar (39% — cobrir)**: conferência lança no folio, reposição baixa estoque central.

### Governança / Manutenção / Escala 🟠/🟢
- [x] Check-out → faxina (sinal) (via #1).
- [ ] Manutenção: bloqueio de quarto (status BLOQUEADA), concluir libera + faxina; preventiva recorrente.
- [ ] Escala: grade semanal, ausência bloqueia escalar, troca de turno aprovada reatribui.

### Pagamentos 🟡
- [ ] Cobrança (Pix/cartão/boleto/link); webhook **idempotente**; estorno auditado; conciliação.
- [ ] **Pix direto** (fora do PSP): BR Code local, confirmação manual; cartão segue Safra.

### Comercial / Marketing 🟢
- [ ] Funil (ganho só por conversão), perda com motivo, SLA; **calendário segue as datas** (corrigido).
- [ ] Marketing: portão por fase (autosave destrava), verba/teto, canais.

### Fiscal 🟠
- [ ] NFS-e da diária (parte SERVIÇO do folio), idempotente; cancelamento auditado; gateway simulado.

### Portal / Site 🟡
- [ ] Portal por token: pedir restaurante/limpeza/manutenção/check-out expresso; degrada se módulo off.
- [ ] Site: vitrine por unidade, reserva por quarto, day use; expiração de retenção.

### Auditoria / Relatórios 🟢
- [ ] Varredura de pendências (caixa aberto, vencidas, estoque mínimo) com link "Resolver".
- [ ] Trilha append-only (toda escrita) com frases legíveis + CSV; faturamento por setor (mês/ano).

---

## Achados — fluxo-mestre #1 (E2E)

- **A1** (info): check-out recusa com saldo em aberto ("receba ou ajuste antes") — invariante confirmado e coberto por teste.
- **A2** (baixa): `ContaHospedagem.total_por_natureza()` indexa pela *label* ("Consumo"/"Serviço") — frágil p/ uso programático; considerar chavear pelo value.
- (Cobertura: Frigobar/39% — **resolvido**: módulo removido em 03/10.)

## Achados — Auditoria multiagente (03/10/2026)

19 módulos auditados · **45 achados confirmados** (após refutação adversarial de 49 brutos) · 4 altas, 15 médias, 23 baixas, 3 info.

> ⚠️ 6 módulos não concluíram (agentes travaram): **pagamentos, site, manutenção, portal, conciliação** (+1) — re-auditar.

# Relatório Executivo de Auditoria — CRM Pousada Vô Testa

**Data:** 01/10/2026 · **Escopo:** 40 achados confirmados (pós-refutação adversarial) · **Público:** dono da pousada + desenvolvedor

---

## 1. Veredito geral

O CRM está **estruturalmente saudável e apto a operar**: as regras invioláveis do projeto funcionam no caminho principal — dinheiro em `DecimalField`, movimentos de caixa/estoque imutáveis e auditados, overbooking barrado por `ExclusionConstraint` no banco, e a auditoria total por signals de fato registra as escritas. **Nenhum achado é "Crítico"** (nenhum permite perda irreversível de dinheiro, overbooking consumado ou acesso por usuário anônimo). O que aparece são **arestas de consistência**: quatro furos de **Alta** que merecem correção antes de apoiar mais operação (uma escrita financeira sem a área exigida, a tela de caixa que ignora o módulo, sinal de reserva pagável em dobro e salário exposto na trilha de auditoria), além de um padrão recorrente de **médias/baixas** — falta de `select_for_update` em check-then-write de estoque/caixa/comanda (corridas raras numa pousada de 24 quartos), inconsistências de gating de módulo (`@requer_modulo` ausente em algumas views de cancelamento) e endurecimento de webhooks/exports. A dívida se concentra em **concorrência** e **consistência de gating**, não em arquitetura: as correções são localizadas, de baixo risco e, em vários casos, de uma linha.

---

## 2. Achados por severidade

### 🔴 Crítica
*Nenhum achado nesta categoria.*

### 🟠 Alta

| Módulo | Lente | Achado | Correção |
|---|---|---|---|
| Caixa & Financeiro | Permissões | `conta_baixar` protegida só por `@login_required` — qualquer usuário autenticado baixa conta a pagar/receber (escrita financeira com lançamento) | Trocar por `@requer_area(Area.FINANCEIRO)`, alinhando às views irmãs; adicionar teste de 403 |
| Caixa & Financeiro | Funcional | Tela/ações de caixa não filtram por módulo — com 2+ caixas abertos (suportado por design), lança no caixa errado ou dá 500 no fechar (lockout) | Selecionar a sessão por `modulo`/pk; seletor de caixa no template; filtrar `SessaoCaixa(..., modulo=...)`; teste do cenário com dois caixas |
| Comercial | Dinheiro | Cobrança de sinal sem idempotência — reemitir gera links antigos órfãos ainda pagáveis (risco de pagamento em dobro) | Reaproveitar a cobrança de sinal pendente existente ou cancelar a anterior ao emitir nova |
| Auditoria | Permissões | Trilha expõe diffs sensíveis (salário) a quem só tem o módulo Auditoria, contornando `pode_ver_salario`/Area.REMUNERAÇÃO | Mascarar/filtrar campos sensíveis (`salario`) p/ quem não tem Area.REMUNERAÇÃO, ou adicioná-los a `CAMPOS_IGNORADOS` |

### 🟡 Média

| Módulo | Lente | Achado | Correção |
|---|---|---|---|
| Estoque (núcleo) | Disponibilidade | Saldo não-negativo só por check de aplicação sem lock — corrida permite saldo negativo | `select_for_update` por produto×local na baixa; idealmente saldo materializado + `CheckConstraint(qtd>=0)` |
| Estoque (núcleo) | Funcional | Inventário: contagem inválida descartada silenciosamente (`except (ValueError, Exception): pass`) | Validar com `Decimal`/`InvalidOperation`, acumular erros por item, trocar o except genérico |
| Permissões (núcleo) | Permissões | Concessão/revogação de **módulo** (M2M `Usuario.modulos`) não entra na trilha | Conectar `m2m_changed` ao through, ou `registrar_auditoria(antes/depois)` em `_aplicar_acesso_funcionario` |
| Reservas | Disponibilidade | View manual `nova` não checa bloqueio de Manutenção por datas — fura a disponibilidade (constraint só pega reserva×reserva) | Validar `services.uh_disponivel` antes de salvar, ou centralizar a criação manual num service |
| Loja | Disponibilidade | Venda pode levar estoque a saldo negativo sob concorrência (sem lock) | Serializar a baixa no motor de estoque (`registrar_saida`), não só na Loja |
| Lavanderia | Dinheiro | `entregar()` sem `select_for_update` — duplo POST cobra duas vezes (MovimentoCaixa duplicado/órfão) | Reler a ordem com `select_for_update` antes de checar `em_producao` |
| Governança | Funcional | `concluir_tarefa`/`iniciar_tarefa` sem guard de estado — concluir 2× re-dispara `faxina_concluida` e re-audita | Early-return/`ValidationError` se já concluída/em andamento |
| Escala | Permissões | `publicar`, `gerar_semana`, `decidir_troca` só com `@requer_gerencia` — módulo inativo não dá 404 | Empilhar `@requer_modulo(Modulo.ESCALA)` nas três (relatorio_colaborador já está correta); teste 404/403 |
| Escala | Funcional | `decidir_troca` reatribui sem re-checar unicidade/ausência → IntegrityError 500 ou escala a ausente | Revalidar ausência + duplicata e envolver em `try/except IntegrityError → ValidationError` |
| Comercial | Funcional | Conversão em reserva descarta composição adultos/crianças (passa total como adultos) | Passar `adultos=oportunidade.adultos`, `criancas=oportunidade.criancas` |
| Marketing | Dinheiro | Mês da verba travada é mutável após aprovação (`inicio` editável sem revalidar teto) | Congelar `mes_verba` na aprovação; bloquear/revalidar edição de `inicio` com fase ≥ APROVAÇÃO |
| Marketing | Dinheiro | `verba_prevista` aceita negativo — infla a verba disponível do mês | Validar `>= 0` em `parse_moeda`/salvar e em `_aplicar_aprovacao` |
| Fiscal | Permissões | `fiscal:cancelar` sem `@requer_modulo` — cancela com módulo FISCAL desligado | Adicionar `@requer_modulo(Modulo.FISCAL)` acima de `@requer_gerencia` |
| Fiscal | Permissões | Webhook fiscal sem autenticação quando `FISCAL_WEBHOOK_TOKEN` vazio (default) — fail-open | Exigir token obrigatório p/ gateway `focus`/`governo`; comparar com `hmac.compare_digest` |
| Fiscal | Funcional | Idempotência de NFS-e por conta é check-then-create sem constraint — duplica nota | `UniqueConstraint` parcial `(referencia, tipo)` excl. cancelada, ou `select_for_update` na conta |

### 🟢 Baixa

| Módulo | Lente | Achado | Correção |
|---|---|---|---|
| Caixa & Financeiro | Dinheiro | Sangria sem teto pode deixar esperado em dinheiro negativo | Validar `valor <= esperado_em_dinheiro()` em `clean()` (ou avisar) |
| Caixa & Financeiro | Dinheiro | Limite de estorno checado sem lock — estornos parciais concorrentes podem exceder o original | `atomic` + `select_for_update` na origem antes do aggregate |
| Estoque (núcleo) | Dinheiro | Custo médio ponderado é read-modify-write sem lock — corrida corrompe o custo | `select_for_update` no Produto no início de `registrar_entrada` |
| Reservas | Dinheiro | `receber_pagamento`/`receber_adiantamento` não são atômicos (diferente de `receber_folio_grupo`) | Decorar ambos com `@transaction.atomic` |
| Reservas | Dinheiro | `receber_pagamento` aceita valor acima do saldo (overpayment) e trava o check-out | Validar `valor <= saldo`, ou `saldo() <= 0` em `fazer_checkout` |
| Reservas | Funcional | Trava de FNRH burlada com reserva de 0 hóspedes | Validar `adultos >= 1` no `clean()` da Reserva/Form |
| Loja | Cross-module | `destino=conta` não verifica se Reservas está ativo (degradação graciosa incompleta) | `if not modulo_ativo(Modulo.RESERVAS): raise ValidationError` no ramo conta |
| Loja | Dinheiro | Cancelamento estorna na sessão de origem — impossível cancelar após fechar o caixa | Definir política: estornar na sessão atual, ou mensagem orientadora clara |
| Restaurante | Dinheiro | Desconto na conta do quarto abate tudo como CONSUMO (distorce base serviço×consumo) | Ratear o desconto por natureza |
| Restaurante | Disponibilidade | Devolução de estoque por ajuste absoluto é sujeita a corrida (dupla leitura de saldo) | Usar movimento relativo de entrada/estorno, não alvo absoluto |
| Restaurante | Funcional | `transferir_mesa` não valida mesa (None salva sem ponto com falso sucesso) | Validar `nova_mesa` não-nula e ≠ atual → `ValidationError` |
| Restaurante | Dinheiro | Fechamento no caixa não é idempotente contra duplo-submit | `select_for_update` da comanda, ou update condicional do status |
| Lavanderia | Permissões | View `cancelar` só com `@requer_gerencia` (padrão sistêmico em loja/restaurante/manutenção) | Empilhar `@requer_modulo` + `@requer_gerencia` (idealmente nos 4 módulos) |
| Lavanderia | Funcional | Views de rouparia estouram 500 com quantidade/mínimo não-numérico | Tratar `ValueError` na conversão de entrada |
| Escala | Funcional | View `atribuir` com data inválida/ausente → exceção não tratada (500) | Validar `data is None` cedo (400/mensagem de erro) |
| Marketing | Dinheiro | Aprovação sem lock/revalidação atômica — teto do mês estourável por concorrência | Serializar por mês com `select_for_update` + revalidar antes de gravar |
| Marketing | Dinheiro | Fallback do mês diverge entre validação e leitura quando `inicio` é nulo | Setar `aprovada_em` antes de computar o mês, ou congelar `mes_verba` |
| Marketing | Dinheiro | Reabrir campanha encerrada deixa a verba sub-reservada | Re-travar `verba_prevista` (revalidando teto) ao sair de ENCERRADA, ou bloquear o retrocesso |
| Marketing | Cross-module | `ocupacao_x_campanha` usa Reservas sem declarar dependência nem degradar | Guardar `modulo_ativo(Modulo.RESERVAS)`, ou declarar dependência em `DEPENDENCIAS` |
| Fiscal | Funcional | `processar_retorno_focus` faz `save()` completo mesmo sem casar status (polui numero/chave) | Só persistir quando o status for reconhecido; evento informativo p/ intermediário |
| Auditoria | Funcional | Export CSV vulnerável a CSV/formula injection (vetor estreito; `frase` já prefixa verbo) | Prefixar células que iniciam com `= + - @` com `'`; padronizar nos exports do CRM |
| Auditoria | Funcional | CSV grava `detalhe` como dict Python cru (não JSON, não reimportável) | `json.dumps(detalhe, ensure_ascii=False)` ou omitir a coluna |
| Auditoria | Cross-module | `varrer()` sem try/except por módulo — um `pendencias_auditoria()` quebrado derruba o painel | Envolver cada chamada em try/except, logar e seguir |

### ⚪ Informativo

| Módulo | Lente | Achado | Correção |
|---|---|---|---|
| Permissões (núcleo) | Permissões | IP da trilha confia cegamente em `X-Forwarded-For` | Documentar premissa (sempre atrás de proxy) ou usar N-ésimo-da-direita |
| Permissões (núcleo) | Permissões | Dupla checagem de `modulo_ativo` em `requer_modulo` (redundância, não bug) | Micro-otimização opcional (cache por request); comportamento 404-antes-de-403 está correto |
| Governança | Funcional | `nova_tarefa` confia no `tipo` do POST sem validar choices | Validar `tipo in Tipo.values` (cair no default), como já faz `status_marcar` |

---

## 3. Top 5 a corrigir primeiro

Priorizando **dinheiro → disponibilidade → permissões**, com impacto × esforço:

1. **[Permissões/Dinheiro] `conta_baixar` sem `@requer_area(Area.FINANCEIRO)`** (Alta) — escrita financeira privilegiada (quita título + gera lançamento) aberta a qualquer usuário autenticado. **Correção de uma linha** no decorator + teste. Maior retorno por menor esforço.

2. **[Dinheiro] Caixa ignora o módulo** (Alta) — risco duplo: lançar na gaveta errada (integridade de dinheiro) **e** 500 no fechamento travando operação crítica, num estado (2+ caixas) que o próprio design permite. Exige ajuste de view + template (seletor de caixa).

3. **[Dinheiro] Sinal comercial sem idempotência** (Alta) — caminho real de pagamento em dobro + links órfãos pagáveis. Reaproveitar/cancelar a cobrança pendente antes de emitir nova.

4. **[Permissões/LGPD] Salário exposto na trilha de Auditoria** (Alta) — contorna um controle de confidencialidade que o projeto trata como exceção explícita (flag Remuneração acima até de gerentes). Mascarar campos sensíveis ou excluí-los do diff.

5. **[Disponibilidade] Reserva manual fura bloqueio de Manutenção** (Média, promovida à prioridade) — único furo onde a regra "disponibilidade é dona do Reservas" não vale: quarto em reparo recebe hóspede. É a quebra de disponibilidade mais concreta do conjunto. Validar `uh_disponivel` na view `nova`.

> **Padrão transversal recomendado em seguida:** adotar `select_for_update` no **motor de estoque** (`registrar_saida`/`registrar_entrada`) e nos fechamentos/entregas de dinheiro (lavanderia, restaurante, estorno de caixa). Resolve de uma só vez ~8 achados de corrida Média/Baixa e aplica ao estoque/caixa o mesmo rigor de banco que o projeto já exige para overbooking.

---

## 4. Lacunas de cobertura conhecidas

Três módulos com invariantes relevantes ficaram **abaixo do patamar de confiança** na cobertura de testes:

- **Reservas (79%)** — concentra achados de disponibilidade (bloqueio de manutenção na view manual) e dinheiro (atomicidade de `receber_pagamento`/`receber_adiantamento`, overpayment travando check-out). São exatamente as áreas **mais sensíveis do produto** (disponibilidade + folio). Priorizar testes do caminho manual de criação de reserva e dos recebimentos atômicos.
- **Fiscal (78%)** — cinco achados (idempotência de NFS-e, webhook fail-open, gating de `cancelar`, `save` sem casar status). Mitigado hoje por ser **scaffold inativo por padrão** com gateway simulado, mas a dívida **vira exploável no exato caminho de produção** (Focus NFe) do roadmap. Não ligar o provider real sem fechar os quatro.
- **Lavanderia (78%)** — cobertura de caminho-feliz apenas; faltam testes de concorrência na entrega (dupla cobrança) e de entrada não-numérica na rouparia (500).
- **Governança (75%)** — a menor cobertura; os guards de estado (`concluir_tarefa` idempotente) e validação de `tipo` não são exercitados. O sinal `faxina_concluida` atravessa módulos (Lavanderia recolhe enxoval), então um re-disparo tem efeito colateral em livro-razão de outro módulo — merece teste de regressão.

**Nota geral:** nenhum dos achados de corrida tem teste de concorrência — esperado, pois exigem execução paralela real. A recomendação é tratá-los por **construção** (lock/constraint no banco) em vez de teste, seguindo a filosofia já adotada para o overbooking.


### Todos os achados confirmados (por severidade)


#### ALTA (4)

- **(nucleo-caixa/permissoes)** conta_baixar protegida só por @login_required — qualquer usuário baixa conta a pagar/receber
  - Evidência: apps/nucleo/views.py:982-988 — `@login_required` / `def conta_baixar(request, pk): ... conta.baixar(request.user)`. As views irmãs `contas` (957), `conta_form` (968) e `lancamento_form` (941) usam `@requer_area(Area.FINANCEIRO)`. URL expost
  - Correção: Trocar `@login_required` por `@requer_area(Area.FINANCEIRO)` em conta_baixar, alinhando com as demais views de contas/lançamentos. Opcional: adicionar teste de 403 para baixa sem a área.
- **(nucleo-caixa/funcional)** Tela/ações de caixa ignoram o módulo — quebram ou lançam no caixa errado com 2+ caixas abertos
  - Evidência: apps/nucleo/views.py:766-768 `SessaoCaixa.objects.filter(operador=request.user, status=ABERTA).first()`; 809-811 e 837-839 `get_object_or_404(SessaoCaixa, operador=request.user, status=ABERTA)` — nenhum filtra por `modulo`. O modelo e a doc
  - Correção: Incluir o módulo na seleção da sessão: a tela de caixa deve listar/selecionar o caixa (por módulo) e passar o módulo (ou o pk da sessão) em caixa_movimento/caixa_fechar, filtrando `SessaoCaixa.objects.filter(operador, modulo=..., status=ABERTA)`. Adicionar teste do cenário com dois caixas abertos.
- **(comercial/dinheiro)** Cobrança de sinal duplicável: nenhum guard de idempotência — links antigos ficam pendentes e pagáveis
  - Evidência: services.py:2013-2038 criar_cobranca_sinal cria SEMPRE nova Cobranca e faz Oportunidade...update(cobranca_sinal_id=cobranca.id) sem checar op.cobranca_sinal_id prévio; services.py:757-776 (converter_em_reserva, criar_sinal) idem — cria outr
  - Correção: Antes de criar, reaproveitar a cobrança de sinal pendente existente (buscar por op.cobranca_sinal_id com status=pendente e devolvê-la) OU cancelar a anterior pendente ao emitir a nova. Assim o lead nunca fica com dois links de sinal pagáveis para a mesma estadia (risco de pagamento em dobro na conciliação).
- **(auditoria/permissoes)** Trilha de auditoria expõe salários (e todo diff sensível) a quem só tem o módulo Auditoria, sem gate de gerência nem da área Remuneração
  - Evidência: apps/auditoria/views.py:43-45 — a view `trilha` usa apenas `@requer_modulo(Modulo.AUDITORIA)`; não há `@requer_gerencia` nem checagem de `pode_ver_salario`/Area.REMUNERACAO. A trilha renderiza o diff (`t.detalhe`) em templates/auditoria/tri
  - Correção: Reforçar o acesso da trilha: além de `@requer_modulo(AUDITORIA)`, exigir gerência (`@requer_gerencia`) — coerente com a doc 'acesso só gerência' — e/ou filtrar/mascarar diffs de campos sensíveis (ex.: `salario`) quando o usuário não tem Area.REMUNERACAO. Alternativamente, adicionar `salario` (e outros campos de remuneração) a CAMPOS_IGNORADOS da auto-auditoria em apps/nucleo/audit.py para que nunca entrem no diff da trilha.

#### MEDIA (15)

- **(nucleo-estoque/disponibilidade)** Saldo não-negativo é garantido só por check de aplicação sem lock — corrida permite saldo negativo
  - Evidência: apps/nucleo/models/estoque.py:280-288 registrar_saida: `if saldo(produto, local) < quantidade: raise ...` seguido de `_novo_movimento(..., -quantidade, ...)`. `saldo()` (linha 199-207) é um `aggregate(Sum('quantidade'))` sem `select_for_upd
  - Correção: Serializar a baixa por produto×local: travar as linhas do kardex com `MovimentoEstoque.objects.filter(produto=produto, local=local).select_for_update()` (ou um lock advisory / linha de saldo materializada) dentro da mesma transação atômica antes de ler o saldo e inserir a saída/transferência. Idealmente combinar com um saldo materializado por produto×local protegido por CheckConstraint(quantidade>=0) para defesa em profundidade. É o mesmo rigor que a especificação exige para overbooking (constraint no banco), aplicado ao invariante de estoque.
- **(nucleo-estoque/funcional)** Inventário: contagem inválida é silenciosamente descartada (except genérico)
  - Evidência: apps/estoque/views.py:242-250 — `item.quantidade_contada = valor.replace(',', '.')` seguido de `item.save(...)` dentro de `try/except (ValueError, Exception): pass`. Qualquer valor não numérico digitado pelo operador na contagem é engolido 
  - Correção: Validar a entrada explicitamente (Decimal(valor) com tratamento de InvalidOperation) e acumular mensagens de erro por item para avisar o operador quando a contagem não for gravada, em vez de `except (ValueError, Exception): pass`. Trocar o except genérico por exceções específicas (InvalidOperation/ValueError).
- **(nucleo-permissoes/permissoes)** Concessão/revogação de acesso a MÓDULO não entra na trilha de auditoria (M2M Usuario.modulos)
  - Evidência: apps/nucleo/views.py:1178 `u.modulos.set(modulos_ativos_qs.filter(codigo__in=set(request.POST.getlist("modulos"))))`; apps/nucleo/audit.py:48 `if getattr(modelo._meta, "auto_created", False): continue  # tabelas intermediárias (M2M) automát
  - Correção: Auditar explicitamente a mudança de módulos de um usuário: ou conectar `m2m_changed` ao through-table de Usuario.modulos em `conectar_auditoria_automatica()`, ou (mais simples e legível) chamar `registrar_auditoria(request.user, "alterar_acesso", u, {"modulos": [...], "areas": u.areas})` em `_aplicar_acesso_funcionario` logo após o `u.modulos.set(...)`/atribuição de areas, registrando antes/depois. A troca de `areas` (JSONField concreto) já é capturada pelo post_save de Usuario, mas a de módulos não — ficando uma mudança de permissão sensível invisível, contrariando o próprio CLAUDE.md ("inclui Usuario (mudança de permissão)").
- **(reservas/disponibilidade)** Reserva manual (view nova) não checa bloqueio de Manutenção por datas — fura a disponibilidade
  - Evidência: apps/reservas/views.py:253-277 (nova): só faz form.save() e captura IntegrityError da ExclusionConstraint; não chama services.uh_disponivel nem _uhs_bloqueio_manutencao. apps/manutencao/services.py:21-46 + 156-170: o bloqueio de Manutenção 
  - Correção: Na view nova (e no save manual), validar services.uh_disponivel(reserva.uh, checkin, checkout) antes de salvar — ou melhor, centralizar a criação manual também por um service que chame uh_disponivel, mantendo a constraint como última linha. Assim o invariante 'disponibilidade é dona' vale em todos os caminhos.
- **(loja/disponibilidade)** Venda pode levar o estoque a saldo negativo sob concorrência (sem lock de linha)
  - Evidência: apps/loja/services.py:45 `if saldo(produto, local) < qtd:` e apps/loja/services.py:71 `registrar_saida(...)`; apps/nucleo/models/estoque.py:199-207 `saldo` é um `Sum` agregado e estoque.py:280 revalida com o mesmo Sum — não há `select_for_u
  - Correção: No motor de estoque (registrar_saida/saldo), serializar a baixa por produto×local dentro da transação (ex.: lock de uma linha-âncora de LocalEstoque/Produto com select_for_update, ou CHECK/trigger de saldo não-negativo). A Loja já roda em @transaction.atomic; falta o lock que torne o check-then-write atômico contra vendas simultâneas do último item.
- **(lavanderia/dinheiro)** entregar() sem select_for_update permite duplo POST cobrar duas vezes
  - Evidência: apps/lavanderia/services.py:70-113 — `@transaction.atomic def entregar(...)` lê `ordem.em_producao` (linha 73) e depois cobra via receber_no_caixa/lancar_na_conta, mas a ordem foi carregada na view com get_object_or_404 sem lock (views.py:1
  - Correção: Reler a ordem com `OrdemLavanderia.objects.select_for_update().get(pk=ordem.pk)` no início de entregar (dentro do atomic) antes de checar em_producao, serializando a entrega e evitando dupla cobrança / MovimentoCaixa órfão no OneToOne movimento_caixa.
- **(governanca/funcional)** iniciar_tarefa/concluir_tarefa sem guard de estado — concluir duas vezes re-dispara faxina_concluida e re-audita
  - Evidência: apps/governanca/services.py:53-64 `def concluir_tarefa(tarefa, usuario=None): tarefa.status = ...CONCLUIDA; ...; registrar_auditoria(...); faxina_concluida.send(...)` — não verifica o status atual da tarefa. A view apps/governanca/views.py:
  - Correção: Guardar o estado antes de agir: em concluir_tarefa, retornar cedo (ou levantar ValidationError) se `tarefa.status == Status.CONCLUIDA`; idem em iniciar_tarefa se já em andamento/concluída. Assim o sinal faxina_concluida (que faz a Lavanderia recolher enxoval sujo via coletar_faxina) e o registro de auditoria só ocorrem uma vez por faxina. Hoje um duplo POST em 'concluir' recolhe o enxoval duas vezes e grava dois eventos de auditoria.
- **(escala/permissoes)** Views de escala só com @requer_gerencia, sem @requer_modulo — não dão 404 com módulo inativo nem exigem o módulo atribuído
  - Evidência: apps/escala/views.py:189-191 (publicar), :206-207 (gerar_semana), :145-146 (relatorio_colaborador), :325-326 (decidir_troca) — todos decorados apenas com @requer_gerencia / (@requer_gerencia @require_POST); nenhum tem @requer_modulo(Modulo.
  - Correção: Empilhar @requer_modulo(Modulo.ESCALA) acima de @requer_gerencia nessas quatro views (como já é feito em relatorio_colaborador... na verdade falta lá também). Assim módulo inativo → 404 e gerente sem o módulo atribuído → 403, igual ao resto do módulo. Cobrir com teste: gerente staff sem Modulo.ESCALA assinado recebe 404/403 em escala:publicar, escala:gerar, escala:decidir_troca, escala:relatorio.
- **(escala/funcional)** decidir_troca (aprovar) reatribui sem re-checar unicidade/ausência → IntegrityError 500 ou estado inconsistente
  - Evidência: apps/escala/services.py:599-612 decidir_troca: ao aprovar faz atrib.funcionario = troca.substituto; atrib.save(update_fields=["funcionario"]) — sem try/except, sem re-checar ausencia_no_dia(substituto, data) nem a UniqueConstraint escala_at
  - Correção: Em decidir_troca, antes de salvar quando aprovar: revalidar ausencia_no_dia(substituto, atrib.data) e a ausência de Atribuicao duplicada (turno, substituto, data) excluindo a própria; envolver em try/except IntegrityError → ValidationError (a view já trata ValidationError e vira message de erro). Opcional: @transaction.atomic.
- **(comercial/funcional)** Conversão em reserva descarta a composição adultos/crianças do lead (passa total como adultos)
  - Evidência: services.py:727 converter_em_reserva chama criar_prereserva(..., adultos=oportunidade.hospedes) e NÃO passa criancas; a Oportunidade tem campos distintos adultos/criancas (models.py:113-114, migração 0016 criada justamente para a regra do s
  - Correção: Passar adultos=oportunidade.adultos e criancas=oportunidade.criancas na chamada a criar_prereserva, em vez de empilhar hospedes todo em adultos — senão a reserva criada representa a capacidade/pricing errado (ex.: 2 adultos + 2 crianças vira 4 adultos).
- **(marketing/dinheiro)** Mês da verba travada é mutável após a aprovação (inicio editável sem revalidar o teto)
  - Evidência: services.py:54-58 _mes_de_campanha usa `c.inicio` como mês da verba travada; views.py:204-207 salvar_campanha grava `c.inicio = p.get('inicio') or None` sem qualquer guarda de fase. posicao_verba (services.py:76-79) soma verba_travada no mê
  - Correção: Congelar o mês de competência da verba no momento da aprovação (ex.: campo `mes_verba` gravado em _aplicar_aprovacao) e usar esse campo em posicao_verba/_mes_de_campanha; ou bloquear edição de `inicio`/`verba_prevista` enquanto fase >= APROVACAO (ou, ao editar inicio de uma campanha já aprovada, revalidar o teto do novo mês). Após aprovar, mover `inicio` para outro mês hoje realoca a reserva de orçamento para o teto de outro mês sem conferir disponibilidade.
- **(marketing/dinheiro)** verba_prevista aceita valor negativo (parse_moeda sem guarda de sinal) — infla a verba disponível do mês
  - Evidência: services.py:95-104 parse_moeda retorna Decimal sem validar sinal; views.py:208-212 salvar_campanha grava `c.verba_prevista = services.parse_moeda(...)`; _aplicar_aprovacao (services.py:355) só checa `verba_prevista > disponivel` (negativo p
  - Correção: Validar `verba_prevista >= 0` ao salvar e em _aplicar_aprovacao (e idealmente `definir_teto >= 0`). Uma verba_prevista negativa aprovada vira verba_travada negativa, que em posicao_verba reduz a travada do mês e aumenta a disponivel para outras campanhas.
- **(fiscal/permissoes)** fiscal:cancelar não checa módulo ativo — cancela documento com módulo FISCAL desligado
  - Evidência: apps/fiscal/views.py:74-84 — a view cancelar usa só @requer_gerencia (não @requer_modulo, diferente de painel/detalhe/emitir_nfse que têm @requer_modulo(Modulo.FISCAL)). urls.py:12 expõe '<int:pk>/cancelar/' sem guarda externa (config/urls.
  - Correção: Adicionar @requer_modulo(Modulo.FISCAL) na view cancelar (acima de @requer_gerencia), igual às demais views do app, para que módulo inativo retorne 404 de forma consistente.
- **(fiscal/permissoes)** Webhook fiscal fica sem autenticação quando FISCAL_WEBHOOK_TOKEN está vazio (default)
  - Evidência: apps/fiscal/views.py:55-71 — @csrf_exempt + 'esperado = getattr(settings, "FISCAL_WEBHOOK_TOKEN", "")' e 'if esperado and request.headers.get("Authorization") != esperado'. config/settings.py:310 FISCAL_WEBHOOK_TOKEN default ''. Com token v
  - Correção: Exigir token obrigatório quando o gateway for 'focus'/'governo' (recusar webhook se token vazio nesses casos), e comparar com hmac.compare_digest para evitar timing. No gateway 'simulado' o webhook não é usado — pode retornar 404/403.
- **(fiscal/funcional)** Idempotência de NFS-e por conta é check-then-create sem constraint — duplica nota em concorrência/duplo clique
  - Evidência: apps/fiscal/services.py:92-106 — monta ref='conta:{id}', faz DocumentoFiscal.objects.filter(referencia=ref, tipo=NFSE).exclude(CANCELADA).first() e só então chama emitir(); não há unique constraint em (referencia, tipo). O teste test_idempo
  - Correção: Adicionar UniqueConstraint parcial em DocumentoFiscal (referencia, tipo) excluindo status=cancelada, ou usar select_for_update()/get_or_create com lock na conta dentro da transação para serializar a emissão por conta.

#### BAIXA (23)

- **(nucleo-caixa/dinheiro)** Sangria sem teto: pode deixar o esperado em dinheiro negativo
  - Evidência: apps/nucleo/models/financeiro.py:197-304 — MovimentoCaixa não valida SANGRIA contra o saldo em dinheiro da sessão; `esperado_em_dinheiro()` (129-144) subtrai sangrias livremente. Uma sangria maior que o dinheiro em gaveta gera esperado nega
  - Correção: Em MovimentoCaixa.clean(), para SANGRIA validar `valor <= esperado_em_dinheiro()` da sessão (ou avisar). Decisão de negócio — a conferência cega acaba revelando, por isso baixa.
- **(nucleo-caixa/dinheiro)** Limite de estorno checado sem lock — race entre estornos parciais concorrentes
  - Evidência: apps/nucleo/models/financeiro.py:282-288 — `ja_estornado = origem.estornos.aggregate(Sum('valor'))` e compara `self.valor + ja_estornado > origem.valor` dentro de clean(), sem select_for_update nem constraint de banco. Dois estornos parciai
  - Correção: Envolver o estorno em transaction.atomic + `MovimentoCaixa.objects.select_for_update().get(pk=origem.pk)` antes de agregar, ou validar o teto numa constraint/transação serializável. Baixa por ser operação manual de gerência (concorrência rara).
- **(nucleo-estoque/dinheiro)** Custo médio ponderado é read-modify-write sem lock — corrida corrompe o custo de estoque
  - Evidência: apps/nucleo/models/estoque.py:258-264 registrar_entrada: lê `saldo_atual = saldo(produto)` e `produto.custo_medio`, calcula o novo médio e grava com `produto.save(update_fields=['custo_medio'])`. Sem `select_for_update()` na linha do Produt
  - Correção: Carregar o produto com `Produto.objects.select_for_update().get(pk=produto.pk)` no início de registrar_entrada (dentro da transação já existente) antes de ler saldo/custo e recalcular, serializando entradas concorrentes do mesmo produto. A mesma trava resolve, de quebra, o cálculo consistente do saldo_atual usado no ponderado.
- **(reservas/dinheiro)** receber_pagamento e receber_adiantamento não são atômicos (inconsistente com receber_folio_grupo)
  - Evidência: apps/reservas/services.py:619 (receber_pagamento) e :959 (receber_adiantamento) não têm @transaction.atomic; criam MovimentoCaixa em _receber_no_caixa e só depois PagamentoConta/Adiantamento. Já receber_folio_grupo (:792-793) É @transaction
  - Correção: Decorar receber_pagamento e receber_adiantamento com @transaction.atomic, igualando o padrão de receber_folio_grupo, para que MovimentoCaixa e PagamentoConta/Adiantamento nasçam juntos ou nenhum.
- **(reservas/dinheiro)** receber_pagamento aceita valor acima do saldo (overpayment) e trava o check-out
  - Evidência: apps/reservas/services.py:619-642 (receber_pagamento) só valida conta.aberta; não limita valor ao saldo. apps/reservas/models.py:333-336 (fazer_checkout) exige conta.saldo() != Decimal('0.00'); um pagamento acima do devido deixa saldo NEGAT
  - Correção: Validar valor <= saldo em receber_pagamento (ou permitir, mas tratar saldo<=0 como quitado no fazer_checkout usando saldo() <= 0 em vez de != 0), evitando travar a saída por excesso.
- **(reservas/funcional)** Trava de FNRH e diárias são burladas quando a reserva tem 0 hóspedes
  - Evidência: apps/reservas/models.py:236-246 (total_hospedes = adultos+criancas; fnrh_pronta usa len(completas) >= self.total_hospedes). adultos/criancas são PositiveSmallIntegerField e aceitam 0 (models.py:152-153). Com total_hospedes=0, basta um titul
  - Correção: Validar adultos >= 1 no clean() da Reserva (ou no ReservaForm), garantindo total_hospedes >= 1 e preservando o sentido da trava de FNRH e do cálculo de colchão.
- **(loja/cross_module)** Degradação graciosa incompleta: destino=conta não verifica se Reservas está ativo
  - Evidência: apps/loja/services.py:84-100 em destino CONTA faz `from apps.reservas import services as reservas` e usa `conta_aberta`/`lancar_na_conta` sem checar `Modulo.RESERVAS` ativo; a guarda só existe na view (apps/loja/views.py:52 `if request.user
  - Correção: No início do ramo destino=conta de finalizar_venda, verificar que o módulo Reservas está ativo/contratado (ex.: via modulo_ativo(Modulo.RESERVAS)) e levantar ValidationError amigável caso contrário, em vez de depender só de a view esconder a opção. Hoje um POST direto com destino=conta + conta_id válido lança na conta mesmo com Reservas desativado.
- **(loja/dinheiro)** Cancelamento estorna na sessão de origem — impossível cancelar depois do fechamento do caixa
  - Evidência: apps/loja/services.py:122-125 `estornar_movimento(venda.movimento_caixa, venda.movimento_caixa.sessao, ...)` usa a sessão ORIGINAL; apps/nucleo/models/financeiro.py:266-268 `clean()` rejeita movimento se `not self.sessao.aberta`. Como o can
  - Correção: Decidir a política: ou documentar que cancelar só é possível com o caixa de origem ainda aberto (mensagem clara ao operador), ou permitir estorno na sessão ATUAL do operador no módulo Loja (como receber_no_caixa acha a sessão aberta). Hoje o usuário recebe 'A sessão de caixa está fechada.' sem orientação, e vendas de dias anteriores ficam sem caminho de cancelamento. Observação: mesmo comportamento existe na view de estorno do núcleo (apps/nucleo/views.py:906-908), então é sistêmico; não há corrupção de dados.
- **(restaurante/dinheiro)** Desconto na CONTA do quarto não respeita a natureza fiscal dos itens (abate tudo como CONSUMO)
  - Evidência: apps/restaurante/services.py:102-105 — `reservas.lancar_na_conta(conta, "desconto", "consumo", "Restaurante: desconto", desconto, operador)` sempre usa natureza="consumo"; os itens são lançados cada um com a sua `item.natureza` (linha 99).
  - Correção: Se a comanda tiver itens de natureza SERVIÇO, o desconto único em natureza CONSUMO distorce o `totais_por_natureza` (base da NFS-e/NFC-e). Ratear o desconto por natureza (ou pelo menos abater da natureza predominante) para que os subtotais serviço×consumo da conta permaneçam corretos para o fiscal.
- **(restaurante/disponibilidade)** Devolução de estoque por ajuste absoluto (saldo + qtd) é sujeita a corrida — pode clobberar movimento concorrente
  - Evidência: apps/restaurante/services.py:63-66 (remover_item) e 122-125 (cancelar_comanda): `atual = saldo(item.produto, comanda.local)` e `ajustar(..., atual + item.quantidade, ...)`. `ajustar` recomputa a diferença sobre o saldo lido, sem lock de lin
  - Correção: A devolução deveria ser um movimento de ENTRADA/estorno relativo (ex.: `registrar_entrada`/movimento inverso de quantidade fixa), não um ajuste para valor absoluto calculado a partir de um `saldo()` lido fora de lock. Com ajuste absoluto, uma saída concorrente (outra comanda baixando o mesmo produto/local) entre o `saldo()` e o `ajustar()` é apagada pelo set absoluto. Usar movimento relativo elimina a corrida.
- **(restaurante/funcional)** transferir_mesa não é atômico e não registra auditoria/validação de mesa
  - Evidência: apps/restaurante/services.py:134-139 — `transferir_mesa(comanda, nova_mesa)` apenas faz `comanda.save(update_fields=["mesa"])`; a view (views.py:176) passa `Mesa.objects.filter(...).first()` que pode ser None, e nada impede transferir para 
  - Correção: Validar `nova_mesa` (não-nulo, ativo, diferente da atual) levantando ValidationError; a troca de ponto é operação de atendimento que outros fluxos (ex.: cancelamento) auditam — manter consistência registrando a transferência. Hoje nova_mesa=None salva comanda sem ponto silenciosamente.
- **(restaurante/dinheiro)** Fechamento no caixa não é idempotente contra duplo-submit (sem lock da comanda)
  - Evidência: apps/restaurante/services.py:69-112 — `fechar_comanda` checa `comanda.aberta` no início mas não faz `select_for_update()` da comanda; dois POSTs concorrentes em restaurante:fechar poderiam ambos passar pela checagem e criar dois MovimentoCa
  - Correção: Bloquear a comanda com `Comanda.objects.select_for_update().get(pk=...)` no início da transação (o decorator já é @transaction.atomic), ou usar update condicional no status, para impedir cobrança/lançamento duplicado em duplo clique/retry.
- **(lavanderia/permissoes)** View cancelar não checa módulo ativo nem acesso ao módulo (só gerência)
  - Evidência: apps/lavanderia/views.py:146 — `@requer_gerencia\ndef cancelar(request, pk):` enquanto todas as outras views usam `@requer_modulo(Modulo.LAVANDERIA)`. requer_gerencia (permissoes.py:36) só verifica eh_gerente, não chama modulo_ativo() nem p
  - Correção: Empilhar os dois decoradores: `@requer_modulo(Modulo.LAVANDERIA)` + `@requer_gerencia` em cancelar, igual ao padrão do restante do módulo, para que módulo inativo dê 404 e quem não tem o módulo dê 403 antes da checagem de gerência.
- **(lavanderia/funcional)** Views de rouparia estouram 500 com quantidade/mínimo não-numérico
  - Evidência: apps/lavanderia/views.py:219-243 rouparia_mover passa `qtd` a services que fazem `int(quantidade)` (services.py:147,159,162,183) — int('abc') levanta ValueError, mas o except só captura ValidationError (views.py:241). Idem rouparia_item: `i
  - Correção: Validar/converter a entrada com tratamento de ValueError (ex.: helper que devolve ValidationError amigável) nas views rouparia_mover e rouparia_item, como já é feito em servicos() (views.py:184 captura Exception).
- **(escala/funcional)** View atribuir com data inválida/ausente estoura IntegrityError não tratado (500)
  - Evidência: apps/escala/views.py:225-230: data = _data(request.POST.get("data")) — _data (views.py:20-24) devolve None para texto inválido/ausente; em seguida services.atribuir(turno, func, None, ...) (services.py:69-79) chama Atribuicao.objects.create
  - Correção: Validar data cedo: se data is None, messages.error / JsonResponse 400 antes de chamar o service; ou em services.atribuir levantar ValidationError('Informe a data.') quando data is None. Idem checar func/turno. Teste: POST sem campo data → mensagem de erro, não 500.
- **(marketing/dinheiro)** Aprovação sem lock de linha/revalidação atômica — teto do mês pode ser estourado por concorrência
  - Evidência: services.py:351-363 _aplicar_aprovacao lê `posicao_verba(mes)['disponivel']` e grava verba_travada sem select_for_update; avancar (services.py:380-389) abre transaction.atomic() mas sem travar linhas de Campanha.
  - Correção: Serializar a aprovação por mês: travar as campanhas do mês com select_for_update() dentro da transação antes de somar a travada e revalidar `verba_prevista <= disponivel` imediatamente antes de gravar. Sem isso, duas aprovações simultâneas podem cada uma ver disponível suficiente e juntas estourar o teto.
- **(marketing/dinheiro)** Fallback do mês na aprovação diverge entre validação e leitura quando inicio é nulo
  - Evidência: services.py:352-363 _aplicar_aprovacao calcula `mes = _mes_de_campanha(campanha)` ANTES de setar `aprovada_em` (linha 363); com inicio=None, _mes_de_campanha (services.py:57) cai em criado_em na validação, mas leituras posteriores (posicao_
  - Correção: Setar aprovada_em antes de computar o mês, ou congelar o mês de competência em campo próprio na aprovação. Se criado_em e aprovada_em caírem em meses diferentes e inicio ficar nulo, a verba é validada contra o teto de um mês e depois contabilizada no teto de outro, sem revalidação.
- **(marketing/dinheiro)** Reabrir campanha encerrada (retroceder p/ NOAR/PRODUCAO) deixa a verba sub-reservada
  - Evidência: services.py:385-386 ao encerrar faz `verba_travada = gasta` (devolve o não gasto); retroceder (services.py:398-406) só zera a verba quando desce abaixo de APROVACAO — voltar de ENCERRADA para NOAR mantém verba_travada=gasta, não re-trava o 
  - Correção: Ao retroceder de ENCERRADA para uma fase ativa (>= ESTRUTURACAO), re-travar `verba_travada = verba_prevista` (revalidando o teto) ou bloquear retrocesso a partir de ENCERRADA. Caso contrário a campanha reaberta fica com orçamento comprometido menor que o planejado.
- **(marketing/cross_module)** ocupacao_x_campanha depende de reservas sem declarar dependência nem degradar quando inativo
  - Evidência: services.py:826 `from apps.reservas.services import ocupacao_prevista` dentro de ocupacao_x_campanha, chamado pela view ocupacao (views.py:480-499); nucleo/modulos.py:33-41 DEPENDENCIAS não lista nada para Modulo.MARKETING (não depende de R
  - Correção: Ou declarar a dependência de Reservas em DEPENDENCIAS, ou guardar `modulo_ativo(Modulo.RESERVAS)` em ocupacao_x_campanha/na view e exibir estado vazio quando inativo. Hoje a tela de ocupação consome dados de Reservas mesmo para um cliente que não contratou o módulo (quebra da degradação graciosa; não derruba por ser o mesmo banco, mas vaza função de módulo não contratado).
- **(fiscal/funcional)** processar_retorno_focus faz doc.save() completo mesmo quando o status do webhook não casa nenhum ramo
  - Evidência: apps/fiscal/services.py:126-148 — doc.numero/chave/pdf_url/xml_url/payload são sobrescritos a partir do payload antes do if/elif de status; se status não for autorizado/cancelado/erro (ex.: 'processando' ou vazio), nenhum EventoFiscal é cri
  - Correção: Só persistir (e sobrescrever campos) quando o status for reconhecido; para status intermediário/desconhecido, registrar EventoFiscal informativo e não alterar numero/chave definitivos, ou retornar sem save.
- **(auditoria/funcional)** Export CSV da trilha é vulnerável a CSV/formula injection (dados controlados pelo usuário não são neutralizados)
  - Evidência: apps/auditoria/views.py:52-56 — `w.writerow([... frase(t), t.acao, t.alvo, t.alvo_id, t.detalhe])`. Campos como `frase(t)` e `t.detalhe` embutem texto livre vindo do domínio (nomes de Pessoa, descrições de movimento, motivos de estorno/canc
  - Correção: Sanitizar cada célula de texto antes de escrever: se o valor começar com um de `= + - @ \t \r`, prefixar com `'` (aspa simples) ou usar um helper comum de export seguro. Aplicar em todas as colunas de texto (frase, acao, alvo, detalhe). Vale padronizar com os demais exports CSV do CRM.
- **(auditoria/funcional)** CSV da trilha grava `t.detalhe` como dict Python cru numa coluna, fugindo da promessa 'nunca JSON/estrutura crua' e dificultando o consumo
  - Evidência: apps/auditoria/views.py:55 escreve `t.detalhe` (um JSONField, dict em runtime) direto na célula 'detalhe'. O csv.writer fará `str(dict)` → `{'valores': {...}}` com aspas simples Python, não JSON. A UI (trilha.html:64) deliberadamente mostra
  - Correção: Serializar com `json.dumps(t.detalhe, ensure_ascii=False)` (depois de sanitizar para CSV injection) ou omitir a coluna detalhe se a frase já cobre a narrativa. Mantém o CSV consistente e parseável.
- **(auditoria/cross_module)** varrer() não protege contra exceção de um pendencias_auditoria() de módulo quebrado — uma falha derruba todo o painel
  - Evidência: apps/auditoria/services.py:70-87 — cada `achados += pendencias_auditoria()` é chamado sem try/except. Se qualquer módulo dono (reservas/manutencao/restaurante/lavanderia/fiscal/comercial) lançar exceção dentro do seu pendencias_auditoria (e
  - Correção: Envolver cada chamada de módulo em try/except, logando o erro e seguindo (eventualmente adicionando um achado 'varredura de <modulo> falhou'). Mantém a degradação graciosa prometida no docstring do módulo.

#### INFO (3)

- **(nucleo-permissoes/permissoes)** IP da trilha confia cegamente em X-Forwarded-For (sem proxy confiável configurado)
  - Evidência: apps/nucleo/audit.py:75-79 `_ip_da_requisicao`: `xff = request.META.get("HTTP_X_FORWARDED_FOR"); if xff: return xff.split(",")[0].strip()` — usa o primeiro elemento do header enviado pelo cliente, sem validar contra uma lista de proxies con
  - Correção: Em produção atrás do proxy da Railway isso é aceitável, mas o IP gravado na auditoria é falsificável se o app algum dia ficar acessível diretamente. Opcional: documentar a premissa (sempre atrás de proxy) ou usar `settings` para o número de proxies confiáveis e pegar o N-ésimo-da-direita em vez do primeiro-da-esquerda. Apenas endurecimento da trilha, não quebra funcional.
- **(nucleo-permissoes/permissoes)** Dupla checagem de modulo_ativo em requer_modulo (redundância, não bug)
  - Evidência: apps/nucleo/permissoes.py:54-56 `if not modulo_ativo(codigo): raise Http404(...)` seguido de `if not request.user.pode_acessar(codigo)`, e pode_acessar (usuarios.py:41) começa com `if not modulo_ativo(codigo): return False` — duas queries a
  - Correção: Comportamento correto (404 antes de 403 é o desejado). Apenas uma micro-otimização possível: a segunda consulta a modulo_ativo dentro de pode_acessar é redundante quando chamado pelo decorator. Sem impacto de correção; pode-se ignorar ou cachear por request se houver pressão de performance.
- **(governanca/funcional)** nova_tarefa confia no campo 'tipo' vindo do POST sem validar contra as choices
  - Evidência: apps/governanca/views.py:30-31 `tipo = request.POST.get('tipo') or TarefaGovernanca.Tipo.FAXINA; services.abrir_faxina(uh, tipo=tipo, ...)`. O campo `tipo` tem max_length=16 e o maior valor válido tem 15 chars; choices não são impostas pelo
  - Correção: Validar `tipo` contra `TarefaGovernanca.Tipo.values` antes de chamar abrir_faxina (cair no default FAXINA se inválido). Evita criar tarefa com tipo fora das choices e evita DataError no Postgres se vier string >16 chars.

## Próximos passos

1. **Re-auditar os 6 módulos travados** (pagamentos, site, manutenção, portal, conciliação, +1) — agentes estagnaram, sem achados.
2. **Corrigir as 4 ALTAS primeiro** — 2 no Caixa (permissão `conta_baixar` + sessão por módulo), Comercial (sinal idempotente), Auditoria (salário na trilha).
3. Varrer as MÉDIAS de concorrência (`select_for_update` em estoque/loja/lavanderia) e o gating de módulo (escala/fiscal).
4. Fluxos-mestre E2E #2–#5.



## Re-auditoria dos 6 módulos travados (03/10/2026)

6 módulos · **18 confirmados** (de 19) · {'alta': 2, 'media': 7, 'baixa': 8, 'info': 1}


#### ALTA (2)

- **(pagamentos/dinheiro)** View interna `simular` confirma pagamento SEM checar sandbox — burla a fonte da verdade em produção
  - Correção: Guardar a rota atrás do sandbox: no início de `simular`, se `getattr(settings, "PAGAMENTOS_GATEWAY", "simulado") != "simulado"` retornar erro/404 (mesma proteção que `pagar` já consulta em views.py:234). Opcionalmente exigir `@requer_gerencia`. O botão do template já deve aparecer só em sandbox, mas a view precisa barrar por conta própria.
- **(conciliacao/dinheiro)** Recebimento estornado continua no pool de conciliação bancária (concilia crédito que não existe no banco)
  - Correção: Excluir do pool os recebimentos com estorno associado, ex.: .exclude(estornos__isnull=False) (related_name=estornos em MovimentoCaixa.movimento_origem) e não oferecer movimentos tipo=ESTORNO. Aplicar em conciliar_banco, conciliar_cartao, candidatos_para_extrato e candidatos_para_cartao.

#### MEDIA (7)

- **(pagamentos/dinheiro)** Liquidação (valor_liquido/taxa) gravada a partir do corpo do webhook sem verificação na fonte
  - Correção: Fora do sandbox, não aceitar valores de liquidação do corpo: ou buscar os dados de settlement via consultar_status/relatório de vendas do gateway, ou aceitar só a liquidação por conferência manual (view `liquidar`, que já existe). No mínimo, só registrar liquidação por webhook quando o gateway for autenticável e os números vierem de endpoint consultado, não do payload recebido.
- **(site/dinheiro)** Desconto Pix só existe no recibo do site; não é propagado ao CRM (fonte da verdade da conta)
  - Correção: Passar o valor_diaria com desconto para criar_reserva_site/criar_reserva_site_unidade (ex.: valor_diaria líquido) OU registrar o desconto Pix como lançamento/adiantamento no CRM, para a conta refletir o valor realmente cobrado. Hoje o desconto vive só no canal e some na reconciliação.
- **(manutencao/permissoes)** cancelar OS não respeita 'módulo inativo → 404' nem checa acesso ao módulo
  - Correção: Empilhar os dois decorators na view cancelar: `@requer_modulo(Modulo.MANUTENCAO)` + `@requer_gerencia` (módulo inativo → 404; sem gerência → 403), mantendo o padrão das outras ações sensíveis do módulo.
- **(portal/funcional)** pedir_restaurante não é atômico: falha no meio do loop deixa comanda órfã + baixa de estoque parcial
  - Correção: Envolver pedir_restaurante em @transaction.atomic (do django.db import transaction) para que qualquer ValidationError de adicionar_item reverta a comanda e todas as saídas de estoque já feitas; ou revalidar saldo de todos os itens antes de abrir a comanda. Alinhar com o padrão dos demais services (adicionar_item/remover_item já usam @transaction.atomic).
- **(conciliacao/dinheiro)** Conciliação de cartão com usuario=None marca CONCILIADO sem lançar a taxa (líquido não bate no banco)
  - Correção: Usar usuário de sistema quando usuario for None, ou exigir usuario (ValidationError) antes de conciliar quando houver taxa > 0; nunca marcar CONCILIADO sem registrar a taxa.
- **(conciliacao/funcional)** Dedupe do OFX só ocorre se a conta for informada — reimportar sem conta duplica todas as linhas
  - Correção: Deduplicar por FITID globalmente (ou por banco) mesmo sem conta, ou tornar a conta obrigatória; alternativamente unique por (banco, conta, fitid) atravessando extratos.
- **(relatorios/cross_module)** rel_faturamento_modulos importa models internos de outros módulos (viola a própria regra de arquitetura e o docstring do arquivo)
  - Correção: Expor um service público em cada módulo (ex.: loja.services.faturamento_periodo(ini, fim) -> {caixa, quarto}; idem restaurante/lavanderia; reservas.services já poderia dar diárias do período) e consumir esses services, mantendo o relatório desacoplado como os outros.

#### BAIXA (8)

- **(pagamentos/funcional)** `cancelar` não é atômico (duas escritas fora de transação)
  - Correção: Decorar `cancelar` com `@transaction.atomic` para casar o save do status com o EventoPagamento, igual às demais mutações do módulo.
- **(site/funcional)** Código da reserva do site colide em criações no mesmo minuto (unique + precisão de minuto) → 500
  - Correção: Gerar o código com entropia (sufixo aleatório curto ou segundos+random) ou capturar IntegrityError e regenerar em loop. Como `finalizar_reserva` é @transaction.atomic, a falha hoje faz rollback da pré-reserva do CRM junto (não deixa órfã), mas devolve 500 ao hóspede em vez de concluir.
- **(manutencao/dinheiro)** Custos de mão de obra/peças aceitam valores negativos
  - Correção: Validar custo_maodeobra >= 0 e custo_pecas >= 0 em concluir_os (ou MinValueValidator(Decimal('0')) no model), rejeitando negativos com ValidationError.
- **(portal/funcional)** Ações públicas por token sem rate-limit (spam de faxina/OS/comanda)
  - Correção: Aplicar limite_excedido(request, 'portal_acoes', ...) por IP/token nas views de ação pública (pedir/solicitar), como já feito em checkin, para conter abuso/duplo-clique. Opcionalmente deduplicar solicitações de limpeza/manutenção já abertas e pendentes para a mesma UH.
- **(conciliacao/dinheiro)** Vínculo de conciliação sem unicidade no banco — corrida pode ligar o mesmo movimento/conta a duas linhas
  - Correção: Adicionar UniqueConstraint parcial em LancamentoExtrato.movimento_caixa, LancamentoExtrato.conta e TransacaoCartao.movimento_caixa (condition=isnull=False), ou usar select_for_update nos candidatos. Baixo risco mono-operador, mas é a única barreira de idempotência real.
- **(conciliacao/funcional)** conciliar_banco usa criado_em.date() em UTC sem localtime — pode deslocar o dia na janela
  - Correção: Usar timezone.localtime(m.criado_em).date() ao montar os itens do CRM.
- **(relatorios/dinheiro)** Reconciliação "lançado no quarto = o que a recepção coleta" é afirmada como igualdade exata, mas usa base accrual com timestamps heterogêneos e cobertura incompleta
  - Correção: Reformular o docstring para deixar claro que é faturamento por competência/accrual (o que foi vendido no período), não a batida de caixa; se a intenção é conciliar com a gaveta da recepção, somar diretamente os LancamentoConta de todos os tipos de débito do folio (ou os MovimentoCaixa do check-out) em vez de reconstruir setor a setor por carimbos distintos.
- **(relatorios/funcional)** CSV de relatórios usa delimitador vírgula sem BOM — diverge do padrão do projeto (BOH usa ; + BOM para Excel pt-BR)
  - Correção: Alinhar ao padrão do BOH: escrever BOM (resp.write('﻿') / codificação utf-8-sig) e usar csv.writer(resp, delimiter=';') para abrir corretamente no Excel pt-BR.

#### INFO (1)

- **(manutencao/funcional)** Recorrência de preventiva usa 30 dias por mês (deriva do calendário)
  - Correção: Usar aritmética de mês real (ex.: dateutil.relativedelta(months=n) ou cálculo manual de ano/mês preservando o dia) em vez de 30*N dias.


## Correções aplicadas — as 6 ALTAS (03/10/2026) ✅

- **nucleo/conta_baixar**: `@login_required`→`@requer_area(Area.FINANCEIRO)` (+teste 403).
- **nucleo/caixa por módulo**: views selecionam a sessão por módulo (sem 500 com 2+ caixas), seletor no template (+teste).
- **comercial/sinal idempotente**: cancela o sinal pendente anterior antes de reemitir (+teste).
- **auditoria/salário**: trilha redige o valor de `salario` p/ quem não tem Area.REMUNERAÇÃO (helper `redigir_sensiveis`, +3 testes).
- **pagamentos/simular**: barra confirmação manual fora do sandbox (+2 testes).
- **conciliacao/estorno**: recebimento totalmente estornado sai do pool (`_sem_estornados`, parcial permanece; +teste).

**Pendente (médias/baixas):** concorrência (`select_for_update` em estoque/loja/lavanderia), gating de módulo (escala/fiscal), liquidação por webhook sem verificação na fonte (pagamentos), estorno PARCIAL na conciliação (hoje só o total sai do pool). Suíte: 727 testes OK.


## Correções — médias de dinheiro/concorrência (03/10/2026) ✅

12 médias atacadas, cada uma com teste onde determinístico:

**Concorrência (lock/serialização):**
- **estoque** `registrar_saida`: `select_for_update` por produto×local — sem corrida pra saldo negativo (corrige loja e todos os PDVs na raiz).
- **lavanderia** `entregar`: `select_for_update` na ordem — duplo POST não cobra 2×.
- **fiscal** `emitir_nfse_da_conta`: lock da conta — não duplica NFS-e em duplo clique.
- **governança** `concluir_tarefa`/`iniciar_tarefa`: guard de estado (idempotente) — não re-dispara sinal/auditoria.

**Correção de dinheiro:**
- **marketing**: `verba_prevista` nunca negativa; `inicio`/`verba` congelados após a aprovação (mês do teto não remexe).
- **pagamentos**: liquidação (líquido/taxa) do webhook só no sandbox — fora dele vem de conferência/provedor, não do corpo forjável.
- **conciliação**: recebimento totalmente estornado fora do pool (feito antes); `conciliar_cartao` sem operador usa usuário de sistema (taxa sempre lançada); dedupe do OFX por FITID sempre (banco+conta), mesmo sem conta.
- **site**: desconto Pix propagado para a diária da pré-reserva no CRM (fonte da verdade), não só no recibo.
- **reservas**: view `nova` valida `uh_disponivel` (bloqueio de manutenção por datas) antes de salvar.

Suíte: **732 testes OK**. Pendentes do audit = médias/baixas não-dinheiro (ex.: conversão descarta composição adultos/crianças, gating de módulo em escala) + baixas.

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

## Achados

| # | Sev | Módulo | Achado | Status |
|---|---|---|---|---|
| A1 | info | reservas | **Invariante confirmado:** check-out recusa com saldo em aberto ("receba ou ajuste antes"). | OK (esperado) |
| A2 | baixa | reservas | `ContaHospedagem.total_por_natureza()` indexa pela **label** ("Consumo"/"Serviço"), frágil para chamada programática. Considerar chavear pelo value. | aberto |
| A3 | info | — | Cobertura 80%; **frigobar/services 39%** é o maior buraco — priorizar. | aberto |

_Próximos: implementar fluxos-mestre #2–#5 e varrer as lentes por módulo, começando por Frigobar (cobertura) e pelos fluxos de dinheiro._

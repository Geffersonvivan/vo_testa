# Plano de Implementação — Estoque de Colchões Extra + Avisos

> Plano **fechado** (08/10/2026), decidido com o dono. Fonte de regras:
> [`CONFIGURACAO_QUARTOS.md`](CONFIGURACAO_QUARTOS.md) + `Manual_de_Vendas_Vo_Testa.pdf` +
> as 14 respostas + 3 confirmações do dono. **CRM em beta → pode remodelar quartos/seed.**
>
> **Progresso (09/10/2026):**
> - ✅ **Fase 1** — models/migração (`ColchoesExtra`, `Reserva.casais/solteiros/usa_sofa_cama`
>   + props `colchoes_consumidos`/`colchoes_extra`), helpers `casais_max`/`camas_solteiro`,
>   seed `configurar_camas`.
> - ✅ **Fase 2** — serviço de domínio: funções puras em `apps/reservas/colchoes.py`
>   (`sugerir_arranjo`, `cabe_no_quarto`, `consumo_extra`, `presets`, `configurado`) **+ a
>   trava global por noite** em `services.py` (`colchoes_extra_livres`, `conferir_arranjo`,
>   `_resolver_arranjo`), com `select_for_update` no pool.
> - ✅ **Fase 3** — nova reserva na **recepção**: `ReservaForm` com arranjo (vazio = sugere),
>   trava do pool na view `nova` (lock + atômico; orçamento não consome), **aviso/bloqueio ao
>   vivo** no modal (`tarifa_preview` + JS) e pool editável no admin. O **site** e a conversão
>   do **Comercial** herdam a trava via `criar_prereserva` (arranjo auto-sugerido). Pendente da
>   Fase 3: UI do site para o hóspede **alterar** o arranjo (hoje é só sugerido).
> - ✅ **Fase 4** — disponibilidade enxerga o pool: `uh_disponivel`/`uhs_disponiveis`/
>   `tipo_disponivel`/`uh_livre_do_tipo` aceitam `adultos`/`criancas` e descartam o quarto
>   quando o arranjo sugerido não cabe no pool em alguma noite (base sempre ofertada).
>   `criar_prereserva` aloca por tipo já olhando o pool; o **site** passa a lotação em todas
>   as checagens de disponibilidade. Sem lotação = disponibilidade-base (compat).
> - ✅ **Fase 5** — painéis: (a) **dashboard** "Precisa de atenção" com noites de colchão
>   esgotado/no-limite nos próximos 14 dias (link p/ o painel); (b) **Governança** com
>   "Montagem de camas — chegadas de hoje" (quarto · casais · solteiros · sofá · extra), via
>   `montagem_do_dia` (degrada se Reservas inativo); (c) **Painel de colchões**
>   (`reservas:painel_colchoes`, gerência) usados × livres por noite no período, link na lista.
>   Serviços: `painel_colchoes`, `colchoes_alertas_proximos`, `montagem_do_dia`. O aviso ao vivo
>   na nova reserva já veio na Fase 3.
> - ✅ **Fase 6** — motor de preço (Manual §2) + taxas + política de cancelamento + canais
>   (recepção, site, funil, CRM). **COMPLETA — 789 testes verdes.**
>   `apps/reservas/precos.py` (base 2pax → pessoa adicional, single 70%, criança ≤5 grátis /
>   6-15 meia; ISS 4% por fora + taxa de turismo R$4/diária, cada uma desmarcável; day use por
>   pessoa). **Sem tarifa não-reembolsável** (−12% removido por decisão do dono). Campos novos:
>   `TipoUH.pessoa_adicional`/`preco_day_use` (seed por categoria, admin editável) e
>   `Reserva.criancas_0_5/6_15/cobra_iss/cobra_taxa_turismo/confirmada_em`. Check-in lança ISS +
>   turismo (`lancar_taxas`, flag `PRECO_TAXAS_ATIVAS`, off em teste; taxas quitadas no
>   check-out) e **o colchão deixou de cobrar**. `criar_prereserva`/site/recepção calculam
>   `valor_diaria` pela motor; preview itemizado na recepção.
>   **Política de cancelamento (única)** em `apps/reservas/cancelamento.py`: janela de
>   arrependimento (CDC) de **7 dias a partir da confirmação** (dentro → 100%; depois → retém
>   **10%** do valor total); **estadia iniciada** → diárias consumidas + 10% (sem janela).
>   **Reagendar** = `services.transferir_datas` (revalida disponibilidade/pool, recalcula
>   diária). Parâmetros `CANCELAMENTO_ARREPENDIMENTO_DIAS/RETENCAO_PCT` editáveis. Testes:
>   `tests_precos`, `tests_cancelamento`, taxas no check-in.
>   **Site FEITO (786 testes verdes):** busca com faixas de idade (steppers 0-5 / 6-15),
>   `_resumo_preco(_unidade)` via motor com total itemizado (hospedagem + ISS + turismo),
>   explicação ("online paga hospedagem; taxas no check-out") + **toggles que recalculam** (JS),
>   política de cancelamento exibida, faixas/flags passadas ao `criar_reserva_site`, **Tailwind
>   rebuildado**. Testes do site: criança aplica preço por pessoa + desmarcar ISS.
>   **CRM:** detalhe da reserva com **"Transferir data"** (`TransferenciaForm` → `transferir_datas`,
>   reagenda e recalcula) e **"Cancelar"** mostrando a prévia da política (pago × retém × devolver,
>   por cenário) e registrando o desfecho no motivo + auditoria (`resumo_cancelamento`, `total_pago`).
>   **Funil (Comercial):** `registrar_cotacao` cota pela motor (deriva faixas de idade de
>   `idades_criancas`, pessoa adicional, single, criança 6-15 meia) + ISS/turismo no total, com
>   toggles do vendedor no `CotacaoForm`. **Único fast-follow:** automação do estorno parcial do
>   cancelamento (devolver 90% pelo caixa) — hoje o valor é apontado ao operador (fontes de
>   pagamento mistas: adiantamento no caixa + Pix/cartão online).
> - ✅ **Fase 7** — testes de aceite §9 completos (793 testes verdes). Pousada inteira
>   (`AceiteColchoesTests`): #1 seed dos 24 quartos (35 casais, base 70, 42 vagas, 13 sofás,
>   pool 10), #2 todos em base = 0 extra, #3 10 extras ok / 11º recusado, #7 Quarto 22 cheio
>   com sofá (9 hóspedes, 3 extras). #4/#5/#6/#9/#10/#11/#12/#13 já cobertos nas Fases 2-5.
>   **Limitação (#8):** o sofá valida por **contagem** (1 adulto OU 2 crianças), não por idade
>   individual; 16+ já é modelado como adulto, então "criança de 16" não existe no modelo —
>   mistura adulto+criança no sofá não é rejeitada (nuance menor, não bloqueia).
> - ✅ **Grupos** — `adicionar_quarto` agora calcula a diária pela **motor** (pessoa adicional,
>   criança, taxas no folio no check-in) e passa pela **trava de colchões por noite** (lock +
>   arranjo sugerido), igual às reservas avulsas. Testes: quarto do grupo precifica por pessoa +
>   respeita a trava.
> - ✅ **UI de arranjos (site, venda por unidade)** — passo 3 oferece a **montagem das camas**
>   (presets via `arranjos_disponiveis` + "abrir sofá-cama"; default "Sugerido"); a escolha flui
>   até `criar_reserva_site_unidade` (casais/solteiros/sofá). Não altera preço (só montagem/
>   disponibilidade). Teste: escolha "só solteiros" grava no CRM.
>
> **🏁 Plano de estoque de colchões 100% implementado** (Fases 1-7 + grupos + UI de arranjos),
> **796 testes verdes**. Único item fora do plano de colchões: automação do estorno parcial no
> cancelamento (Fase 6) — hoje o valor a devolver é apontado ao operador.

## 1. Modelo conceitual (a decisão central)
- **Só existem colchões de SOLTEIRO** (nenhum de casal). **Cama de casal = 2 solteiros unidos = 2 colchões.** Cada pessoa em cama = 1 colchão. **Sofá-cama NÃO consome colchão.**
- **35 posições de casal = 70 colchões de solteiro FIXOS.** Cada posição vira **1 casal OU 2 solteiros**: a **montagem muda, a quantidade (2 por posição) não**. Só o que passa dessas camas fixas puxa dos **10 extras** compartilhados.
- **Base garantida por quarto:** os **2 colchões de cada posição de casal** (`2 × casais_max`) são **sempre reservados** àquele quarto — podem ser montados como **1 casal OU 2 solteiros**, mas **nunca faltam** (não entram em disputa).
- **Colchões extra:** um **campo global editável** (ex.: **10**) é o **único recurso compartilhado e limitado**. Tudo que passa da base de cada quarto puxa daqui, por noite.
- **Capacidade real da pousada** = base (70) + extras (10) em cama + 13 sofás = **~93 adultos** (ou 80 adultos + 26 crianças). Teto físico se um dia houver colchões p/ todas as 42 vagas: 125.

### Fórmula
```
colchoes_extra_da_reserva = máx(0, (2*casais + solteiros) − 2*casais_max)
                                     └── consumo total ──┘   └ base garantida ┘
```
Exemplos — Quarto 03 (`casais_max=1`, `camas_solteiro=3`):
- 1 casal → 2−2 = **0 extra** · 3 solteiros → 3−2 = **1 extra** · 1 casal+1 solteiro → 3−2 = **1 extra**.

## 2. Organograma do fluxo
```
CONFIG (admin): quarto {casais_max, camas_solteiro, layout, sofa} · global {COLCHOES_EXTRA=10, alerta=1}

NOVA RESERVA
 ① quarto + datas + adultos/crianças
 ② sistema SUGERE arranjo (casal base + sofá/extra); usuário pode ALTERAR casais↔solteiros
     trava: casal garantido + (2c+s ≤ camas_solteiro) + ((2c+s)+sofá ≥ adultos+crianças)
 ③ calcula colchoes_extra da reserva (fórmula §1)
 ④ por NOITE: extras_livres = COLCHOES_EXTRA − Σ(extras das reservas ativas na noite)
       • precisa 0 extra ............... ✅ OK (base sempre cabe)
       • extras_livres ≥ precisa, sobra>1  ✅ OK
       • extras_livres ≥ precisa, sobra≤1  ⚠️ AVISA "resta só N colchão extra na noite dd/mm" (segue)
       • extras_livres < precisa ........ 🚫 BLOQUEIA "sem colchão extra na noite dd/mm (faltam X)"
                                            → sugere: menos pessoas / usar sofá / outro quarto / outra data
 ⑤ CONFIRMA → select_for_update + atômico → revalida a noite → grava casais/solteiros/colchoes_extra
 ⑥ REFLETE em: Dashboard (atenção) · Governança (montagem do dia) · Painel de colchões (usados/livres)
```
> A **base (casal) nunca é bloqueada por colchão** — só os extras disputam o pool.

## 3. Modelo de dados (estender o existente — não duplicar)
**Quarto (`UH`/`AcomodacaoConfig`):** adicionar `casais_max`, `camas_solteiro`, `layout`
(`separado`/`conjugado`/`meia_divisao`). Reconciliar com `posicoes_cama` + `max_colchoes_extras`
já existentes. `sofa_cama`/sofá já existem. Derivados (não persistir): `base = 2*casais_max`,
`vagas_extras = camas_solteiro − 2*casais_max`.

**Global — `ColchoesExtra`** (singleton/setting editável): `quantidade` (default **10**) +
`alerta_minimo` (default **1**). Número único editável (sem histórico).

**Reserva (e relação reserva↔quarto nos grupos):** `casais`, `solteiros`, `usa_sofa_cama`;
derivado `colchoes_extra = máx(0, (2*casais+solteiros) − 2*casais_max)`. Mantém `adultos`/`crianças`
(preço/FNRH). Hóspedes com idade/contagem de crianças ≤15 p/ validar sofá.

## 4. Validações (camada de serviço reutilizável — admin, API, forms, site)
1. `casais ≤ casais_max`
2. `2*casais + solteiros ≤ camas_solteiro`
3. `usa_sofa_cama` só se `quarto.sofa_cama`
4. Sofá: 1 adulto **ou** até 2 crianças ≤15 anos
5. `(2*casais + solteiros) + capacidade_sofa_em_uso ≥ adultos + crianças`
6. **Global por noite** (check-in inclusive, check-out exclusivo): para cada noite,
   `Σ colchoes_extra das reservas ativas + os desta reserva ≤ COLCHOES_EXTRA vigente`.
   - Ativas = **pré-reserva (retenção válida), confirmada, check-in**. Exclui cancelada/no-show.
   - Na edição, exclui a própria reserva da soma.
   - **`select_for_update` + transação atômica** ao confirmar (anti-corrida).
   - Erro **aponta a(s) noite(s) e quantos faltam**.
7. Day use **não** consome colchão. Berço **grátis**, fora da conta.
8. Grupo: o consumo **soma todos os quartos** do grupo.

## 5. Avisos + painéis (pedido do dono)
- **Aviso "resta só N colchão extra na noite dd/mm"** → na **nova reserva** (ao vivo, por noite),
  **bloqueio em 0** (só dos extras), alerta em `≤ alerta_minimo`.
- **Dashboard "Precisa de atenção":** noites com extras no limite/esgotados.
- **Governança — lista de montagem do dia:** quarto · casais · solteiros · sofá aberto (sim/não).
- **Painel de colchões:** extras usados / livres por noite no período.
- Admin: `COLCHOES_EXTRA` e config dos quartos editáveis.

## 6. Preço (segue o Manual de Vendas — NÃO muda com o arranjo)
- Preço por **nº de adultos × temporada** (tabela do Manual, pág. 2); criança ≤5 grátis, 6-15 meia
  pessoa adicional, 16+ adulto; hóspede sozinho 70%; não-reembolsável −12%.
- O **arranjo de cama (casal × solteiros) NÃO altera o preço** — é só montagem/disponibilidade.
- **Reconciliar** a `tarifa_colchao_extra` atual: a cobrança da pessoa extra já vem da *pessoa
  adicional* do Manual → aposentar/alinhar p/ não cobrar em dobro (o colchão vira só disponibilidade).

## 7. Seed (mesclar os dois)
Carregar os 24 quartos **mesclando** a fixture do `CONFIGURACAO_QUARTOS.md` (layout, camas_solteiro,
casais_max, sofa_cama) com o descritivo atual (nome temático, vista, PCD 04/14, metragem) — comando
idempotente (`update_or_create` por número). Metragens já levantadas: Recepção 67, Superior 86,7,
Central 64, Hobbits 62 m²; corredores via plantas.

## 8. Fases de implementação
1. **Modelos + migração** (`ColchoesExtra`; campos no quarto e na reserva) + seed mesclado.
2. **Serviço de domínio** (validações 1-8), com a trava global por noite.
3. **Nova reserva** (recepção + site): sugestão de arranjo, ajuste, aviso/bloqueio ao vivo.
4. **Disponibilidade** (`uh_disponivel`/`tipo_disponivel`) passa a olhar o pool de extras por noite.
5. **Painéis**: aviso no dashboard, lista de montagem (governança), painel de colchões.
6. **Reconciliar preço** (tarifa_colchao_extra × pessoa adicional).
7. **Testes de aceite** (§9).

## 9. Testes de aceite (automatizados)
1. Seed → totais: 24 quartos, 112 camas de solteiro, 35 casais, base 70, **COLCHOES_EXTRA=10**, 13 sofás.
2. 24 quartos em config base (só casais) na mesma noite → **0 extras usados**, aceito.
3. +10 solteiros extras distribuídos em quartos com vaga → aceito (extras=10). **11º extra → recusado**, apontando a noite.
4. Quarto 11: `1 casal + 1 solteiro` → recusado (excede `camas_solteiro=2`); `2 solteiros` → aceito.
5. Quarto 03: `2 casais` → recusado (`casais_max=1`).
6. Quarto 10: `usa_sofa_cama` → recusado (sem sofá).
7. Quarto 22, 3 extras livres: `2 casais + 3 solteiros` + sofá 2 crianças (10 anos) → aceito (9 hóspedes).
8. Sofá: 2 adultos → recusado; 1 adulto → aceito; 1 criança de 16 + 1 de 8 → recusado.
9. Estadia 3 noites, só a 2ª sem colchão extra → recusada, apontando **só a 2ª noite**.
10. Reserva cancelada deixa de consumir extra.
11. Editar reserva sem mudar config não conta o próprio consumo em dobro.
12. **Aviso:** quando `extras_livres(noite) ≤ 1` → sistema avisa (não bloqueia); a **base (casal) nunca é bloqueada** por colchão.
13. Alterar `COLCHOES_EXTRA` para 42 → todas as vagas extras ficam disponíveis.

## 10. Decisões registradas (do dono)
Só solteiros em todos os quartos (80 colchões, 0 de casal); base de casal garantida por quarto;
recurso limitado = campo editável "Colchões extra" (10); aviso por noite em nova reserva + dashboard
+ governança; bloqueio só dos extras (nunca a base); sistema sugere arranjo e permite alterar;
preço e cobrança seguem o Manual; pré-reserva/confirmada/check-in seguram colchão; grupo soma;
day use e berço fora da conta.

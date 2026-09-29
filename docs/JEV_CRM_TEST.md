# JEV_CRM_TEST — Piloto de lead scoring com Jev (TypeSafe AI)

**Status:** proposta / plano (nada implementado).
**Escopo:** um único ponto de decisão — o **score de lead do módulo Comercial** —
rodando **em sombra** (shadow) ao lado da heurística atual, sem trocar o que já funciona.
**Data do plano:** 27/09/2026.

---

## 1. Por que este ponto e por que o Jev

O funil Comercial já pontua cada lead por **regra fixa** (`calcular_score` em
`apps/comercial/services.py`): soma pontos por valor estimado, datas preenchidas, origem,
nº de atividades e existência de cotação; o total (0–100) vira **temperatura**
(frio/morno/quente) em `AnaliseLead`. É um bom começo, mas é **heurística estática** — não
aprende com o que de fato converteu.

O **Jev** é um *System One model*: em vez de gerar texto, recebe um **estado + perguntas
tipadas** e devolve **decisões com probabilidade e confiança calibradas** (70–500ms). Lead
scoring é exatamente uma decisão calibrável: *"qual a probabilidade real de esta
oportunidade fechar?"* e *"qual o melhor canal de 1º contato?"*. Como ele retorna
**confiança**, dá para medir se acerta antes de confiar nele.

**Primitivas do Jev** (usadas aqui): `Score` (nota calibrada contra critério), `Choice`
(escolher de uma lista), `Noul` (avaliar verdade, 0–1). Todas podem vir na mesma chamada,
avaliadas em paralelo; **o nosso código compõe** o resultado.

---

## 2. As perguntas do piloto (atômicas)

Para o lead scoring, três perguntas independentes numa só chamada:

| # | Tipo | Pergunta | Retorno usado |
|---|------|----------|---------------|
| 1 | `Score` | Probabilidade de a oportunidade **converter em reserva** | `score` (0–100) + `confidence` |
| 2 | `Choice` | Melhor **canal de 1º contato** para este lead | `whatsapp` / `ligação` / `e-mail` + `confidence` |
| 3 | `Noul` | Este lead é **real/qualificado** (não curioso ou bot que passou)? | `noul` (0–1) |

O nosso código combina: `score_jev` (nº 1) alimenta a ordenação do funil; o canal (nº 2)
vira sugestão na tarefa de 1º contato; o `noul` baixo (nº 3) marca o lead para revisão.

---

## 3. Estado enviado ao Jev (features, **não** PII)

Regra de privacidade (LGPD): **não** mandar nome/telefone/e-mail crus. Mandar só
**features derivadas** da oportunidade — o Jev decide sobre o *padrão*, não sobre a pessoa:

- `origem` (site/indicação/whatsapp/agência…), `tipo_interesse` (hospedagem/evento/day_use),
  `faturamento` (particular/agência/empresa)
- `valor_estimado`, `tem_datas` (bool), `antecedencia_dias` (checkin − hoje), `noites`,
  `hospedes`
- `n_atividades`, `tem_cotacao` (bool), `pagina_captacao` (slug), campanha/UTM
  (`utm_source/medium/campaign`)
- `sinais` já calculados por `_sinais_lead` (urgência por palavra-chave etc.), tamanho da
  mensagem (não o texto)
- opcional: sinais de enriquecimento que já gravamos em `origem_rastreio` (UF, dispositivo…)

Nenhum desses é dado pessoal identificável isolado. A chave de API do Jev fica em
**variável de ambiente** (padrão do projeto), nunca no código.

---

## 4. Desenho da integração (padrão gateway plugável)

Mesmo padrão de `pagamentos/gateways.py`, `reservas/fnrh_gateway.py`,
`comercial/whatsapp_gateways.py`, `fiscal` (`*_GATEWAY` no settings):

- **Novo** `apps/comercial/decisao_gateway.py` com:
  - `GatewaySimulado` (default) — sem rede; devolve um score determinístico a partir das
    features (reaproveita a heurística atual como "modelo"). Serve dev/teste/CI.
  - `GatewayJev` — chama a API do Jev (Score/Choice/Noul), lê `JEV_API_URL/JEV_API_KEY` do
    ambiente. **Best-effort com timeout curto** (ex. 800ms); qualquer erro → devolve `None`.
  - `get_decisao_gateway()` resolve por `DECISAO_GATEWAY` (settings; default `simulado`).
- **Degradação graciosa:** se o gateway devolve `None` (Jev fora, timeout, sem chave), o
  score **cai na heurística `calcular_score` atual** — o funil nunca fica sem score.
- **Ponto de plugue:** dentro de `analisar_lead(op)` — depois de `atualizar_score` (que
  segue calculando o heurístico), chamar o gateway e **gravar o resultado em campos novos**
  de `AnaliseLead` (ver §5). No piloto, **o score oficial continua o heurístico** — Jev só
  registra ao lado.

---

## 5. Migração de dados (aditiva)

Novos campos em `AnaliseLead` (nada removido):

- `score_jev` (Int, null) — probabilidade de conversão (0–100) do Jev
- `confianca_jev` (Decimal 0–1, null) — confiança da resposta nº 1
- `canal_sugerido` (char, null) — resposta nº 2
- `qualificado_jev` (Decimal 0–1, null) — `noul` da resposta nº 3
- `jev_modelo` (char, null) — versão do modelo/resposta (auditoria de calibração)
- `jev_avaliado_em` (datetime, null)

`Oportunidade.score` **não muda no piloto** (só na Fase 2, se formos adiante).

---

## 6. Modo de operação em 3 fases

1. **Fase 0 — Sombra (este piloto).** Jev roda e grava `score_jev` etc. em paralelo. **Zero
   impacto** na UI, na ordenação e na decisão humana. Só coletamos dados para comparar.
2. **Fase 1 — Assistido.** Mostrar no card a sugestão do Jev (probabilidade + canal) quando
   `confianca_jev` for alta; ordenar por `score_jev` como opção. **Humano ainda decide.**
3. **Fase 2 — Ativo.** `score_jev` vira o score oficial (com fallback heurístico e
   *kill-switch* por setting). Só se a calibração provar valor.

---

## 7. Como mediremos sucesso (critérios de saída da Fase 0)

Rodar ~2–4 semanas (ou fazer *replay* nos leads históricos — ver §8) e avaliar:

- **Calibração** — *Brier score* / curva de calibração: quando o Jev diz "70%", ~70% fecham?
  Comparar contra a heurística atual no mesmo período.
- **Poder de ordenação** — os leads que o Jev pôs no topo converteram mais? (AUC/lift vs.
  heurística).
- **Canal** — a sugestão de canal bate com o canal que de fato converteu?
- **Operacional** — latência p95, custo por 1k decisões, **taxa de fallback** (quantas vezes
  o Jev não respondeu e caímos na heurística).

**Ir para Fase 1** só se o Jev **empata ou supera** a heurística em calibração/ordenação com
fallback < ~5% e latência aceitável.

---

## 8. Ferramenta de avaliação (sem esperar leads novos)

Comando `manage.py jev_replay` (read-only): pega oportunidades **já fechadas** (ganhas/
perdidas), monta as features de cada uma, consulta o Jev e compara a probabilidade prevista
com o **desfecho real**. Dá o número de calibração **antes** de expor qualquer coisa na UI.
Usa o `GatewaySimulado` no CI; o Jev real só quando houver chave.

---

## 9. Arquivos afetados (resumo)

- **novo** `apps/comercial/decisao_gateway.py` (Simulado + Jev + `get_decisao_gateway`)
- `apps/comercial/services.py` — `analisar_lead()` chama o gateway e grava em `AnaliseLead`
- `apps/comercial/models.py` — campos novos em `AnaliseLead` + migração
- `config/settings.py` — `DECISAO_GATEWAY` (default `simulado`), `JEV_API_URL`, `JEV_API_KEY`,
  `JEV_TIMEOUT_MS`
- **novo** `apps/comercial/management/commands/jev_replay.py`
- `apps/comercial/tests.py` — testes com `GatewaySimulado` (determinístico), fallback quando
  o gateway devolve `None`, e que o piloto **não altera** `Oportunidade.score`

---

## 10. Riscos & mitigações

- **Modelo novíssimo (2 semanas de vida).** → Só **sombra**; fallback sempre para a
  heurística; *kill-switch* por `DECISAO_GATEWAY=simulado`.
- **Privacidade.** → Enviar **features**, não PII; chave em env; sem persistir PII no provedor.
- **Custo/latência inesperados.** → Timeout curto + medição de custo/latência na Fase 0;
  desligar por setting.
- **Dependência externa.** → Degradação graciosa (o CRM funciona idêntico sem o Jev).

---

## 11. Pendências / decisões abertas (não bloqueiam o desenho)

- Confirmar na conta TypeSafe: **endpoint/auth exatos**, formato de request/response das
  primitivas, **preço** e limites, disponibilidade regional.
- Definir a lista fechada de canais do `Choice` (whatsapp/ligação/e-mail — bate com o que a
  equipe usa?).
- Escolher a janela do *replay* (quantos leads fechados temos com desfecho confiável?).

---

## 12. Rollback

Tudo é **aditivo**: campos novos ficam nulos, `Oportunidade.score` intacto. Desligar =
`DECISAO_GATEWAY=simulado` (ou remover a chave). Sem migração reversa necessária para
"desligar"; a migração dos campos pode ser mantida sem uso.

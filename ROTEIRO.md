# ROTEIRO — conectar os pacotes de design ao CRM

Plano de execução para ligar o trabalho em `SIteCRM_Vo_Testa_Design/` ao sistema
Django existente. **Nada que já funciona é reescrito.** Cada passo diz o que muda,
quais arquivos, o critério de aceite verificável e de que depende.

> Este documento é o plano. **Não implementar nada antes da aprovação do dono do
> produto.** As duas seções finais — "Divergências" e "Decisões que não são minhas"
> — precisam ser lidas antes de autorizar.

Leitura feita antes de escrever este plano: `LEIA-ME-PRIMEIRO.md`, `AUDITORIA.md`,
os três `Instruções.md`/`LEIA-ME.md` dos pacotes, todo o código de
`apps/pagamentos/`, `apps/site/emails.py`, `apps/reservas/models.py` e
`services.py`, `apps/nucleo/models/cadastros.py`, `seletores.py`, `permissoes.py`,
`apps/portal/services.py`, `apps/site/models.py`/`views.py`, e todos os arquivos de
código dos três pacotes de handoff.

---

## Princípios que valem sobre qualquer passo (de `LEIA-ME-PRIMEIRO.md`)

1. **Dinheiro tem uma fonte só.** Uma função calcula a conta; ficha, check-out e
   Saídas leem dela, não recalculam.
2. **Check-out fecha a conta** numa transação: recebe o saldo, quita a cobrança,
   encerra, avisa a lista de espera.
3. **Estado vem do banco**, não da tela.
4. **Pré-reserva tem prazo** e algo a expira.
5. **Capacidade é da unidade**; a frase de camas é gerada, nunca digitada.
6. **Portal e CRM leem o mesmo dado.**
7. **Não escrever "sem juros" cobrando juros.**
8. **Cartão nunca é persistido** — nem payload, nem log, nem evento.

O que **não se toca**: webhook/conciliação/mapa de status Safrapay
(`views.webhook`, `_status_pago`, `_STATUS_PAGO`, `_extrair_liquidacao`,
`registrar_liquidacao`); migrações já aplicadas (só criar novas); `static/css/app.css`
(usar tokens); a sidebar (`modulos.py`, um `url_name` por módulo — telas novas viram
aba no controle segmentado da página). Arquivos `.dc.html` e `dados.js` são
protótipo — referência de regra, não código.

---

## Estado verificado do repositório (o que já existe)

Confirmado lendo o código — importa para os passos abaixo:

- **`fazer_checkout` já recusa fechar com saldo aberto** (`conta.saldo() != 0`
  levanta erro). O defeito "check-out deixava saldo aberto" **já não ocorre no CRM**.
  Falta o oposto do protótipo: fechar *registrando* o recebimento numa transação e
  avisar a lista de espera (ver Passo 8).
- **Conta da hospedagem** = `ContaHospedagem` (OneToOne com `Reserva`, criada no
  check-in). `conta.saldo()` = lançamentos − pago − adiantamentos. `dados_estadia()`
  já é lida pelo Portal e pela ficha — é o embrião da "fonte única".
- **Desconto Pix** hoje vive só no **site** (`_resumo_preco`,
  `site.Reserva.desconto_percentual`, `ConfiguracaoSite.desconto_pix=5%`). O CRM tem
  `LancamentoConta.tipo=DESCONTO`, mas o desconto do site **não é reaplicado** na
  conta do CRM de forma unificada.
- **Três cálculos de dinheiro coexistem**: `site.views._resumo_preco`, o folio
  pré-check-in (`valor_diaria × noites`) e `conta.saldo()`. O invariante nº 1 mira
  exatamente isso.
- **Pagamentos**: `Cobranca` tem `metodo`, `payload`, `pix_copia_cola`, `expira_em`,
  `parcelas`, `gateway_id`, `criado_por`, `pago_em`, `Status`, `Finalidade`,
  `Metodo`. `EventoPagamento.Tipo.WEBHOOK` existe. `services.criar_cobranca(operador,
  *, valor, metodo, descricao, finalidade, pagador, reserva_id, parcelas)`;
  `confirmar_pagamento(cobranca, usuario, origem)`; `cancelar(cobranca, operador)`.
  `views._url_recibo_site` e `_status_pago` **já existem no `views.py`** (o
  `views_novas.py` do pacote os referencia sem redefinir — bom).
- **Rota pública** = `pagamentos:pagar` (`pagar/<uuid:token>/`) + `pagar_simular`.
- **Portal**: não há `url_publica`; o token vem de `AcessoPortal` via
  `portal.services.get_acesso(reserva_id).token`.
- **Estrutura física**: `TipoUH` (capacidade, tarifa_base, modalidade), `UH` (numero,
  tipo, pcd, status). **Não existe** composição de camas, `ConfiguracaoUH`,
  `PosicaoCama`, `UH.tarifa_override`, nem `apps/nucleo/estrutura.py`.
- **Site**: `site.Quarto.tipo_uh` (FK) e `capacidade` existem; `sincronizar_quartos`
  gera 1 card por `TipoUH`; `finalizar_reserva` chama `criar_reserva_site` e aloca um
  quarto físico livre do tipo.
- **Settings existentes**: `PAGAMENTOS_GATEWAY`, `SAFRAPAY_ENV`, `SAFRAPAY_ID`,
  `SAFRAPAY_CODIGO_ATIVACAO`, `SAFRAPAY_TOKEN`, `SAFRAPAY_GATEWAY_URL`,
  `RESERVA_RETENCAO_MINUTOS=30`, `SITE_PUBLIC_URL`, `DEFAULT_FROM_EMAIL`,
  `EMAIL_BACKEND`. **Faltam**: `WHATSAPP_POUSADA`, `RESERVA_PERCENTUAL_SINAL`,
  `USE_THOUSAND_SEPARATOR`; o pacote cita `SAFRAPAY_AMBIENTE` (o real é `SAFRAPAY_ENV`).
- **NPS** é esqueleto (só `proposta()`/stub); **Fiscal** tem `emitir_nfse_da_conta` e
  achado por `referencia=f"conta:{id}"` — não há `nota_da_conta`.

---

## Ordem de execução (por dependência real)

Blocos independentes marcados. A ordem segue `LEIA-ME-PRIMEIRO.md`.

| Passo | Entrega | Depende de | Pode ir a prod antes do token Safrapay? |
|---|---|---|---|
| 1 | Filtro de moeda único | — | sim |
| 2 | Capacidade e camas por unidade | 1 (só formatação) | sim |
| 3 | Tarifa por unidade + "a partir de" honesto | 2 | sim |
| 4 | Colchão extra cobrado na cotação/conta | 2, 3 | sim |
| 5 | Site vendendo quarto (não tipo) | 2, 3, 4 | sim |
| 6 | Página de pagamento (Pix/QR/validade/polling/estado expirado) | 1 | sim |
| 7 | Política de parcelamento + tela de configurações | 1, 6 | sim |
| 8 | Cartão (form + patch gateway + rate limit) | 6, 7 | **não** (homologação) |
| 9 | Seis e-mails da jornada + gatilhos | 1 (2 melhora) | sim |

Os passos 6–9 são independentes de 2–5; podem correr em paralelo a partir do 1.

---

### Passo 1 — Filtro de moeda único

**O que muda:** decidir **um** formatador de dinheiro e usá-lo em todo lugar novo.
Recomendo o filtro `intcomma_brl` do pacote, em `apps/nucleo/templatetags/moeda.py`
(o pacote de e-mails e o `pagar.html` já o esperam). O `emails_jornada._brl` duplica
essa lógica — **manter só um**: o módulo de e-mail importa o mesmo formatador ou usa
uma função utilitária única.

**Arquivos:** criar `apps/nucleo/templatetags/moeda.py` (de
`pagamento_handoff/templatetags_moeda.py`). Ajustar `emails_jornada.py` para não ter
segundo formatador.

**Critério de aceite:** `{% load moeda %}{{ 1600|intcomma_brl }}` → `R$ 1.600,00`;
`-67.5` → `-R$ 67,50`; `None`/vazio/inválido → `R$ 0,00`. Nenhum outro formatador de
moeda novo no código. Testes de zero/milhar/negativo/None passam.

---

### Passo 2 — Capacidade e composição de camas por unidade

**O que muda:** capacidade deixa de ser número no `TipoUH` e passa a ser composição
de camas por `UH`. Traduzir de `dados.js` (`camasDe`, `capacidade`, `descricaoCamas`)
para Django.

**Arquivos:**
- `apps/nucleo/models/cadastros.py`: novos models `PosicaoCama` (FK `UH`, `nome`,
  `montagem_padrao` [casal|dois_solteiros], `ordem`) e `ConfiguracaoUH` (OneToOne
  `UH`: `tem_sofa_cama`, `sofa_adultos=1`, `sofa_criancas=2`, `sofa_idade_maxima=15`,
  `max_colchoes_extras`, `tarifa_colchao_extra=80.00`). Exportar em
  `apps/nucleo/models/__init__.py`.
- **Novo** `apps/nucleo/estrutura.py`: `capacidade(uh)` (dict com `fixa`,
  `sofa_adultos`, `sofa_criancas`, `extras`, `maxima`, `maxima_criancas`) e
  `descricao_camas(uh)` (frase gerada; day use → "Sem pernoite · acesso à estrutura
  no período").
- Nova **migração de dados** semeando os 24 quartos (11 de dois cômodos: 01,02,16–24;
  sofá em 01,02,09,15,16–24; PCD 04 e 14; colchões: 2 nos de dois cômodos, 1 nos de
  um). Day use sem cama. `pcd=True` em 04 e 14.
- Tela Cadastros → Quartos: edição da composição, capacidade **calculada só-leitura**
  com quebra (fixa/sofá/extra). Sem tocar no layout Lampião.
- Mapa de quartos: exibir a lotação de cada quarto.

**Critério de aceite:** `capacidade()` para os três perfis — dois cômodos com sofá
(7 adultos / 8 com crianças), um cômodo com sofá (4 / 5), um cômodo sem sofá (3 / 3);
day use → zero e sem camas. **Soma total de lotação = 118** (131 com crianças no
sofá) — se der diferente, a migração está errada. `descricao_camas` bate a frase
exata do `Instruções.md`. Testes de `capacidade()` e `descricao_camas()` passam.
Disponibilidade filtra por `maxima_criancas`.

---

### Passo 3 — Tarifa por unidade + "a partir de" honesto

**O que muda:** dentro do mesmo tipo, o quarto de dois cômodos custa mais.

**Arquivos:**
- `UH`: campo `tarifa_override` (DecimalField, null=True) — override manual vence o
  cálculo.
- `apps/nucleo/estrutura.py` (ou `reservas/services.py`): `tarifa_da_unidade(uh,
  classificacao/temporada)` com ordem `tarifa_override` → tarifa do tipo × fator se
  duplo → tarifa do tipo; `tarifa_minima_do_tipo(tipo_uh)` = menor tarifa efetiva
  entre as unidades do tipo.
- `settings`: `ACRESCIMO_TARIFA_DUPLO = 1.6` (configurável, não constante no código;
  acréscimo de 60% arredondado à dezena).
- Onde hoje anuncia `tarifa_base`: vitrine do site, cards de tipo no CRM, tabela de
  temporadas → passar a usar `tarifa_minima_do_tipo`, com legenda de que é o mínimo.

**Critério de aceite:** override vence cálculo; duplo recebe acréscimo (250 → 400);
simples fica na base. `tarifa_minima_do_tipo` retorna o menor valor real, não
`tarifa_base`. Testes passam. A vitrine não anuncia "a partir de" abaixo da menor
tarifa real.

---

### Passo 4 — Colchão extra cobrado

**O que muda:** colchão extra vira item cotado e lançado; sofá-cama e berço não
cobram. Traduzir `extrasPara`/`cotacaoUnidade` de `dados.js`.

**Arquivos:**
- `apps/nucleo/estrutura.py`: `extras_para(uh, pessoas)` →
  `clamp(pessoas - (posições×2 + sofa_adultos), 0, max_colchoes_extras)`.
- Cotação (site + reserva): valor do colchão itemizado à parte das diárias
  (`qtd × tarifa_colchao_extra × noites`).
- Conta: lançar como `LancamentoConta` com `tipo=SERVICO`, `natureza=SERVIÇO`,
  descrição "Colchão extra · N unidades · M noites" (via `lancar_na_conta`).
- Governança: expor quantos colchões via service/sinal (não importar model de
  reservas na governança).
- FAQ do site: trocar o texto de "cama extra sem custo" pelo texto validado no
  `Instruções.md`.

**Critério de aceite:** `extras_para` = 0 quando cabe nas camas incluídas; limitado
ao máximo; nunca negativo. Cotação com colchão em período que cruza duas temporadas
tem bruto correto e linha itemizada. Testes passam.

---

### Passo 5 — Site vendendo quarto, não tipo

**O que muda:** motor lista **quartos** livres (1 card por unidade), filtra por
lotação real, ordena do mais barato ao mais caro, mostra a frase de camas e o preço
daquela unidade (com colchão somado quando preciso). A reserva nasce no quarto
escolhido.

**Arquivos:** `apps/site/views.py` (motor de busca e `finalizar_reserva`),
`sincronizar_quartos` (ou a montagem da vitrine), templates do site (seletor 1–8
hóspedes no hero e no motor, persistindo na sessão), estado vazio honesto.

**Não regride:** antioverbooking por `ExclusionConstraint`, `expira_em` +
`expirar_vencidas`, `obter_ou_criar_hospede`, `site.Reserva` como recibo com
`crm_reserva_id`. A mudança é só na seleção e na precificação.

**Critério de aceite:** com 6 pessoas sobram 9 quartos; com 2, aparecem 22. Reserva
do site nasce no quarto escolhido (não em outro do mesmo tipo). Grupo sem quarto que
comporte vê mensagem honesta com o teto real. Testes de disponibilidade-por-pessoas e
de "nasce no quarto escolhido" passam.

---

### Passo 6 — Página de pagamento (Pix, QR, validade, polling, estado expirado)

**O que muda:** substitui a `pagar` e o template público; adiciona QR SVG, contagem
de validade, polling de status (tira o "Já paguei" do caminho principal) e o estado
expirado com "gerar novo código". **Sem tocar no webhook/conciliação.**

**Arquivos:**
- `apps/pagamentos/views.py`: colar `pagar` (nova), `pagar_status`,
  `pagar_novo_codigo`, `_contexto_pagar`, `_qr_svg`, `_expirada`, `_legenda_valor`,
  `_resumo_reserva` de `views_novas.py`. **Reaproveitam `_url_recibo_site` e
  `_status_pago` já existentes.**
- `apps/pagamentos/urls.py`: rotas `pagar_status` e `pagar_novo_codigo` de
  `urls_novas.py` (nomes `pagamentos:pagar`, não `publica`).
- `templates/pagamentos/pagar.html`: do pacote (cinco estados, tokens do `app.css`).
- Ajustar `_legenda_valor`/`_resumo_reserva`: **não existe `Reserva.valor_total`** —
  usar `valor_diaria × noites` (folio) ou `conta` conforme o estado (ver Divergências).
- `_contexto_pagar` lê `WHATSAPP_POUSADA` (settings **a criar**).

**Critério de aceite:** `qr_svg` vazio não quebra a página (cai no copia-e-cola);
`expirada` renderiza o estado expirado, não o formulário; `pagar_status` devolve
`{"status": ...}` e nada mais; cache de 10 s por token no polling; validade
contando na tela. Testes de `pagar_status`, expirada e QR vazio passam.

---

### Passo 7 — Política de parcelamento + tela de configurações

**O que muda:** taxa (MDR) por número de parcelas vira dado da gerência, não
constante. Aba de configurações no controle segmentado da página de Pagamentos.

**Arquivos:**
- `apps/pagamentos/models.py` (ou `models_parcelamento.py` importado no `__init__`):
  `PoliticaParcelamento` (singleton `load()`, `modo` absorver/repassar, `parcelas_max`,
  `parcela_minima`, `vale_sinal=False`, `vale_saldo`, `vale_avulso`, horários e taxas
  early/late), `TaxaParcela` (por nº de parcelas, `ativa`), `opcoes_parcelas()`.
- Nova migração de dados: `migration_politica.py` — **taxas nascem em ZERO**.
- `apps/pagamentos/views.py`: `configuracoes` + `configuracoes_salvar` de
  `views_configuracoes.py` (`@requer_gerencia`). Trocar as URLs hardcoded
  `/crm/pagamentos/...` por `reverse` quando possível.
- `apps/pagamentos/urls.py`: rotas `configuracoes` e `configuracoes_salvar`.
- `templates/pagamentos/configuracoes.html`: aba segmentada (não menu novo).

**Critério de aceite:** `opcoes_parcelas` respeita ativa, teto e parcela mínima ao
mesmo tempo; sinal com `vale_sinal=False` não oferece parcelamento; no modo
`repassar` o rodapé **não** diz "sem juros" (`sem_juros` governa o texto). Migração
semeia taxas em zero. Testes passam.

---

### Passo 8 — Cartão (form + patch do gateway + rate limit) — **depende de homologação**

**O que muda:** formulário de cartão com validação cliente+servidor (Luhn, bandeira,
CVV, validade), idempotência, rate limit e **cartão nunca persistido**. Patch no
`gateways.py` para receber `card` por argumento e nunca cair em cartão fictício fora
de sandbox/HML.

**Arquivos:**
- `apps/pagamentos/views.py`: `pagar_cartao`, `_validar_cartao`, `_luhn`, `_bandeira`,
  `_rate_limit`, `BANDEIRAS` de `views_novas.py`.
- `apps/pagamentos/urls.py`: rota `pagar_cartao`.
- `apps/pagamentos/gateways.py`: aplicar `patch_gateways.py` — assinatura
  `criar_cobranca(self, cobranca, *, card=None)`, `_criar_cartao(..., card=None)`,
  `_limpar_card()`. **Corrigir `SAFRAPAY_AMBIENTE` → `SAFRAPAY_ENV`** (ver
  Divergências). Não tocar em `_criar_pix`/`_criar_boleto`/webhook.
- `services.criar_cobranca` chama `get_gateway().criar_cobranca(cobranca)` hoje sem
  `card`; o `card` vem do POST em `pagar_cartao`, que chama o gateway direto —
  confirmar o fluxo para não gravar cartão no `payload`.

**Critério de aceite:** Luhn no servidor recusa dígito trocado **antes** de chamar o
gateway; CVV de 4 aceito só em Amex; validade vencida recusada; POST em cobrança já
paga não cobra de novo; rate limit dispara na 6ª tentativa do mesmo token; **teste
explícito** buscando PAN/CVV em `payload`, `EventoPagamento` e log não encontra nada.
Todos os testes do `LEIA-ME.md` passam.

---

### Passo 9 — Seis e-mails da jornada + gatilhos

**O que muda:** véspera, pré-reserva expirando, pós-checkout, NPS, cobrança,
abandono. `enviar_confirmacao` **fica intacta**.

**Arquivos:**
- `apps/site/templates/site/emails/`: `base_email.html` + os seis pares `.html`/`.txt`.
- `apps/site/emails_jornada.py`: do pacote, com os imports **corrigidos** (ver
  Divergências — nomes reais de campos/services/rotas). `fail_silently=True`.
- Gatilhos: `vespera_enviada_em` em `reservas.Reserva` (nova migração) + comando de
  cron `enviar_vespera`; `pos_checkout` no `fazer_checkout` (após fechar a conta);
  `cobranca` em `criar_cobranca`; `pre_reserva_expirando` em cron; `nps` em cron D+2/3.
- **Marcadores a resolver** contra a API real: `portal.services.url_publica` →
  `get_acesso(reserva_id).token` + `reverse`; `valor_total_reserva` → `valor_diaria ×
  noites`; `pagamentos:publica` → `pagamentos:pagar`; `criar_cobranca(valor=,
  finalidade=, reserva=, forma=)` → assinatura real `(operador, *, valor, metodo,
  descricao, finalidade, pagador, reserva_id, parcelas)`; `cobranca.get_forma_display`
  /`dados_gateway`/`vencimento` → `get_metodo_display`/`payload`/`expira_em`;
  `nps.services.url_pesquisa` (não existe); `fiscal.nota_da_conta` → busca por
  `referencia=f"conta:{id}"`; `descricao_camas` do Passo 2 (try/except).

**Critério de aceite:** cada função renderiza `.html`+`.txt` sem erro; não envia sem
e-mail do destinatário (retorna `False`); `pos_checkout` muda o rótulo nos três casos
(zero/a pagar/a devolver); `abandono` muda CTA/texto conforme o quarto esteja livre;
assunto sem quebra de linha. `abandono` só se o model de rascunho existir (senão fica
para depois — ver Decisões). Testes no padrão do teste de confirmação passam.

---

## Divergências (pacote × código atual)

Onde os pacotes discordam do repositório. Sigo o que **preserva o comportamento já
testado** e registro aqui.

1. **`Reserva.valor_total` não existe.** `views_novas._legenda_valor` e
   `emails_jornada.valor_total_reserva` presumem esse campo. Real: `valor_diaria ×
   noites` (folio pré-check-in) ou `conta` (pós check-in). → Usar o cálculo real; não
   criar campo redundante que viraria segunda fonte de verdade.

2. **`emails_jornada.py` usa vocabulário de model errado.** Presume
   `cobranca.get_forma_display()`, `cobranca.dados_gateway`, `cobranca.vencimento`. O
   model real tem `get_metodo_display()`, `payload`, `expira_em`. → Corrigir no import.

3. **Nome de rota do link público diverge.** E-mails usam `pagamentos:publica`; o
   real (e o pacote de pagamentos) é `pagamentos:pagar`. → Padronizar em
   `pagamentos:pagar`.

4. **Assinatura de `criar_cobranca` diverge.** E-mails chamam `criar_cobranca(valor=,
   finalidade=, reserva=, forma=)`; real é `criar_cobranca(operador, *, valor, metodo,
   descricao, finalidade, pagador, reserva_id, parcelas)`. → Adaptar as chamadas.

5. **`SAFRAPAY_AMBIENTE` não existe.** `patch_gateways.py` lê `SAFRAPAY_AMBIENTE`; o
   settings real é `SAFRAPAY_ENV`. → Usar `SAFRAPAY_ENV`.

6. **`portal.services.url_publica` não existe.** Real: `get_acesso(reserva_id).token`
   + `reverse` da rota do portal. → Escrever um helper fino ou usar direto.

7. **`nps.services.url_pesquisa` não existe** (NPS é esqueleto). → O e-mail NPS fica
   pendente da fase CRM do Hóspede, OU cria-se um `url_pesquisa` mínimo que aceita
   `?nota=`. Decisão de produto (abaixo).

8. **`fiscal.nota_da_conta` não existe.** Real: `DocumentoFiscal.objects.filter(
   referencia=f"conta:{id}", tipo=NFSE)`. → Adaptar (já está em try/except no pacote).

9. **`estrutura.py` não existe** e capacidade hoje é `TipoUH.capacidade`. → Criar o
   módulo; manter o campo antigo por compatibilidade, mas nada de disponibilidade lê
   dele depois do Passo 2.

10. **`UH.tarifa_override` e composição de camas não existem.** → Criados nos Passos
    2–3 (migrações novas, não editar as aplicadas).

11. **Check-out no CRM já recusa saldo aberto** — diverge do defeito descrito
    (protótipo devolvia o quarto com saldo em aberto). → O CRM está mais seguro; o que
    falta é o `fecharConta` do protótipo: **receber o saldo + quitar a cobrança +
    avisar a lista de espera numa transação** (Passo 8/9 e lista de espera). Não
    afrouxar a checagem atual.

12. **Duas funções de moeda** (`intcomma_brl` e `emails_jornada._brl`). → Manter só
    uma (Passo 1).

13. **`_url_recibo_site` e `_status_pago`**: o `views_novas.py` os referencia sem
    redefinir — **já existem** no `views.py` atual. Sem conflito; só não duplicar.

14. **URLs `/crm/pagamentos/...` hardcoded** em `views_novas`/`views_configuracoes`/
    `patch_gateways`. → Trocar por `reverse` onde der; se ficar hardcoded, documentar o
    acoplamento ao prefixo `/crm/`.

---

## Decisões que não são minhas (precisam do dono do produto)

Não escolho por você. Cada uma trava ou muda um passo.

1. **Reserva de grupo (BLOQUEADOR do `AUDITORIA.md`).** O modelo admite **uma UH por
   reserva**; RS-0151 tinha 16 pessoas num quarto de 3 e "8 quartos" que continuavam
   vendáveis (venda dupla real). Precisa de decisão de desenho: **reserva com lista de
   unidades** ou **reserva-mãe com filhas por quarto**. Fora do escopo dos quatro
   pacotes — não implemento sem a decisão. Afeta o Passo 5.

2. **Taxas de parcelamento (MDR).** Nascem em zero (Passo 7). Os valores reais vêm do
   **contrato Safrapay** — preciso deles para produção.

3. **Absorver × repassar + contabilidade.** No `absorver` o caixa recebe o cheio e a
   taxa é despesa; no `repassar` o líquido iguala a cobrança. **Confirmar com o
   contador** antes de ligar em produção — muda a conciliação. Default do pacote:
   `absorver`.

4. **Janela de retenção da pré-reserva.** Hoje 30 min. O e-mail
   `pre_reserva_expirando` 15 min depois é quase inútil. O pacote sugere **aumentar
   para algumas horas** quando houver aviso por e-mail. Decisão de negócio — não mudo
   `RESERVA_RETENCAO_MINUTOS` sem confirmar.

5. **`vale_sinal` (parcelar o sinal).** Vem **desmarcado** por decisão do pacote
   (parcelar 30% em 6× recebe depois da estadia). Confirmar se fica assim.

6. **Fator de acréscimo do quarto duplo.** Pacote usa **60% (× 1.6)**, arredondado à
   dezena, configurável. Confirmar o valor.

7. **E-mail NPS.** NPS é esqueleto. Ou (a) adio o e-mail para a fase CRM do Hóspede,
   ou (b) crio um `url_pesquisa` mínimo que grava `?nota=` agora. Qual?

8. **E-mail de abandono.** Exige um model de rascunho (unidade, período, pessoas,
   valor, e-mail, token, `enviado_em`) que o motor não tem, e é marketing (descadastro
   + envio único). Criar o model agora ou deixar os outros cinco e-mails e adiar o
   abandono?

9. **Política de cancelamento / estorno** (Oportunidades do `AUDITORIA.md`): o texto
   existe, a retenção não é calculada; cancelar reserva paga não devolve nada. Fora
   dos quatro pacotes — confirmar se entra nesta leva.

---

## O que fica de fora desta entrega (e por quê)

- **Blocos "Oportunidades" do `AUDITORIA.md`** que não estão em nenhum pacote
  (RevPAR, histórico por pessoa, comissão de agência, metas por canal, conciliação por
  arquivo, fechamento de caixa por turno) — são conversas de produto, não tarefas
  prontas.
- **Fila para Celery/Redis dos e-mails** — os seis são síncronos, como o
  `enviar_confirmacao`. `fail_silently=True` protege o fluxo até o Celery entrar.
- **Migrar `confirmacao.html` para `base_email.html`** — opcional, commit separado,
  com o teste de e-mail passando antes e depois. Não faz parte desta entrega.
- **Reserva de grupo, cancelamento/estorno, NPS real, abandono** — dependem das
  decisões acima.

---

## Como trabalhar (do prompt do dono)

- Um commit por passo, com a mensagem dizendo o passo.
- Testar cada passo pelo critério de aceite acima **antes** de seguir
  (`.venv/bin/python manage.py test`).
- Marcar os passos concluídos aqui e nos checkboxes do `AUDITORIA.md`.
- Antes de finalizar módulo: testes → django-verification → /code-review → (commit e
  deploy só com ordem explícita).
- Deploy/commit/push **só com comando explícito**.
```
[x] Passo 1   [x] Passo 2   [x] Passo 3   [x] Passo 4   [x] Passo 5
[ ] Passo 6   [ ] Passo 7   [ ] Passo 8   [ ] Passo 9
```

> Passo 5 numera as etapas internas 1–6 do bloco de grupo (ver seção do Passo 5).
> Todas concluídas. Passos 6–9 abaixo são os da página de pagamento, parcelamento,
> cartão e e-mails.

---

## Progresso — Passos 1 a 4 (implementados)

Parado antes do Passo 5, que depende da decisão de **reserva de grupo**.

### Passo 1 — Filtro de moeda ✓
- `apps/nucleo/templatetags/moeda.py` — filtro único `intcomma_brl`. `USE_THOUSAND_SEPARATOR`
  não está ligado (sem conflito). Testes: `MoedaFiltroTests` (6).

### Passo 2 — Capacidade e camas por unidade ✓
- Models `PosicaoCama` e `ConfiguracaoUH` em `nucleo/models/cadastros.py`
  (migração `0016`), seed dos 24 quartos (migração de dados `0017`).
- `apps/nucleo/estrutura.py` — `capacidade()`, `descricao_camas()`, `faixa_do_tipo()`
  (fonte única, frase gerada). Filtros `camas_uh`/`lotacao_uh` em `nucleo_extras`.
- Comando `popular_camas` (idempotente) para bases novas — os 24 quartos vêm de
  seed manual, não de migração; a migração `0017` cobre a base existente.
- UI: editor de composição na tela do quarto (`nucleo/uh_form.html`: posições via
  formset + sofá/colchões + capacidade calculada só-leitura); coluna Camas/Lotação
  na lista; lotação no tooltip do mapa de quartos.
- **Conferido: lotação total = 118 (131 com crianças), 70 fixas + 13 sofá + 35 colchão.**
- Testes: `EstruturaCamasTests` (8).

### Passo 3 — Tarifa por unidade ✓
- Campo `UH.tarifa_override` (migração `0018`); `estrutura.eh_duplo()`; setting
  `ACRESCIMO_TARIFA_DUPLO=1.6`.
- `reservas.services`: `tarifa_da_unidade()`, `diaria_media_unidade()`,
  `tarifa_minima_do_tipo()` (override → tipo×1.6 se duplo, arredondado à dezena → tipo).
- "A partir de" honesto: `sincronizar_quartos` usa `tarifa_minima_do_tipo`; tela
  Cadastros → Quartos mostra "A partir de" + faixa de lotação por tipo.
- Testes: `TarifaUnidadeTests` (5).

### Passo 4 — Colchão extra cobrado ✓
- `estrutura.extras_para(uh, pessoas)`; `reservas.services.cotacao_unidade()`
  (itemizada) e `colchoes_extras(reserva)` (interface pública p/ governança).
- Lançado na conta no **check-in** (`ContaHospedagem.lancar_colchoes_extras`):
  `LancamentoConta` tipo=SERVIÇO, "Colchão extra · N unidades · M noites",
  itemizado à parte da diária.
- Testes: `ColchaoExtraTests` (8).

### Passo 5 — Reserva de grupo (desenho fechado com o dono)

Desenho: **reserva-mãe com filhas por quarto**. A mãe (`GrupoReserva`) não ocupa
quarto; cada quarto é uma `Reserva` normal (uma UH) com FK `grupo`. Antioverbooking,
check-in por quarto e conta seguem por filha — a mãe agrupa. Reserva comum = filha
sem mãe (`grupo=None`). Resolve o bloqueador RS-0151 (Grupo Ribeiro): 8 quartos = 8
filhas em UHs reais, cada uma na ocupação, sem venda dupla.

**Decisões travadas:**
- **Dinheiro = híbrido.** Diária **e colchão extra** → **folio-mãe** (conta do grupo,
  paga pelo titular). Consumo (frigobar, restaurante, loja, lavanderia) → **conta do
  quarto**, paga pelo hóspede. Regra de roteamento: `natureza SERVIÇO da acomodação
  (diária/colchão) → folio-mãe; CONSUMO → conta do quarto`. Cada conta é fonte única
  do seu escopo; a mãe soma, nunca recalcula.
- **Criação só no CRM.** Recepção monta o bloco. Site segue quarto a quarto; grupo
  grande no site = «Pedir proposta» (Comercial).
- **Check-in/out por quarto, independente.** Botão «check-in do grupo» por
  conveniência. Status da mãe derivado das filhas.
- **Check-out do quarto com folio-mãe aberto = permitido.** Basta a conta do quarto
  (consumo) zerada; as diárias ficam no folio-mãe, faturadas e fechadas no
  encerramento do grupo.
- **Sinal único no folio-mãe.** Uma cobrança confirma o grupo todo.
- **Cancelamento em cascata + encolher.** Cancelar a mãe cancela as filhas (auditado);
  dá para remover um quarto do bloco; pré-reserva do grupo expira junta.

**Plano de construção (incremental, com testes de dinheiro/disponibilidade em cada
etapa):**

1. **Models.** `GrupoReserva` (titular, faturamento, período, canal, expira_em, rótulo,
   criado_por; status via property derivada das filhas). `Reserva.grupo` FK null
   (related_name `filhas`). `ContaHospedagem`: `reserva` vira opcional + FK `grupo`
   (folio-mãe), constraint "exatamente um dos dois". Migrações novas.
   *Aceite:* criar mãe + 2 filhas em UHs distintas; antioverbooking recusa filha em UH
   ocupada; filha sem grupo funciona igual a hoje.
2. **Roteamento do lançamento.** `fazer_checkin` da filha: cria conta do quarto (para
   consumo) e lança **diária + colchão no folio-mãe** quando há grupo; senão, como hoje.
   *Aceite:* diária no folio-mãe, consumo na conta do quarto, colchão no folio-mãe;
   soma do grupo = diárias(todas) + colchão.
3. **Check-out da filha + encerramento do grupo.** Check-out exige só a conta do quarto
   zerada. Ação de grupo `encerrar_grupo` recebe/fatura o folio-mãe e fecha.
   *Aceite:* quarto sai com folio-mãe aberto; grupo encerra quando o folio-mãe é quitado.
4. **Sinal único (Pagamentos).** Cobrança de sinal referenciando o grupo; ao pagar,
   `confirmar_grupo` confirma todas as filhas. Sem tocar no webhook/conciliação — só o
   hook em `services.confirmar_pagamento` (novo ramo para finalidade sinal de grupo).
   *Aceite:* pagar o sinal confirma o grupo inteiro; idempotente.
5. **Cancelamento e expiração.** `cancelar_grupo` (cascata, auditado); remover uma
   filha encolhe o bloco (libera a UH); expiração no nível do grupo.
   *Aceite:* cancelar a mãe cancela as filhas ativas; remover 1 quarto não derruba o
   resto; grupo pré-reserva vencido cancela junto.
6. **UI CRM.** Fluxo «Nova reserva de grupo» (período, titular, seleção de N quartos
   livres); detalhe do grupo (quartos + status, folio-mãe, botões check-in do grupo /
   encerrar / cancelar / remover quarto); selo de grupo no mapa.
   *Aceite:* montar um bloco de 3 quartos ponta a ponta pela tela; o mapa mostra o selo.

**Pode virar duas ondas** se o dono preferir: onda A = etapas 1–3 + 5 + 6 (agrupamento,
folio-mãe, cancelamento, telas); onda B = etapa 4 (sinal único integrado ao Pagamentos).

### Passo 5 — Reserva de grupo (implementado) ✓

Etapas 1–6 concluídas e testadas. Resolve o bloqueador RS-0151 do `AUDITORIA.md`.

- **Models** (migração `reservas/0006`): `GrupoReserva` (reserva-mãe, status derivado
  via `situacao()`), `Reserva.grupo` FK (`filhas`), `ContaHospedagem` agora é de um
  quarto **ou** o folio de um grupo (constraint XOR `conta_reserva_xor_grupo`).
- **Folio híbrido:** `fazer_checkin` roteia diária + colchão ao folio-mãe quando há
  grupo (`ContaHospedagem.lancar_diarias/lancar_colchoes_extras(usuario, reserva=)`);
  consumo fica na conta do quarto. Cada conta é fonte única do seu escopo.
- **Services** (`reservas/services.py`): `criar_grupo`, `adicionar_quarto` (UH
  específica, antioverbooking), `confirmar_grupo`, `checkin_grupo`, `cancelar_grupo`
  (cascata), `remover_do_grupo` (encolher), `receber_folio_grupo`, `encerrar_grupo`
  (exige folio zerado), `total_grupo` (consolidação só-leitura), `expirar_grupos_vencidos`.
- **Sinal único (Pagamentos):** `Cobranca.grupo_id` (migração `pagamentos/0003`);
  `criar_cobranca(grupo_id=)`; `confirmar_pagamento` confirma o grupo inteiro. Webhook,
  conciliação e status Safrapay **intocados**.
- **Cron:** `expirar_reservas` agora também expira grupos vencidos.
- **UI CRM** (`Reservas → Grupos`): lista, novo grupo, detalhe (folio, quartos,
  adicionar/confirmar/check-in/cancelar/remover/receber folio/encerrar/sinal). Selo de
  grupo no mapa de quartos. Nada de item novo na sidebar — é sub-tela de Reservas.
- **Check-out do quarto** liberado com o folio-mãe aberto (só a conta do quarto
  precisa zerar), conforme decidido.
- Testes: `GrupoReservaTests` (11) cobrindo diária→folio / consumo→quarto, colchão no
  folio, check-out com folio aberto, cancelamento cascata, encolher, encerrar exige
  folio zerado, expiração e sinal único. Suite completa: **353 testes**.

### Desvios/decisões registrados durante a implementação
- **Tabela de temporadas**: não existe tela de matriz de tarifas no CRM (a matriz
  `Tarifa` é gerida no admin). O "a partir de" honesto ficou na vitrine do site e na
  lista de tipos do CRM. Nada a corrigir na tela de temporadas (que só lista períodos).
- **FAQ do site**: o texto "berço e cama extra sem custo" **não existe** no site atual
  (era do protótipo). Sem FAQ para corrigir — quando houver, usar o texto do
  `Instruções.md`.
- **Governança**: a contagem de colchões é exposta por `colchoes_extras(reserva)`
  (service), sem inverter dependência. A faxina de *preparação* (pré-chegada) não é um
  fluxo existente na Governança hoje; a governança lê o service quando precisar montar
  o quarto.
- **Colchão no site (cotação/self-service)**: `cotacao_unidade()` está pronto e testado,
  mas a exibição da linha "N colchões · R$ X" na cotação do site entra junto do
  **Passo 5** (site vendendo por unidade, com nº de pessoas dirigindo a seleção).
- Suite completa: **342 testes** (um erro intermitente pré-existente de UUID, não
  relacionado a estes passos — reproduz e some entre execuções; passa limpo ao repetir).

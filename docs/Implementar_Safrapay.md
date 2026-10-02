# Implementar Safrapay (pagamento online)

Estado: **código pronto e os 3 meios VALIDADOS na HML** (Pix, cartão e boleto batem na
API de verdade; **cartão autoriza e captura** com os cartões homologados; webhook confirma
a reserva; site já cria a cobrança e mostra "Pagar agora"). O gargalo é o **processo de
homologação com a Safrapay** — não é programação.

> **Atalho para acelerar:** não espere o cartão. **Pix já está 100%.** Assim que o Token
> chegar, dá para vender no site por Pix imediatamente; cartão e boleto vêm logo atrás.

## Pix direto (fora do PSP) — implementado 01/10/2026

Opção para **não pagar taxa de adquirente no Pix**: as cobranças Pix saem por um **BR Code
gerado localmente** (padrão BACEN/EMV) a partir da chave da própria pousada — sem passar
pela Safrapay. **Cartão e boleto continuam pela Safrapay** normalmente. Como não há PSP,
**não há webhook**: a confirmação é **manual** (a recepção confere o extrato e dá baixa).

- **Ligar:** no `.env` → `PIX_DIRETO=1` + `PIX_CHAVE=<chave da pousada>` (CNPJ/e-mail/
  telefone/aleatória) + `PIX_RECEBEDOR_NOME` + `PIX_RECEBEDOR_CIDADE`.
- **Fluxo:** cobrança Pix → página pública mostra QR + copia-e-cola; hóspede paga no app do
  banco e toca "Já paguei" (só **avisa** a recepção). Recepção abre a cobrança no CRM →
  **"Confirmar recebimento do Pix"** → confirma o pagamento (e a reserva, se for sinal).
- **Código:** `apps/pagamentos/pix_br.py` (gerador EMV + CRC-16/CCITT), roteado em
  `services.criar_cobranca` (`gateway = "pix_direto"`); view `confirmar_recebimento`.
  Testes: `PixBRCodeTests`, `PixDiretoTests`.
- Desligado (`PIX_DIRETO=0`, default) → Pix volta a sair pelo `PAGAMENTOS_GATEWAY`.

## Homologação do cartão — CONCLUÍDA do nosso lado (01/10/2026)

A Safrapay (último e-mail) confirmou que o **antifraude deles está OK** e pediu "um novo
teste enviando todos os dados obrigatórios". Feito: rodamos a bateria completa pela nossa
integração contra a API HML, enviando o pacote antifraude inteiro (`remoteIp`,
`charge.sessionId`, `customer.phone/address`, `card.brand/cardholderDocument/
billingAddress/isPrivateLabel`).

**Resultado (estabelecimento HOMOL EC 1001188):**

- **6 cartões da tabela aprovados** a R$ 16,00 → `Authorized / Captured`
  (MC `5502093769921690`, MC `5502091221618516`, ELO `6277800000002390`,
  VISA `4444585001234562`, VISA `4444585006543215`, AMEX `375177012458884`).
- **ELO e AMEX a R$ 3,33** → `NotAuthorized / Denied` (caminho de recusa da tabela).
- **Pix** (EMV copia-e-cola) e **boleto** (linha digitável) criados na mesma rodada.

Confirmado que a API aceita o CVV tanto como `securityCode` quanto `cvv` (ambos
`Authorized/Captured`). O cartão genérico `4111…` continua recusado — use os homologados.

**Evidências para enviar** (pasta `evidencias/safrapay/`):
- `evidencias-safrapay-2026-10-01.json` — 10 transações com `merchantChargeId`,
  `sessionId`, `chargeId` e status de cada uma.
- `Resposta_Safrapay_2026-10-01.md` — texto do e-mail de resposta + tabela de IDs.

Regerar a qualquer momento: a tela **Pagamentos → Safrapay → «Gerar evidências»**
(`gerar_evidencias`) cria Pix + cartão + boleto; a bateria dos 6 cartões foi rodada via
`GatewaySafrapay` direto na HML.

**Suíte do projeto:** `manage.py test` → **715 testes OK** (skipped=8) em 01/10/2026,
incluindo os 39 de `apps.pagamentos` (fluxo da página, JSON do webhook, idempotência,
PAN não persistido, rate limit, segurança do webhook).

---

## O que já está pronto (não refazer)

- Provider real `GatewaySafrapay` (`apps/pagamentos/gateways.py`): auth (accessToken),
  **Pix** (copia-e-cola), **cartão** (crédito à vista), **boleto**, `consultar_status`,
  **estorno** (`PUT /v2/charge/cancelation`).
- **Cartão no site**: página pública `pagar/<token>/` captura número/validade/CVV/CPF e
  autoriza (`services.autorizar_cartao_online`). O PAN **só transita** para o gateway —
  nunca é gravado no nosso banco.
- **Webhook** (`pagamentos:webhook`) acha a cobrança por `gateway_id` → `confirmar_pagamento`
  → sinal → `reservas.confirmar_reserva` (idempotente).
- Gateway **simulado** como rede de segurança; alternância hml/prod por `SAFRAPAY_ENV`.

---

## Validação ao vivo na HML (03/09/2026)

Rodamos os 3 meios contra a API HML de verdade (auth OK, chaves já autenticam):

- **Pix**: cria cobrança + copia-e-cola EMV + consulta status. ✅ (**QR agora renderiza** na
  página pública `/pagar/<token>/`.)
- **Boleto**: cria (linha digitável/PDF). **Tem valor mínimo** — R$ 1,00 é recusado
  (`Amount inválido`), R$ 10,00 passa. Usar ≥ R$ 10 nas evidências.
- **Cartão**: o cartão de teste genérico **`4111 1111 1111 1111` é RECUSADO** na HML
  (`chargeStatus=NotAuthorized` / `transactionStatus=Denied`). É preciso o **cartão de
  teste que a Safrapay indica** para uma autorização aprovada.
- **Ambientes**: HML e prod **não debitam de verdade só por criar** a cobrança — o débito
  ocorre no **pagamento** (Pix pago / boleto pago / cartão autorizado com autoCapture).

**Bug corrigido (fail-safe):** `autorizar_cartao_online` confirmava pagamento sempre que a
requisição dava HTTP 200, ignorando o status da transação — cartão **recusado** virava
"pago". Agora o mapa de status é central (`gateways.status_pago`): só **Captured/Paid**
confirmam; **Denied/NotAuthorized/desconhecido não confirmam**.

## Caminho crítico (o que destrava tudo)

### Passo 1 — Gerar e enviar o pacote de evidências  ✅ **evidências geradas (01/10/2026) — falta só ENVIAR o e-mail**

A Safrapay pede as evidências de teste (Pix + cartão + boleto na HML) antes de avançar a
homologação. Estado:

1. ✅ Bateria rodada contra a HML (10 transações: 6 cartões aprovados, 2 recusados, Pix,
   boleto) — IDs em `evidencias/safrapay/evidencias-safrapay-2026-10-01.json`.
2. ✅ E-mail de resposta redigido — `evidencias/safrapay/Resposta_Safrapay_2026-10-01.md`.
3. ⛔ **Enviar** o e-mail (texto pronto) + anexar o JSON, respondendo o último e-mail deles.
4. As transações já aparecem no painel HML (Visão geral de transações, EC 1001188).

> Em **produção** mantenha `PAGAMENTOS_GATEWAY=simulado` enquanto o Token de prod não
> existir (hoje o Railway está em `simulado` — correto). O `.env` **local** já está em
> `safrapay`/HML para os testes.

### Passo 2 — Homologação assistida  ⛔ *depende deles*

Depois das evidências, a Safrapay costuma pedir testes específicos (ex.: o **cartão de
teste que eles indicam**). Feito isso, o **Token** aparece em **Developers → Keys**.

### Onde coletar as chaves (HML)

Portal HML **<https://portal-hml.safrapay.com.br/>** (mesmo login/senha do "developers")
→ **GERENCIAMENTO → CHAVES DE ACESSO**:
- **MerchantId** → `SAFRAPAY_ID`
- **MerchantToken** → `SAFRAPAY_TOKEN`
- (o **Código de Ativação** → `SAFRAPAY_CODIGO_ATIVACAO`)

**Estabelecimento de teste (HML):** `SafraPay HOMOL EC 1001188` — é nele que as cobranças
criadas em HML aparecem (portal → **Visão geral de transações**). É de lá que saem os
prints das evidências.

### Passo 3 — Ligar em produção (HML → prod)  ✅ *nós, minutos*

No `.env` (nunca commitar segredos):

```env
PAGAMENTOS_GATEWAY=safrapay
SAFRAPAY_ENV=hml            # troque para prod após validar em HML
SAFRAPAY_ID=...
SAFRAPAY_CODIGO_ATIVACAO=...
SAFRAPAY_TOKEN=...          # o Merchant Token liberado no passo 2
```

Cadastrar o **webhook** no painel Safrapay apontando para:
`https://SEU_DOMINIO/crm/pagamentos/webhook/`

Validar em HML → **primeira venda por Pix sai imediatamente** → depois cartão/boleto.

---

## Notas técnicas

- **Cartão sem token**: a cobrança de cartão é criada **pendente** e só é autorizada
  quando o hóspede digita o cartão na página pública (não cobra na criação).
- **Webhook em localhost não chega** — por isso existe `consultar_status` (o botão "Já
  paguei" consulta o status real e só confirma se estiver pago). Em produção, o webhook
  público confirma sozinho.
- **PCI / cartão**: hoje o número passa pelo nosso servidor a caminho do gateway (não é
  persistido). Para reduzir escopo PCI no futuro, avaliar **tokenização/checkout hospedado**
  da Safrapay — fica como melhoria, não bloqueia a operação.
- **Idempotência**: `confirmar_pagamento` é idempotente (webhook + consulta não confirmam
  em dobro).

## Fast-follows (não bloqueiam a primeira venda)

- Lançar o dinheiro online no **Financeiro sem passar pelo caixa** (adiantamento/folio).
- **Estorno integrado** ao Financeiro (hoje o estorno é no gateway + auditoria).

## Checklist rápido

- [x] Gerar evidências (Pix + cartão + boleto) na HML — 01/10/2026
- [x] Validar cartão (6 homologados aprovados + recusa) na HML — 01/10/2026
- [ ] **Enviar o e-mail de resposta + JSON à Safrapay** ← próximo passo real
- [ ] Receber o Token de **produção** (Developers → Keys)
- [ ] Railway (produção): `PAGAMENTOS_GATEWAY=safrapay` + credenciais + `SAFRAPAY_ENV=prod`
- [ ] Cadastrar webhook `/crm/pagamentos/webhook/` no painel Safrapay
- [ ] Primeira venda real por Pix → depois cartão e boleto

_Relacionado: tela `Pagamentos → Safrapay` (checklist ao vivo via `status_credenciais`)._

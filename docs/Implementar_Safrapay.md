# Implementar Safrapay (pagamento online)

Estado: **código pronto** (Pix, cartão e boleto batem na API HML de verdade; webhook
confirma a reserva; site já cria a cobrança e mostra "Pagar agora"). O gargalo é o
**processo de homologação com a Safrapay** — não é programação.

> **Atalho para acelerar:** não espere o cartão. **Pix já está 100%.** Assim que o Token
> chegar, dá para vender no site por Pix imediatamente; cartão e boleto vêm logo atrás.

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

### Passo 1 — Gerar e enviar o pacote de evidências  ⛔ **ainda não foi feito — fazer agora**

A Safrapay **só libera o Token** depois de receber evidências de teste (Pix + cartão +
boleto no formato HML). Como fazer:

1. Entrar no CRM em **Pagamentos → Safrapay** (`/crm/pagamentos/safrapay/`).
2. Clicar em **«Gerar evidências (Pix + cartão + boleto)»** — o CRM cria 3 cobranças no
   sandbox e monta o **JSON no formato HML** + prints.
3. **Baixar o JSON** e os prints.
4. **Anexar no formulário de integração da Safrapay** (ou enviar no e-mail de integração
   que eles indicarem). É este envio que dispara a liberação.

> Mantenha `PAGAMENTOS_GATEWAY=simulado` enquanto o Token não existir.

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

- [ ] **Gerar evidências no CRM e enviar à Safrapay** ← próximo passo real
- [ ] Receber o Token (Developers → Keys)
- [ ] `.env`: `PAGAMENTOS_GATEWAY=safrapay` + credenciais + `SAFRAPAY_ENV=hml`
- [ ] Cadastrar webhook `/crm/pagamentos/webhook/` no painel
- [ ] Testar Pix em HML → ligar; depois cartão e boleto
- [ ] Virar `SAFRAPAY_ENV=prod` após validação

_Relacionado: tela `Pagamentos → Safrapay` (checklist ao vivo via `status_credenciais`)._

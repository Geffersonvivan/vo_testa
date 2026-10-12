# Resposta à Safrapay — novo teste com dados obrigatórios (01/10/2026)

**Anexo:** `evidencias-safrapay-2026-10-01.json`
**Estabelecimento (HML):** SafraPay HOMOL EC 1001188 · **Ambiente:** Homologação

---

## Texto do e-mail

> Bom dia! Tudo bem?
>
> Feito. Rodamos um novo teste pela nossa integração enviando **todos os dados
> obrigatórios** do antifraude — `remoteIp`, `charge.sessionId`, `customer` com
> `phone` e `address`, e no cartão `brand`, `cardholderDocument`, `billingAddress`
> e `isPrivateLabel` — usando os cartões da tabela de homologação (crédito à vista,
> e-commerce, autoCapture).
>
> **Resultados (estabelecimento HOMOL EC 1001188):**
>
> Aprovados a R$ 16,00 → *Authorized / Captured*:
> - Mastercard 5502093769921690 — chargeId `6d9d6d2a-adb4-4c95-82e5-48971b496ba2`
> - Mastercard 5502091221618516 — chargeId `99b1bbaf-d8aa-41cb-89f0-c6eb0f80945a`
> - Elo 6277800000002390 — chargeId `6e4957a8-09a1-476f-84c2-0b4421845b22`
> - Visa 4444585001234562 — chargeId `580672af-beb4-44c7-87f6-b51a1469bef3`
> - Visa 4444585006543215 — chargeId `bb8ff07e-326e-43ed-9630-2589f0d615d3`
> - Amex 375177012458884 — chargeId `e7409953-701d-44f2-9dbc-c6e02203d91f`
>
> Caminho de recusa a R$ 3,33 → *NotAuthorized / Denied* (conforme a coluna
> "transação negada" da tabela):
> - Elo 6277800000002390 — chargeId `33a5d00a-1349-46c5-bcd4-f3bf8065fd6e`
> - Amex 375177012458884 — chargeId `353cbf36-60e9-4938-809b-ef6fadfdf3b9`
>
> **Pix** e **boleto** também validados pela mesma integração na HML:
> - Pix (copia-e-cola EMV) — chargeId `401d2999-33eb-4909-8cf9-1699fe4a480d`
> - Boleto (linha digitável) — chargeId `bc8088dd-6082-4ec3-b4e7-b0e00b2c3b8c`
>
> As transações devem estar visíveis no painel de vocês (Visão geral de transações).
> Segue em anexo o JSON com o detalhe de cada uma (merchantChargeId, sessionId,
> chargeId e status).
>
> Podem seguir com a homologação e nos orientar sobre a **liberação do ambiente de
> produção** (credenciais/Token de produção e cadastro do webhook de notificação)?
> O webhook do nosso lado já está pronto em:
> `https://www.pousadavotesta.com.br/crm/pagamentos/webhook/`
>
> Obrigado!

---

## Tabela-resumo (para conferência interna)

| Meio | Bandeira / tipo | Cartão | Valor | Resultado | chargeId |
|---|---|---|---|---|---|
| Cartão | MC | 5502093769921690 | R$ 16,00 | Authorized/Captured | 6d9d6d2a-adb4-4c95-82e5-48971b496ba2 |
| Cartão | MC | 5502091221618516 | R$ 16,00 | Authorized/Captured | 99b1bbaf-d8aa-41cb-89f0-c6eb0f80945a |
| Cartão | ELO | 6277800000002390 | R$ 16,00 | Authorized/Captured | 6e4957a8-09a1-476f-84c2-0b4421845b22 |
| Cartão | VISA | 4444585001234562 | R$ 16,00 | Authorized/Captured | 580672af-beb4-44c7-87f6-b51a1469bef3 |
| Cartão | VISA | 4444585006543215 | R$ 16,00 | Authorized/Captured | bb8ff07e-326e-43ed-9630-2589f0d615d3 |
| Cartão | AMEX | 375177012458884 | R$ 16,00 | Authorized/Captured | e7409953-701d-44f2-9dbc-c6e02203d91f |
| Cartão | ELO | 6277800000002390 | R$ 3,33 | NotAuthorized/Denied | 33a5d00a-1349-46c5-bcd4-f3bf8065fd6e |
| Cartão | AMEX | 375177012458884 | R$ 3,33 | NotAuthorized/Denied | 353cbf36-60e9-4938-809b-ef6fadfdf3b9 |
| Pix | — | — | R$ 16,00 | criado (EMV) | 401d2999-33eb-4909-8cf9-1699fe4a480d |
| Boleto | — | — | R$ 16,00 | criado (linha digitável) | bc8088dd-6082-4ec3-b4e7-b0e00b2c3b8c |

**Dados obrigatórios enviados em cada requisição de cartão:**
`remoteIp`, `charge.sessionId`, `customer.phone`, `customer.address`,
`card.brand`, `card.cardholderDocument`, `card.billingAddress`, `card.isPrivateLabel`.

# Evidências Safrapay (homologação)

Pasta para o pacote enviado à SafraPay **antes** do Token ser liberado.

| Item | Onde |
|------|------|
| JSON dos payloads HML | `safrapay-evidencias-homologacao.json` |
| Prints das telas de pagamento | `prints/` (Pix, cartão, boleto) |

## Como gerar de novo

1. CRM → `/crm/pagamentos/safrapay/` → **Gerar evidências**
2. O JSON é salvo aqui automaticamente e também baixado pelo navegador
3. Coloque os screenshots em `prints/` com nomes claros, ex.:
   - `01-pix.png`
   - `02-cartao.png`
   - `03-boleto.png`

JSON e prints não vão para o git (só esta pasta + README).

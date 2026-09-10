# SafraPay — Decisão de integração (maquininha na recepção)

**Data:** 10/09/2026 · **Decisão:** Caminho **B — maquininha avulsa + baixa no CRM**.

## Contexto
A SafraPay encaminhou o kit de **homologação SafraPay Store** (pasta
`Homologação_Máquina_Cartão/`): questionário de parceiro, manual e instruções. Ao ler os
documentos, ficou claro que esse fluxo é para **construir um aplicativo Android nativo que
roda DENTRO do terminal** (Smart POS SafraPay), usando o **SDK Java** deles (`.aar`,
classe `Gerenciador`, `minSdk=22`, sem Google Play Services, Manifest `category="safra"`).
Isso é um **stack diferente** do nosso CRM (Django/web) — seria um app novo e separado.

## Caminhos avaliados
| Caminho | O que é | Esforço | Decisão |
|---|---|---|---|
| **A) App na maquininha (Store)** | App Android nativo no terminal, integra via SDK; puxa valor do CRM e devolve "pago" | Alto (dev Android, homologação de APK) | ❌ Descartado agora |
| **B) Maquininha avulsa + baixa no CRM** | Recepção digita o valor na maquininha comum e marca "pago" no CRM | Zero | ✅ **Escolhido** |
| **C) Pix/link online (gateway REST)** | CRM gera Pix/link (SafraPay REST, já iniciado); hóspede paga pelo celular | Baixo (já quase pronto) | ⏭️ Porta aberta p/ depois |

## O que muda
- **Não faremos** a homologação SafraPay Store → **descartados** o Questionário de
  Parceiro, o PPT e o app Android. O kit fica só como **referência histórica**.
- Precisamos de uma **maquininha SafraPay comum** (credenciamento de lojista padrão),
  **não** o fluxo de parceiro/desenvolvedor.

## Como funciona no CRM (já implementado)
- No **check-out**, a recepção cobra na maquininha e registra o pagamento no **caixa de
  Reservas** (`receber_pagamento` → `receber_no_caixa`, `forma = cartão`).
- **Fail-safe** existente: cartão **recusado não pode ser marcado como pago**.
- **NSU/autorização (novo, 10/09/2026):** campo opcional `MovimentoCaixa.autorizacao`
  (migração `nucleo.0033`). Capturado no formulário de pagamento da reserva
  (`RecebimentoForm.autorizacao`) e exibido na lista de pagamentos do folio — para
  **conciliar** o extrato da SafraPay com o CRM. Retrocompatível (os demais caixas —
  Loja/Restaurante/Lavanderia — não precisam preencher).

## Texto de resposta para a SafraPay (ajustar o pedido)
> Boa tarde! Obrigado pelas informações.
>
> Reavaliamos aqui e **não vamos desenvolver aplicativo para o terminal** (fluxo SafraPay
> Store / homologação de app). O que precisamos, na verdade, é de uma **maquininha comum
> (POS avulsa)** para a recepção da nossa pousada — **crédito, débito e Pix** — com o
> **credenciamento de lojista padrão**.
>
> Podem, por gentileza, me direcionar para esse processo (credenciamento comum) em vez da
> homologação de aplicativo? Qualquer dúvida, fico à disposição. Obrigado!

## Futuro (se e quando fizer sentido)
- **Caminho C (Pix/link):** já iniciado no projeto (`docs/Implementar_Safrapay.md`) — bom
  para o site e para cobrança à distância.
- **Caminho A (app integrado):** só se a operação crescer e justificar o investimento em
  desenvolvimento Android.

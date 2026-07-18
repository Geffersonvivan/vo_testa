# Relação de produtos para NCM — Pousada Vô Testa

Documento para o **contador** preencher os códigos fiscais dos produtos **revendidos**
(restaurante, loja, frigobar) — necessários para a **NFC-e** (consumo/ICMS).

> ⚠️ **A lista abaixo é um ponto de partida** (produtos de demonstração do sistema).
> A pousada deve **substituir/completar** com o catálogo real de tudo que vende ao hóspede.
> O contador preenche as colunas fiscais.

> 🎯 **Por que cada coluna importa (confirmado pela Focus NFe):** a Focus faz só a
> **mensageria** com a SEFAZ — ela **não calcula imposto nem valida preenchimento**. Quem
> monta e calcula tudo é o **nosso CRM**. Se um NCM/CST/CFOP/alíquota vier errado, **a
> SEFAZ rejeita** e a nota volta com o motivo (não há correção automática). Por isso todas
> as colunas abaixo precisam vir **completas e corretas** — campo em branco ou errado =
> nota rejeitada.

Empresa: **POUSADA VO TESTA LTDA** · CNPJ **26.003.246/0001-00** · Itá/SC ·
Regime **Lucro Presumido** · CNAE **55.10-8-01 (Hotéis)**.

---

## Produtos revendidos

| Produto | Categoria | Preço venda | **NCM** | **CFOP** | **CST/CSOSN** | **Origem** | **Alíq. ICMS** | **ST?** | **CEST** |
|---|---|---|---|---|---|---|---|---|---|
| Água mineral 500 ml | Bebidas | R$ 4,00 | | | | | | | |
| Água 500 ml | Bebidas | R$ 5,00 | | | | | | | |
| Refrigerante lata | Bebidas | R$ 7,00 | | | | | | | |
| Cerveja long neck | Bebidas | R$ 12,00 | | | | | | | |
| Amendoim (pacote) | Frigobar | R$ 8,00 | | | | | | | |
| Barra de cereal | Frigobar | R$ 6,00 | | | | | | | |
| *(adicionar os demais produtos reais…)* | | | | | | | | | |

---

## Observações para o contador
- **Contexto da operação:** toda venda é a **consumidor final**, **dentro de SC**, presencial
  (frigobar, restaurante da piscina, loja) — isso orienta o **CFOP** (venda ao consumidor,
  com ou sem ST).
- **Bebidas (cerveja, refrigerante, água):** normalmente têm **Substituição Tributária (ST)**
  em SC — indicar **ST = Sim** e o **CEST** quando aplicável.
- **Origem:** 0 = nacional, 1 = importação direta, etc.
- **CST × CSOSN:** como o regime é **Lucro Presumido** (não Simples), usar **CST** (não CSOSN).
- **Alíquota ICMS:** informar a alíquota efetiva por produto (interna SC), mesmo quando ST —
  o nosso sistema calcula a base e o valor; a Focus só transmite.
- O sistema já classifica cada item como **CONSUMO** (produto) — falta só o
  **NCM · CST · Alíq. ICMS · CFOP · Origem** (+ ST/CEST quando houver).

## ⚠️ Pré-requisito da NFC-e
A emissão de **NFC-e depende da Inscrição Estadual (IE)**, que a empresa **ainda não possui**
(setor de constituição providenciando) + do **CSC** na SEFAZ-SC. Enquanto a IE não sair,
**a NFC-e fica bloqueada** — a **NFS-e (hospedagem)** segue independente e já pode ser emitida.

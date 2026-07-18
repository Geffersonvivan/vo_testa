# Checklist para o contador — dados fiscais (Pousada Vô Testa)

Documento para **encaminhar ao contador**. Objetivo: reunir os parâmetros fiscais para
configurar a emissão de nota eletrônica no sistema (NFS-e de serviço + NFC-e de consumo).
Complementa o plano técnico em `docs/Implementar_fiscal.md`. Município: **Itá/SC**.

---

## 1. Enquadramento
- [ ] **Regime tributário** atual (Simples Nacional / Lucro Presumido / Real). Se Simples, **qual anexo**.
- [ ] **Itá/SC já emite NFS-e pelo Emissor Nacional** (padrão nacional)? Desde quando?

## 2. Dados da empresa (emitente)
- [ ] CNPJ, razão social, nome fantasia, endereço fiscal completo + CEP.
- [ ] **Inscrição Estadual (IE)** e **Inscrição Municipal (IM)** — números e se estão **ativas**.
- [ ] **CNAE** principal (e secundários).

## 3. NFS-e — serviços (diária, lavanderia, day use, taxas)
- [ ] **Código do serviço (lista LC 116)** de cada: hospedagem/diária, lavanderia, day use, taxas.
- [ ] **Alíquota de ISS** de cada serviço em Itá.
- [ ] Há **retenção de ISS**? Algum **benefício/regime especial**?

## 4. NFC-e — produtos (restaurante, loja, frigobar)
Por produto (ou por categoria):
- [ ] **NCM**
- [ ] **CFOP** de venda ao consumidor
- [ ] **CST** (ou **CSOSN**, se Simples)
- [ ] **Origem** da mercadoria (0 = nacional, etc.)
- [ ] **Alíquota de ICMS**
- [ ] **Substituição tributária (ST)** — atenção às **bebidas** (cerveja/refri) + **CEST** quando aplicável.
- [ ] **CSC (Código de Segurança do Contribuinte)** + **ID/Token do CSC** (SEFAZ-SC — gera o QR da NFC-e).
- [ ] Qual **série** usar na NFC-e.

## 5. Certificado e acessos
- [ ] **Certificado Digital A1 (e-CNPJ)** — arquivo `.pfx` + senha. Quem tem/providencia?
- [ ] Se usarmos **Focus NFe**: quem abre a conta e gera o **token de API** (homologação e produção).

## 6. Política de emissão (operacional)
- [ ] Emitir a nota **no check-out** (conta consolidada) ou por lançamento?
- [ ] Quando **quem paga ≠ hóspede** (agência/empresa): quem é o **tomador** da NFS-e?
- [ ] Confirmar fluxo: **homologação (testes) → produção**.

---

## Mínimo para começar a homologar (prioridade)
1. Regime tributário.
2. Confirmação do Emissor Nacional em Itá.
3. Certificado A1.
4. Código LC116 + alíquota ISS da **diária**.
5. NCM/CFOP/CST/origem das **bebidas/produtos mais vendidos**.

Com isso já emitimos as primeiras notas de teste (1 diária em NFS-e, 1 venda em NFC-e) no
**sandbox**, sem custo.

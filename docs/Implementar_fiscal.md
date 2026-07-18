# Implementar Fiscal — CRM Pousada Vô Testa

Plano de implementação da emissão de nota fiscal eletrônica (módulo Fiscal, §14 / fase 2).
Documento vivo — atualizar conforme contador/prefeitura confirmarem os parâmetros.

> **Município:** Itá/SC · **Última atualização:** julho/2026

---

## 0. Dados confirmados pelo contador (jul/2026) ✅

**Empresa:** POUSADA VO TESTA LTDA · CNPJ **26.003.246/0001-00** · Inscrição Municipal
**4829** · **sem Inscrição Estadual** · Rod SC 155, Km 129, Lago Azul, **Itá/SC** ·
CNAE **55.10-8-01 (Hotéis)** · Natureza 206-2 (Ltda) · Porte ME ·
Contador **Escritório Contábil Itá Ltda**.

- **Regime tributário:** **Lucro Presumido** → usar **CST** (não CSOSN).
- **NFS-e:** Itá emite pelo **Emissor Nacional (Portal Nacional)** ✅.
- **NFS-e — hospedagem/diária:** código de serviço **`090101 — HOSPEDAGEM EM HOTELARIA`**;
  **ISS 4%**; **sem retenção**; **sem benefício/regime especial**.
  *(Lavanderia, quando entrar, é outro item da LC 116 — pedir ao contador.)*
- **NFC-e:** **BLOQUEADA por ora** — a empresa **não tem Inscrição Estadual**; sem IE não
  há habilitação de NFC-e nem CSC. Setor de constituição providenciando a IE. A **série**
  não é definida pelo escritório (o sistema usa série 1 por padrão).
- **Produtos revendidos:** o contador precisa da **relação com NCM** → template em
  `docs/Produtos_para_NCM.md` (a pousada completa; o contador preenche os códigos).

**Conclusão de prioridade:** **NFS-e (hospedagem) já pode ser homologada** (falta só o
certificado A1 + conta no provedor). **NFC-e** aguarda a **Inscrição Estadual**.

---

## 1. Situação atual (o que já existe no CRM)

O alicerce fiscal **já está pronto**: a 4ª "veia" transversal do sistema classifica
**toda linha** vendável e **todo lançamento de conta** como:

- **SERVIÇO** → diária/hospedagem, lavanderia do hóspede, taxas, day use → **NFS-e** (ISS)
- **CONSUMO** → loja, restaurante, frigobar → **NFC-e / NF-e** (ICMS)

Isso é obrigatório desde a fase 1 (`NaturezaFiscal.SERVICO | CONSUMO`, sem default), justamente
para permitir a nota separada depois. Falta o **motor de emissão** (este documento).

---

## 2. Os dois documentos que a pousada precisa

| Natureza | Documento | Órgão | Padrão |
|---|---|---|---|
| **Serviço** (diária, lavanderia) | **NFS-e** | Prefeitura (ISS) | **NFS-e Nacional** (Emissor Nacional) |
| **Consumo** (restaurante, loja, frigobar) | **NFC-e** (consumidor) / NF-e (B2B) | SEFAZ-SC (ICMS) | padrão estadual consolidado |

---

## 3. Mudança-chave: NFS-e Nacional (a partir de 01/07/2026)

Desde **1º/07/2026**, os municípios de SC emitem NFS-e **exclusivamente pelo Emissor
Nacional** (Portal Nacional da NFS-e, infraestrutura federal), por força da **Reforma
Tributária** (EC 132/2023 + **LC 214/2025**). O sistema municipal antigo deixa de emitir;
a apuração do ISS continua na prefeitura, mas a **nota sai no padrão nacional único**.

**Impacto positivo:** some o risco "o provedor cobre o sistema específico de Itá?".
Com o padrão nacional, o layout é o mesmo para todos os municípios — basta o provedor
falar **NFS-e Nacional**.

⚠️ **Confirmar com contador/prefeitura:** se **Itá já concluiu a adesão/integração** ao
Emissor Nacional (em SC, 295 municípios aderiram; ~120 ainda integravam no início de 2026).
Em julho/2026 é provável que já esteja ativo — confirmar por telefonema/contador.

⚠️ **Reforma Tributária (transição 2026–2033):** CBS (federal) + IBS (estadual/municipal)
vão substituir PIS/COFINS/ICMS/ISS. O padrão nacional da NFS-e já nasce preparado.
O módulo deve mirar **padrão nacional / CBS-IBS**, com o **contador** definindo o regime
na transição.

---

## 4. O que é preciso ter (fora do software)

1. **Contador da pousada** — peça-chave. Define: regime tributário (Simples? Presumido?),
   código de serviço (lista LC 116), alíquota de ISS, CFOP/CST/CSOSN e NCM dos produtos,
   e a situação na transição CBS/IBS.
2. **Certificado Digital A1 (e-CNPJ)** — arquivo `.pfx`, validade 1 ano. Assina o XML.
   Usar **A1** (não A3/token) — funciona em servidor/API.
3. **Inscrições ativas** — Estadual (SEFAZ) e Municipal (Prefeitura de Itá).
4. **CSC (Código de Segurança do Contribuinte)** — solicitado na SEFAZ-SC (QR da NFC-e).

---

## 5. Serviço necessário (provedor fiscal)

Recomendação: **não construir o motor do zero** (schemas XML, assinatura, webservices,
contingência, atualizações legais constantes). Integrar um **provedor fiscal** via API —
mesmo padrão do módulo de Pagamentos (gateway plugável, sandbox → produção).

O provedor deve emitir **os dois**: **NFS-e Nacional** + **NFC-e SEFAZ-SC**.

| Provedor | Observação |
|---|---|
| **PlugNotas** (Tecnospeed) | Boa cobertura, NFS-e Nacional + NFC-e, sandbox generoso. **1ª recomendação.** |
| **Focus NFe** | API simples e bem documentada. Ótima 2ª opção. |
| NFE.io / eNotas / WebmaniaBR | Alternativas — comparar preço. |

Obs.: a NFS-e Nacional tem **API pública** e **emissor web gratuito**. Para volume baixo dá
pra emitir NFS-e **manualmente de graça** no portal; para **integração automática** ao CRM
(nota saindo no check-out), o provedor resolve NFS-e + NFC-e num só lugar.

### 5.1 Comparativo de preços (levantado em jul/2026)

| Provedor | Preço | Transparência | Observação |
|---|---|---|---|
| **Focus NFe** — Plano Solo | **R$ 89,90/mês** · 1 CNPJ · **100 notas incluídas** · **R$ 0,10/nota adicional** · 30 dias grátis | ✅ preço público | Emite NF-e / **NFS-e (Nacional)** / NFC-e / CT-e / MDF-e num só plano. **Recomendado pela previsibilidade.** |
| **PlugNotas** | **não publicado no site** (modelo por consumo/créditos; valor na Área do Cliente / comercial) | ⚠️ opaco | Forte em cobertura de cidades; exige criar conta/contatar pra saber o preço. |
| **Governo (direto)** | **R$ 0** (só o A1) | ✅ | NFS-e no `nfse.gov.br` (grátis) + NFC-e SEFAZ-SC. Grátis, porém todo o esforço/risco de integração é seu. |

**Dimensionamento (pousada 24 quartos):** ~1 NFS-e por check-out + NFC-e das vendas
(restaurante/loja/frigobar) pode **passar de 100 notas/mês em alta temporada**. No Focus,
excedente a R$ 0,10 cada (ex.: 300 notas ≈ R$ 110/mês) — barato e previsível.

**Decisão de custo:** os ~R$ 90/mês pagam **conveniência + automação** (principalmente a
NFC-e). A **NFS-e** ainda pode ser emitida **de graça** no `nfse.gov.br`. Por isso o módulo
tem **gateway plugável** (`focus` × `governo` × `simulado`) — dá pra começar grátis e trocar
depois sem retrabalho. **Escolha inicial sugerida: Focus NFe** (teste grátis 30 dias).

---

## 6. Custos (aproximados — confirmar com o fornecedor)

| Item | Custo |
|---|---|
| Certificado A1 (e-CNPJ) | ~R$ 130–250/ano — único gasto para começar |
| Provedor (NFS-e Nacional + NFC-e) | ~R$ 50–150/mês (volume pequeno) ou por nota |
| Emissor Nacional / CSC / inscrições | **Grátis** |
| Homologação (testes / sandbox) | **~R$ 0** |

**Custo mínimo para começar:** homologação ~R$ 0 + A1 (~R$ 150). Só se paga o provedor
ao virar **produção**.

---

## 7. Desenho do módulo `apps/fiscal` (a implementar)

Mesmo padrão do `apps/pagamentos` (gateway plugável):

- **Cadastro fiscal** — por **produto** (NCM, CFOP, CST/CSOSN, origem) e por **serviço**
  (código LC 116, alíquota ISS). Dados vindos do contador.
- **Gateway fiscal plugável** (`fiscal/gateways.py`) — provider (PlugNotas/Focus) com
  `PAGAMENTOS_GATEWAY`-like setting; **sandbox/homologação** por padrão.
- **Emissão** — ao fechar conta/venda, monta o payload a partir dos lançamentos (natureza,
  valores, tomador/hóspede, códigos fiscais), chama o provedor, guarda o retorno (número,
  chave, XML, PDF/DANFE, status). NFS-e para serviço; NFC-e para consumo.
- **Cancelamento / contingência / carta de correção**.
- **Conciliação** — nota × lançamento (extrato por natureza já existe na conta).
- **Trilha de auditoria** (padrão do projeto).

---

## 8. Passos para proceder

1. **Contador:** confirmar (a) regime tributário e (b) se **Itá já está no Emissor Nacional**.
2. **Certificado A1** (se ainda não tiver).
3. Abrir conta de **homologação** no PlugNotas ou Focus NFe (grátis).
4. **Implementar o `apps/fiscal`** (esqueleto plugável) mirando **NFS-e Nacional + NFC-e**.
5. **Homologação:** emitir notas de teste (1 NFS-e de diária, 1 NFC-e do restaurante),
   validar retorno/DANFE/QR/cancelamento.
6. **Virada para produção** — primeiras notas reais conferidas com o contador.

---

## 9. Decisões / pendências

- [ ] Regime tributário da pousada (contador).
- [ ] Confirmar adesão de Itá/SC ao Emissor Nacional de NFS-e (contador/prefeitura).
- [ ] Certificado A1 disponível?
- [ ] Provedor fiscal escolhido (PlugNotas × Focus NFe).
- [ ] Cadastro fiscal por produto/serviço (códigos do contador).

---

## Fontes (julho/2026)

- NFS-e via Emissor Nacional a partir de 01/07/2026 — Município de Itajaí: <https://nfse.itajai.sc.gov.br/>
- 120 municípios de SC ainda integrando a NFS-e nacional — Blog do Prisco:
  <https://www.blogdoprisco.com.br/120-municipios-de-sc-ainda-nao-concluiram-a-integracao-da-nfs-e-nacional-e-podem-sofrer-bloqueios-de-transferencias-de-recursos-ja-em-janeiro-de-2026/>
- NFS-e Nacional — Espaço Legislação (TOTVS): <https://espacolegislacao.totvs.com/nfs-e-nacional/>
- Adesão NFS-e Nacional (Tecnospeed): <https://blog.tecnospeed.com.br/adesao-nfs-e-nacional-novos-municipios/>

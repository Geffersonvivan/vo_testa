# Checklist — CRM Vô Testa 100% (vivo)

> Atualizado em 11/09/2026. Marque `[x]` conforme concluir. 🔴 = **bloqueia a inauguração**.
> **Responsável:** 💻 código (Claude) · 🧑‍💼 operação (Gefferson/equipe) · 🌐 terceiro (Meta/Safrapay/contador/Serpro).

---

## 1. 🔌 Integrações externas (dependem de terceiros)

### WhatsApp Cloud API — 🔴 crítico p/ captação
- [ ] 🌐 Registrar o número novo na **WABA do portfólio "Pousada Vô Testa"** (não instalar no app comum)
- [ ] 🌐 Aprovar o template **`boas_vindas_fundador`** (Marketing, pt-BR)
- [ ] 🌐 Gerar **token permanente** + **Phone Number ID** + **App Secret**
- [ ] 💻 Preencher `.env` de produção + apontar webhook (`/whatsapp/webhook/`)
- [ ] 🧑‍💼 Disparo de teste (1 número) → depois lista de fundadores
- *(código pronto e testado — ver `docs/Marketing/CRM_WhatsApp.md` Anexo C)*
- [ ] 💻 **Análise de links recebidos (segurança do atendente)** — extrair URLs das
      mensagens que chegam, checar reputação (**Google Safe Browsing** grátis + heurísticas:
      encurtador, domínio parecido, punycode, IP, domínio novo) e mostrar no chat com selo
      🟢/🟡/🔴, **links não-clicáveis por padrão** + aviso antes de abrir. Reforço: VirusTotal,
      expansão de encurtador e filtro por IA (Claude) p/ phishing. ⚠️ **Cuidar de SSRF** ao
      expandir URL (bloquear IPs internos/privados, timeout, não seguir p/ rede interna).
      *(o número fica na API/CRM → temos controle total pra bloquear o clique antes do atendente)*

### Pagamentos — 🔴 crítico p/ cobrança
- [ ] 🌐 **Maquininha Safrapay** — credenciamento comum ativo (Caminho B, ver `docs/SafraPay/DECISAO.md`)
- [ ] 🧑‍💼 Testar cobrança + baixa no CRM com **NSU** (conciliação)
- [ ] 💻 *(opcional)* Ligar **gateway online Pix/link** (SafraPay REST — já iniciado) p/ cobrança à distância

### Fiscal (nota) — 🔴 bloqueadores burocráticos (começar cedo)
- [ ] 🧑‍💼 Obter **Inscrição Estadual** (necessária p/ NFC-e)
- [ ] 🧑‍💼 Adquirir **certificado digital A1**
- [ ] 🧑‍💼 Escolher **provider**: Focus NFe (R$89,90/mês) ou rota grátis governo
- [ ] 💻 Ligar o provider real + cadastrar produtos (NCM) — *(esqueleto pronto, `docs/Implementar_fiscal.md`)*
- [ ] 🧑‍💼 Confirmar com contador os parâmetros da NFS-e da diária (código, ISS, regime)

### FNRH Digital (Embratur) — não bloqueia (funciona local)
- [ ] 🧑‍💼 Obter **credenciais SNRHos** (via Cadastur)
- [ ] 🧑‍💼 País ISO alpha-2 + cidade código IBGE no cadastro; teste em homologação

### Campanhas Meta (Instagram/Facebook) — captação + demografia
- [ ] 💻 Rodar **uma vez** em produção `manage.py popular_campanha_fundador_2` (cria LP + campanha no CRM)
- [ ] 💻 Confirmar **`META_CAPI_TOKEN`** no `.env` de produção (Pixel já roda; token liga o CAPI server-side)
- [ ] 🧑‍💼 Anunciar com **UTMs** p/ a LP (`/lp/fundador-2/?utm_source=instagram&utm_medium=paid&utm_campaign=fundador-2`)
- [ ] 🧑‍💼 **Demografia do público** (idade/gênero/cidade) → **Gerenciador de Anúncios → Detalhar (Breakdown)** — agregado, grátis
- [ ] 💻 *(opcional)* Puxar os **breakdowns para o CRM** via Marketing API (Insights) — *(Fase C, `Gestor_Impulsionamento_CRM.md` §C.4)*
- *(dado por lead — sexo/UF/dispositivo — já aparece no "Perfil estimado" do lead; ver `apps/comercial/enriquecimento.py`)*

---

## 2. ✅ Validar módulos já construídos (homologação com o usuário)
- [x] Núcleo (caixa testado em 04/07/2026)
- [ ] 🧑‍💼 Reservas (ciclo, mapa, troca de quarto, folio)
- [ ] 🧑‍💼 Estoque · [ ] Loja (PDV) · [ ] Restaurante · [ ] Lavanderia
- [ ] 🧑‍💼 Governança · [ ] Manutenção · [ ] Escala
- [ ] 🧑‍💼 Comercial (funil, LP, campanhas) · [ ] Pagamentos · [ ] Portal do hóspede
- [ ] 🧑‍💼 Relatórios · [ ] Auditoria

---

## 3. 📸 Dados e conteúdo real (operação, não código)
- [ ] 🧑‍💼 Subir **fotos** + **tour 360°** de cada quarto
- [ ] 🧑‍💼 Marcar **qualidades** (vista lago, varanda, pet, ar, tipo de cama)
- [ ] 🧑‍💼 Escolher os **9 destaques** da home
- [ ] 🧑‍💼 Confirmar **preços por temporada** (cadastrar as datas — faixas já existem)
- [ ] 🧑‍💼 Criar **usuários da equipe** + acessos (Equipe & Acessos)

---

## 4. 🧩 Funcionalidades da Fase 2 (evolução pós-abertura — não bloqueiam)
- [ ] 💻 **CRM do Hóspede** — NPS real + relacionamento pós-estadia (hoje esqueleto)
- [ ] 💻 **Canais/OTAs** — sincronizar Booking/Airbnb (sem integração de canal hoje)

### Telefonia/voz no CRM — arquitetura (definida)
> **Duas telefonias:** 🏨 **Pousada (Itá)** = central **Intelbras UNNITI 1000 IP** (recepção,
> hóspedes, ramais). 💼 **Vendas (Concórdia, equipe remota)** = **nuvem**: **Vupt** (operadora,
> R$ 59,90/mês já paga) + **Asterisk** (PBX open-source numa VM, **custo zero de licença**) +
> **SIP.js** (softphone no navegador). Vendas **não** usa a UnniTI (equipe em Concórdia, não
> em Itá) e **não** usa Twilio (celular BR caro, deixaria a Vupt sem uso). Plano executável:
> **`docs/Implementar_Telefonia_Vendas.md`**.
>
> *Achados UnniTI (manual, 14/09/2026): **WebRTC** não nativo (só SIP 2.0/RTP → precisaria SBC);
> **CTI** via **CSTA sobre ICTI** (TCP :7000, auth AARQ/AARE); **gravação** por **ICR (FTP)** ou
> **UCR (Micro-SD)**, não em SMB/NFS.*

- [ ] 🧑‍💼 **Pousada — Central UNNITI:** configurar trunk Vupt, ramais (TIP 125 + V5502+), URA,
      gravação (ICR/FTP ou UCR), anti-fraude
- [ ] 🧑‍💼 **Vendas — Vupt (Fase 0):** confirmar **canais simultâneos** (≥ 3) + franquia de
      minutos + dados do **tronco SIP (BYOC)** p/ registrar o 3CX
- [ ] 🧑‍💼💻 **Vendas — Asterisk na nuvem:** VM (Ubuntu) + TLS/WSS + coturn + tronco Vupt +
      ramais WebRTC + gravação (MixMonitor) *(⚠️ tronco próprio Vupt; VM na nuvem, não no NAS de Itá)*
- [ ] 💻 **CRM (`apps/telefonia`)** — gateway plugável (`simulado`/`asterisk`); **SIP.js** no
      navegador (softphone) + **ARI/AMI** (eventos) → botão "Ligar" no lead → gravação →
      transcrição (Whisper) → IA (Claude) → BI

---

## 5. 🔧 Fast-follows pequenos (não bloqueiam)
- [ ] 💻 Painel de campanha do WhatsApp na UI (hoje por comando/serviço)
- [ ] 💻 Rastrear `delivered`/`read` do WhatsApp como estados próprios
- [ ] 💻 Conciliação do dinheiro online sem caixa (quando o gateway Pix/link for ativado)

---

## 🎯 Caminho crítico para inaugurar (o mínimo)
1. **WhatsApp** ligado (seção 1) + **maquininha Safrapay** (seção 1) → captar e cobrar.
2. **Fiscal**: IE + A1 + provider (o mais burocrático — iniciar já).
3. **Validar** módulos (seção 2) + **subir dados reais** (seção 3).

> O resto (Canais/OTAs, telefonia, CRM do Hóspede) entra **depois da abertura**.

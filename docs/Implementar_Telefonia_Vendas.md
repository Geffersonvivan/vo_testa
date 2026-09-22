# Implementar — Telefonia de Vendas (nuvem, custo zero de licença) + BI por IA

> Plano executável da **voz de vendas** no CRM. Refina o Anexo B de
> `docs/Marketing/CRM_WhatsApp.md` para a realidade confirmada: **equipe de vendas
> remota** (escritório em **Concórdia**), central da pousada em **Itá**.
> **Motor escolhido: Asterisk (open-source) controlado por Python (ARI)** — zero licença.
> Atualizado em 14/09/2026.

## 1. A decisão (por quê nuvem + Asterisk)

Existem **duas telefonias diferentes**, cada uma com a ferramenta certa:

| | 🏨 Pousada (Itá) | 💼 Vendas (Concórdia, remoto) |
|---|---|---|
| Ferramenta | **UnniTI 1000 IP** (central física) | **nuvem**: Asterisk + Vupt |
| Papel | recepção, hóspedes, ramais internos | discar do CRM, gravar, IA |

- **Vendas não usa a UnniTI:** a equipe está em Concórdia, não em Itá. Softphone em
  **nuvem** liga de qualquer lugar (Concórdia, casa, viagem).
- **Vendas não usa Twilio:** cobraria celular BR caro e deixaria a **Vupt (já paga,
  R$ 59,90/mês)** sem uso.
- **PBX = Asterisk, não 3CX:** mesma função, **sem custo de licença**. Não existe
  biblioteca Python que *substitua* a central (a parte de áudio/RTP/WebRTC é de um media
  server em C); o **Python (nosso `apps/telefonia`) controla** o Asterisk via **ARI**.

## 2. Arquitetura

```
Vendedor (Concórdia)         VM na nuvem                       Vupt (operadora)   Lead
 navegador (SIP.js)  ──WebRTC/WSS──►  Asterisk  ──tronco SIP (BYOC)──►  PSTN  ──►  ☎
   botão "Ligar"                       │  MixMonitor grava (.wav)
        ▲                              │ ARI (websocket)
        │ eventos/estado               ▼
   [CRM Django/Railway] ◄──ARI/AMI── apps/telefonia
        │                              │
        └─ registra no funil     [gravação] ─► Whisper (texto) ─► Claude (IA) ─► funil/BI
```

## 3. Papel de cada agente

| Agente | O que é | Papel | Custo |
|---|---|---|---|
| **Vupt** | operadora / tronco SIP | o **número** + **minutos** + saída p/ a rede | **R$ 59,90/mês** (já pago) + canais |
| **Asterisk** (VM nuvem) | central open-source | **gateway WebRTC↔SIP**, tronco Vupt, **gravação** (MixMonitor) | **R$ 0 de licença** + VM ~R$ 30–80/mês |
| **SIP.js** (no CRM) | softphone no navegador | telefone do vendedor (áudio WebRTC) | R$ 0 (lib JS) |
| **`apps/telefonia`** + **ARI** | nosso módulo Python | botão "Ligar", eventos, puxar gravação, funil | nosso código |
| **Whisper** | STT | áudio → texto (pt-BR) | US$ 0,006/min (ou **R$ 0** local no NAS) |
| **Claude** | IA (já usada) | resumo, objeções, sentimento, próximos passos | centavos/ligação |

## 4. Custos e assinaturas (3 vendedores, ~3.000 min/mês)

| Item | R$/mês |
|---|---|
| **VM (Asterisk)** — 2 vCPU / 2–4 GB, IP público (Hetzner/DO/Contabo) | 30–80 |
| **Licença PBX** | **0** (Asterisk é livre) |
| **Whisper** (3.000 min) — ou **R$ 0** rodando local no NAS | 0–100 |
| **Claude** (análise) | ~30 |
| **Total infra** (fora a Vupt já paga) | **≈ R$ 60–210/mês** |

⚠️ **Minutos da Vupt** não estão aí: se a franquia do plano cobrir os ~3.000 min → R$ 0
extra; se estourar, entram avulsos (~R$ 0,10–0,15/celular). Por isso a **Fase 0**.

## 5. O que é preciso — e **como obter** cada um

> Fora a Vupt (já paga), **quase tudo é grátis ou você já tem**. O único custo novo é a VM.
> Provedor escolhido: **Magalu Cloud** (100% brasileiro, paga em R$, datacenter em São
> Paulo). Setup pronto no **Apêndice A**.

| Peça | Onde obter | Como | Custo |
|---|---|---|---|
| **VM na nuvem** | **Magalu Cloud** (SP, brasileiro) — voz não picota | Console → Criar Instância (Ubuntu, SP) | **~R$ 35–70/mês** |
| **Subdomínio** | Você **já tem** `pousadavotesta.com.br` | Painel DNS → **registro A** `pbx` → IP da VM | **R$ 0** |
| **TLS/WSS** | **Let's Encrypt** | `certbot` na VM (renova sozinho) | **R$ 0** |
| **Asterisk + coturn** | Software livre | `apt install asterisk coturn` na VM | **R$ 0** |
| **Tronco Vupt (BYOC)** | **Vupt** (operadora atual) | Abrir chamado: pedir host/usuário/senha/porta/codecs + nº de canais | dentro do plano |
| **Portas (firewall)** | Configura-se | Security List da nuvem **+** firewall do SO | **R$ 0** |
| **Libs Python + SIP.js** | Repositórios públicos | `pip install panoramisk ari` + SIP.js via npm/CDN | **R$ 0** |

⚠️ **Datacenter em São Paulo** (não Europa/EUA): latência baixa até Concórdia e até a Vupt.

## 5.1 Pré-requisitos (checklist)

- [ ] **1 VM na nuvem** (Ubuntu 22.04+), ~2 vCPU / 2–4 GB / **IP público fixo**.
      **Não** hospedar no NAS de Itá (jogaria o áudio de volta para Itá).
- [ ] **1 subdomínio** apontando p/ a VM (ex.: `pbx.pousadavotesta.com.br`).
- [ ] **Certificado TLS** (Let's Encrypt) — WebRTC no navegador exige **WSS** (seguro).
- [ ] **Asterisk 20 LTS** (ou 18/22) + **coturn** (TURN/STUN, mesma VM).
- [ ] **Dados do tronco Vupt (BYOC)** — host, usuário, senha, portas, codecs (Fase 0).
- [ ] **Portas liberadas** na VM: `8089/tcp` (WSS), `5060–5061` (SIP), `10000–20000/udp`
      (RTP), `3478` + faixa TURN (coturn).
- [ ] **Python** no CRM: libs `panoramisk` (AMI async, casa com Django) e/ou `ari`
      (asterisk-ari); **SIP.js** (JS) no front do discador.

## 6. Passo a passo de implementação

### Fase 0 — Confirmar a Vupt (🧑‍💼) — *destrava tudo*
- [ ] **Canais simultâneos** (≥ 3 p/ 3 vendedores) + **franquia de minutos** (celular/fixo).
- [ ] Pedir os **dados do tronco SIP (BYOC)** e confirmar que aceita **registrar um PBX
      externo** (Asterisk). Se faltar canal, pedir ampliação (barato).

### Fase 1 — VM + Asterisk base (💻 infra) — "discar + gravar"
- [ ] Provisionar a VM (Ubuntu), aplicar firewall e abrir as portas da seção 5.
- [ ] Instalar **Asterisk** (`apt install asterisk` ou compilar) + **coturn**.
- [ ] **TLS:** emitir cert Let's Encrypt do subdomínio; habilitar **WSS** em `http.conf`
      (`tlsenable=yes`, porta 8089).
- [ ] **`pjsip.conf`:**
      - **Tronco Vupt** — `endpoint`/`aor`/`auth`/`registration` (registro de saída na Vupt).
      - **Ramais WebRTC** (1 por vendedor) — `transport=wss`, `webrtc=yes` (liga ICE +
        DTLS-SRTP), `context=vendas-saida`.
- [ ] **`extensions.conf`** (dialplan):
      - Contexto **saída** → `Dial(PJSIP/${EXTEN}@vupt)` com **BINA = número da pousada**.
      - **`MixMonitor()`** no início de cada chamada → grava `.wav` (aviso LGPD antes).
      - Contexto **entrada** (se receber ligação) → toca os ramais.
- [ ] **coturn** para o áudio atravessar NAT.
- [ ] **Teste:** registrar um ramal WebRTC (SIP.js demo ou Zoiper WebRTC) e ligar para um
      celular pela Vupt; conferir a gravação gerada.

### Fase 2 — Softphone no CRM (💻 front) — telefone no navegador
- [ ] Embutir **SIP.js** num widget de discador do CRM: registra o ramal WebRTC do vendedor
      (WSS), faz/atende/encerra, mostra estado (chamando/atendida/duração).
- [ ] Áudio flui **direto** navegador ↔ Asterisk (WebRTC). Microfone/headset do PC.
- [ ] Botão **"Ligar"** no lead → manda o SIP.js discar o número do lead.

### Fase 3 — `apps/telefonia` + ARI/AMI (💻 backend) — eventos + registro
- [ ] Habilitar **ARI** no Asterisk (`ari.conf` usuário/senha, `http.conf` enable).
- [ ] Novo app **`apps/telefonia`** (contratável), **gateway plugável** `TELEFONIA_GATEWAY`:
      `simulado` (dev) / `asterisk` (ARI/AMI). Services públicos: `iniciar_ligacao`,
      `registrar_gravacao`, `transcrever`, `analisar` — best-effort, idempotentes,
      **append-only**.
- [ ] Um **worker Python** (`panoramisk`/`ari`) assina os eventos do Asterisk
      (tocando/atendida/desligou + número + duração) → cada ligação vira
      **`AtividadeComercial`** no funil + **auditoria**.
- [ ] Ao encerrar, o worker sabe o **arquivo da gravação** (MixMonitor) → registra o link no
      lead.

### Fase 4 — Transcrição + IA + BI (💻)
- [ ] Enviar a gravação ao **Whisper** → transcript no lead (append-only). *(Provider
      plugável: OpenAI / Groq / **local no NAS de graça**.)*
- [ ] **Claude** lê o transcript → **estruturado**: resumo, objeções, o que funcionou,
      próximos passos, aderência ao script, nota → ficha do lead.
- [ ] **BI:** agregação (objeções, motivos de perda, sentimento por vendedor, conversão por
      abordagem) nos gráficos atuais (Chart.js); se crescer, Metabase.

### LGPD (transversal)
- [ ] **Aviso de gravação** no início ("Esta ligação será gravada para qualidade…") — áudio
      automático no dialplan ou script do vendedor; CRM registra o consentimento.
- [ ] Gravações com **acesso restrito** (gerência), **retenção 12 meses**, acesso/exclusão a
      pedido. Nada de PII em log.

## 7. Pendências a confirmar
- **Vupt:** canais + franquia + dados do tronco BYOC (Fase 0).
- **Onde guardar a gravação:** na VM, ou copiar para o **NAS** (`Gravacoes/`) casando com a
  retenção do `docs/Estrutura_NAS.md`.
- **STT:** Whisper OpenAI × Groq × **local no NAS** (custo × latência × privacidade).
- **Manutenção:** Asterisk é livre, mas **você mantém a VM** (updates, TLS, backup do
  `pjsip.conf`/`extensions.conf`). É o preço do "custo zero de licença".

## 8. Bibliotecas e ferramentas
- **Asterisk** (PBX) · **coturn** (TURN/STUN) · **Let's Encrypt** (TLS).
- **Python:** `panoramisk` (AMI async) · `ari`/`asterisk-ari` (ARI) — controlam ligar,
  eventos e gravação.
- **Front:** **SIP.js** (ou JsSIP) — softphone WebRTC no navegador.
- **IA:** Whisper (STT) · Claude (análise, já em uso).

## Apêndice A — Setup da VM na nuvem (Magalu Cloud) — passo a passo executável

> Runbook do zero: conta → VM → firewall → Asterisk → TLS → coturn → configs. Substitua os
> **PLACEHOLDERS** (MAIÚSCULAS) pelos valores reais. Faça na ordem.

### A.0 — Conta Magalu Cloud
1. Criar conta em **magalu.cloud** (dá p/ usar login Magalu/Magazine Luiza) → confirmar
   e-mail.
2. Adicionar forma de pagamento — **cobrança por hora**, em R$ (VM ~R$ 35–70/mês).

### A.1 — Criar a instância (VM)
1. **Antes:** gerar o par de chaves SSH no seu Mac: `ssh-keygen -t ed25519` (guarda a
   privada; sobe a **.pub**).
2. Console → **Virtual Machines → + Criar Instância**.
3. **Região:** **São Paulo (`br-se1`)**.
4. **Imagem:** **Ubuntu 22.04 LTS** (ou 24.04).
5. **Tipo:** ~**2 vCPU / 4 GB** (Asterisk é leve; 2 vCPU dá folga p/ transcodificar áudio).
6. **Chave SSH:** subir sua **chave pública** (a Magalu só acessa por chave — sem senha
   padrão).
7. **IP público:** habilitar/atribuir.
8. Criar → anotar o **IP público**. **Usuário SSH padrão do Ubuntu = `ubuntu`.**

### A.2 — Grupo de Segurança (firewall da Magalu)
A Magalu **bloqueia todo o tráfego por padrão**. Crie um **Grupo de Segurança** e associe à
VM, com estas **regras de entrada (ingress)** (Source `0.0.0.0/0`, salvo onde indicado):

| Porta | Protoc. | Uso |
|---|---|---|
| 22 | TCP | SSH — *ideal: Source = seu IP* |
| 80, 443 | TCP | certbot / futuro |
| 8088, 8089 | TCP | ARI (8088) e **WSS** (8089) |
| 5060 | UDP e TCP | SIP (tronco Vupt) — *ideal: Source = IP da Vupt* |
| 10000–20000 | UDP | **RTP** (áudio) |
| 3478 | UDP e TCP | STUN/TURN (coturn) |
| 49152–65535 | UDP | faixa de mídia do TURN |

> **Saída (egress):** liberar **TCP 1024–65535** para o retorno das conexões (padrão da
> Magalu). Docs: <https://docs.magalu.cloud/docs/network/how-to/create-security-groups/>

### A.3 — DNS do subdomínio
No painel DNS de `pousadavotesta.com.br` (Registro.br/Cloudflare): **registro A**
`pbx` → **IP público da VM**. Testar: `ping pbx.pousadavotesta.com.br`.

### A.4 — Conectar via SSH
Na Magalu o firewall é o **Grupo de Segurança** (A.2) — **não** há o bloqueio de iptables do
SO que a Oracle tinha. Conecte e atualize:
```bash
ssh ubuntu@IP_PUBLICO
sudo apt update && sudo apt -y upgrade
# (opcional, reforço) ufw liberando as mesmas portas do Grupo de Segurança
```

### A.5 — Instalar Asterisk + coturn + certbot
```bash
sudo apt -y install asterisk coturn certbot
sudo systemctl enable asterisk coturn
```

### A.6 — TLS (Let's Encrypt)
```bash
sudo systemctl stop asterisk                      # libera a porta 80 p/ validação
sudo certbot certonly --standalone -d pbx.pousadavotesta.com.br
# certificados em /etc/letsencrypt/live/pbx.pousadavotesta.com.br/{fullchain,privkey}.pem
sudo usermod -aG ssl-cert asterisk                # Asterisk pode ler os certs
```

### A.7 — coturn (`/etc/turnserver.conf`)
```ini
listening-port=3478
fingerprint
lt-cred-mech
realm=pbx.pousadavotesta.com.br
user=turnuser:TURN_SENHA
external-ip=IP_PUBLICO
min-port=49152
max-port=65535
```
```bash
sudo sed -i 's/#TURNSERVER_ENABLED=1/TURNSERVER_ENABLED=1/' /etc/default/coturn
sudo systemctl restart coturn
```

### A.8 — Configurar o Asterisk
**`/etc/asterisk/http.conf`** (HTTP p/ ARI + HTTPS/WSS):
```ini
[general]
enabled=yes
bindaddr=0.0.0.0
bindport=8088
tlsenable=yes
tlsbindaddr=0.0.0.0:8089
tlscertfile=/etc/letsencrypt/live/pbx.pousadavotesta.com.br/fullchain.pem
tlsprivatekey=/etc/letsencrypt/live/pbx.pousadavotesta.com.br/privkey.pem
```
**`/etc/asterisk/ari.conf`** (o CRM conecta aqui):
```ini
[general]
enabled=yes
[crm]
type=user
password=ARI_SENHA_FORTE
```
**`/etc/asterisk/pjsip.conf`** (transporte WSS + tronco Vupt + 1 ramal por vendedor):
```ini
; --- transportes ---
[transport-wss]
type=transport
protocol=wss
bind=0.0.0.0
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0

; --- TRONCO VUPT (dados da Fase 0) ---
[vupt-reg]
type=registration
outbound_auth=vupt-auth
server_uri=sip:VUPT_HOST
client_uri=sip:VUPT_USUARIO@VUPT_HOST
[vupt-auth]
type=auth
auth_type=userpass
username=VUPT_USUARIO
password=VUPT_SENHA
[vupt-aor]
type=aor
contact=sip:VUPT_HOST
[vupt]
type=endpoint
transport=transport-udp
context=from-vupt
disallow=all
allow=alaw,ulaw
outbound_auth=vupt-auth
aors=vupt-aor
from_user=NUMERO_DA_POUSADA        ; BINA
[vupt-identify]
type=identify
endpoint=vupt
match=VUPT_HOST

; --- RAMAL DO VENDEDOR (repetir 6001, 6002, ...) ---
[6001]
type=endpoint
transport=transport-wss
context=vendas-saida
disallow=all
allow=ulaw,opus
webrtc=yes                          ; liga ICE + DTLS-SRTP automaticamente
auth=6001-auth
aors=6001
[6001-auth]
type=auth
auth_type=userpass
username=6001
password=RAMAL_SENHA
[6001]
type=aor
max_contacts=1
```
**`/etc/asterisk/extensions.conf`** (discar pela Vupt + gravar):
```ini
[vendas-saida]
exten => _X.,1,NoOp(Saida vendas -> ${EXTEN})
 same => n,MixMonitor(${UNIQUEID}.wav)          ; grava (avisar LGPD antes)
 same => n,Dial(PJSIP/${EXTEN}@vupt,60)
 same => n,Hangup()

[from-vupt]
exten => _X.,1,NoOp(Entrada Vupt)
 same => n,Dial(PJSIP/6001,30)
 same => n,Hangup()
```
Aplicar:
```bash
sudo systemctl restart asterisk
sudo asterisk -rx "pjsip show registrations"     # deve mostrar Vupt "Registered"
```

### A.9 — Softphone no navegador (SIP.js) — teste
No front do CRM (ou num teste isolado), configurar o **SIP.js**:
- `server: "wss://pbx.pousadavotesta.com.br:8089/ws"`
- `uri: "sip:6001@pbx.pousadavotesta.com.br"`, `authorizationUsername: "6001"`,
  `authorizationPassword: RAMAL_SENHA`
- `iceServers: [{ urls: "turn:pbx.pousadavotesta.com.br:3478", username:"turnuser",
  credential:"TURN_SENHA" }]`

Teste: registrar o 6001 → discar um celular → falar pelo headset → conferir o `.wav`
gravado em `/var/spool/asterisk/monitor/`. **Fecha a Fase 1.**

### A.10 — Ligar ao CRM (Fase 3, resumo)
- `pip install panoramisk ari` no CRM; conectar no **ARI** (`https://pbx…:8088`, user `crm`)
  para receber eventos e casar cada ligação ao lead (`AtividadeComercial`).
- Copiar/expor a gravação → Whisper → Claude (Fases 3–4).

> **Dica de robustez:** depois de tudo funcionando, restrinja a Source das portas 5060/RTP à
> **faixa de IP da Vupt** e ao IP do escritório de Concórdia; e agende renovação do certbot
> (`certbot renew` no cron) recarregando o Asterisk.

## Apêndice B — Transcrição local no NAS (Whisper grátis, custo/min zero)

> **Escolha:** STT roda **no NAS (Synology DS925+, 32 GB RAM)**, sem custo por minuto e
> **sem o áudio do cliente sair da nossa infra** (LGPD). Alternativas pagas (Groq/OpenAI)
> ficam como *fallback* plugável. Bate com `docs/Estrutura_NAS.md` §6 (serviços no
> Container Manager, Volume 2 / SSD).

### B.1 — Realidade do hardware (decide tudo)
- DS925+ = **CPU AMD (4 núcleos), SEM GPU/CUDA** → Whisper roda **em CPU**.
- Logo: **processamento em lote, não tempo real.** A ligação termina → o `.wav` entra
  numa fila → transcreve em alguns minutos. Para BI de vendas (resumo, objeções,
  sentimento) isso basta — ninguém precisa do texto no segundo seguinte.
- **32 GB de RAM** (instalados) tiram a memória do caminho: dá pra usar o modelo
  **`medium`** (recomendado p/ pt-BR) e até **`large-v3`**; o limite passa a ser só a
  velocidade da CPU (aceitável em lote).

### B.2 — Ferramenta: `faster-whisper` (não o Whisper "de fábrica")
- **`faster-whisper`** (backend CTranslate2, quantização **int8**) — muito mais rápido em
  CPU que o `openai-whisper`. Roda num **container Docker** (Container Manager, Volume 2 /
  SSD) expondo um endpoint HTTP local. Alternativa: `whisper.cpp` (também CPU-friendly).
- **Modelo:** `medium` int8 (qualidade) — ou `small` int8 se quiser mais velocidade.
- **Idioma:** fixar `language=pt`.

### B.3 — O problema de rede (3 redes) e a solução (só saída)
Três máquinas, três redes:
```
Asterisk (Magalu Cloud, IP público)  ──.wav──►  NAS (192.168.1.8, atrás de NAT)
                                                   │ faster-whisper (local, lote)
CRM (Railway, nuvem)  ◄────────── transcript (API) ─┘
```
O CRM roda na **Railway (nuvem)** e o **NAS está na LAN atrás de NAT** — a Railway **não
alcança** o NAS, e **não se expõe** o NAS à internet (`Estrutura_NAS.md` §5). Solução:
um **worker local no próprio NAS** que faz tudo por **conexões de saída**:

1. **Puxa** os `.wav` novos do Asterisk (NAS → VM, `rsync`/`scp` sobre SSH) → `Gravacoes/`.
2. **Transcreve** local com `faster-whisper` (mesmo container).
3. **Envia o texto** ao CRM via **API autenticada** na Railway (POST de saída).
4. CRM chama o **Claude** p/ resumo/objeções/BI e grava no lead (append-only).

Tudo **outbound** do NAS: sem VPN, sem porta aberta, sem QuickConnect. O NAS fala com a VM
e com a Railway; ninguém fala com o NAS.

### B.4 — Provider STT plugável no `apps/telefonia`
Prever `STT_PROVIDER` no settings: **`local`** (NAS, default) / `groq` / `openai`. Service
`transcrever(caminho_ou_url) -> texto` (best-effort, idempotente). O worker do NAS chama o
provider `local`; se um dia faltar CPU ou precisar de tempo real, troca-se por `groq` sem
mexer no resto.

### B.5 — Custo e trade-off
| Opção | Custo | Quando |
|---|---|---|
| **NAS local (`faster-whisper` int8, `medium`)** | **R$ 0/min** (já temos NAS+RAM) | **Padrão** — volume alto, privacidade LGPD |
| Groq (Whisper) | ~centavos/min | Resultado na hora sem worker |
| OpenAI | US$ 0,006/min | *fallback* |

### B.6 — LGPD
Áudio do cliente **não sai da infra** (fica no NAS). Gravações em `Gravacoes/` = acesso só
gestão, retenção 12 meses, criptografia/snapshots do NAS (`Estrutura_NAS.md` §4).

## Links
- Asterisk WebRTC (chan_pjsip): <https://docs.asterisk.org> · ARI:
  <https://docs.asterisk.org/Asterisk_REST_Interface/>
- SIP.js: <https://sipjs.com> · coturn: <https://github.com/coturn/coturn>
- Whisper (preço): <https://tokenmix.ai/blog/whisper-api-pricing>
- Base conceitual: `docs/Marketing/CRM_WhatsApp.md` Anexo B.

> **UnniTI para a casa; para vendas, Asterisk + Vupt (custo zero de licença).** A UnniTI
> segue como telefonia da pousada (Itá); vendas roda 100% em nuvem, sem depender de Itá.

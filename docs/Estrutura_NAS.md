# Estrutura do NAS — Synology DS925+ (Vo_Testa)

> Guia de configuração do NAS da Pousada Vô Testa: papel do equipamento, discos,
> pastas, permissões e proteção. Atualizado em 15/09/2026 · IP local: **192.168.1.8**.
> **Hardware:** CPU AMD 4 núcleos (**sem GPU/CUDA**) · **32 GB RAM** (instalados) —
> folga p/ rodar a transcrição local (Whisper em CPU, em lote — ver §6).

## 0. Papel do NAS (o que ele é e o que NÃO é)
- **É:** servidor de arquivos da pousada (MKT, Financeiro, Gestão…), **guarda das
  gravações** de ligação, **backup** do CRM e **mídia** do site, e host de **serviços**
  (Docker/Container Manager).
- **NÃO é** a central telefônica — a telefonia roda na **Intelbras UNNITI 1000 IP**
  (trunk da **Vupt**). O NAS só **armazena** as gravações que a central gerar.

## 1. Discos e pools (manter os dois em RAID1)
| Pool / Volume | Discos | Capacidade | Uso |
|---|---|---|---|
| **Pool 1 / Volume 1** | 2× HDD Seagate 8 TB — **RAID1** | 7.3 TB | **Arquivos de trabalho + gravações + backup + mídia** |
| **Pool 2 / Volume 2** | 2× SSD SanDisk 2 TB — **RAID1** | 1.8 TB | **Docker/Container Manager, banco e serviços** |

- **Não desmontar** o RAID1 dos SSDs — ganharia espaço, mas perderia a redundância
  (e são SSDs de entrada, durabilidade menor). 1.8 TB sobra para os serviços; o volume
  grande fica no HDD.
- Acompanhar a **"Vida útil estimada"** dos SSDs de tempos em tempos.

## 2. Estrutura de pastas (Pastas Compartilhadas no Volume 1 — HDD)
```
MKT/               → material de marketing, campanhas, criativos
Financeiro/        → planilhas, notas, extratos  (SENSÍVEL)
Gestao/            → relatórios, planejamento, atas
Recepcao/          → documentos de recepção/reservas
RH/                → pessoal, folha, admissões    (SENSÍVEL)
Contratos_Juridico/→ contratos, jurídico          (SENSÍVEL)
Gravacoes/         → gravações de ligação da central  (LGPD)
Backups_CRM/       → backups exportados do CRM
Midia_Site/        → fotos e tour 360° dos quartos
Publico/           → arquivos gerais compartilhados
```
> Serviços (Docker/banco) ficam no **Volume 2 (SSD)** — não misturar com arquivo de escritório.

## 3. Grupos e permissões (menor privilégio — o ponto crítico)
Criar **grupos** no DSM (Painel de Controle → Usuário e Grupo) e dar permissão **por
pasta**. Nada de "todo mundo vê tudo".

| Grupo | Pastas com acesso |
|---|---|
| `marketing` | MKT, Midia_Site |
| `financeiro` | **Financeiro** (só eles + gestão) |
| `rh` | **RH** (só eles + gestão) |
| `recepcao` | Recepcao |
| `gestao` | Gestao, Contratos_Juridico, Gravacoes + **leitura** ampla |
| `admin` | tudo (mín. de pessoas) |

- **Financeiro, RH, Contratos e Gravacoes = acesso restrito.** Gravações são **dado
  LGPD** — só gestão/compliance.
- Preferir **leitura/gravação por grupo**; evitar permissão por usuário solto.
- **Publico** = leitura/gravação para todos os funcionários; **nunca** convidado/anônimo.

## 4. Proteção dos dados (obrigatório — há financeiro e contratos)
1. **Snapshots (Btrfs) — Snapshot Replication:** agendar snapshots das pastas (ex.: a
   cada hora nas sensíveis, diário nas demais). Recupera de **ransomware/exclusão
   acidental** voltando a versão anterior. Reter ~30 dias.
2. **Lixeira (Recycle Bin):** ativar em cada pasta compartilhada (esvaziar automático,
   ex.: 30 dias).
3. **Backup offsite — Hyper Backup → nuvem/outro local:** das pastas críticas
   (**Financeiro, RH, Contratos_Juridico, Gestao, Gravacoes, Backups_CRM**). **RAID não é
   backup** — isto cobre roubo/incêndio/falha do NAS. Agendar diário + testar restauração.
4. **Criptografia** das pastas **Financeiro, RH, Contratos_Juridico** ("Criptografar esta
   pasta compartilhada") — guardar a chave em local seguro (sem a chave, não abre).

## 5. Segurança do DSM
- Criar **usuário admin próprio** com senha forte e **desativar o "admin" padrão**.
- **2FA** em todas as contas com acesso amplo.
- **Painel de Controle → Segurança:** firewall ligado + **proteção de conta** (bloqueio
  por tentativas) + auto-block.
- **HTTPS** (porta 5001) ligado; evitar expor o DSM direto à internet — se precisar de
  acesso remoto, usar **QuickConnect/VPN**, nunca porta aberta.
- Manter **DSM e pacotes atualizados**.

## 6. Integração com o CRM e a central
- **Central UNNITI** grava as ligações → aponta para a pasta **`Gravacoes/`** (SMB/NFS).
- **CRM (`apps/telefonia`)** lê `Gravacoes/` → transcrição (Whisper) → IA (Claude) → BI.
- **Backups do CRM** exportados para `Backups_CRM/` (o banco de produção fica na nuvem
  Railway; aqui é cópia adicional).
- **Serviços auxiliares** (transcrição/IA local, se usados) rodam no **Container Manager**
  (Volume 2 / SSD).

## 7. Rede
- **Fixar o IP 192.168.1.8** (reserva de DHCP no roteador) — a central e o CRM precisam
  sempre achar o NAS no mesmo endereço.

## Checklist rápido de configuração
- [ ] Volumes: Pool 1 (HDD RAID1) reparado/saudável + Pool 2 (SSD RAID1) saudável
- [ ] Criar as pastas compartilhadas (seção 2) no Volume 1
- [ ] Criar grupos + aplicar permissões (seção 3)
- [ ] Ligar snapshots + lixeira (seção 4.1/4.2)
- [ ] Configurar Hyper Backup offsite das pastas críticas (seção 4.3)
- [ ] Criptografar Financeiro/RH/Contratos (seção 4.4)
- [ ] Segurança do DSM: admin próprio, 2FA, firewall, HTTPS (seção 5)
- [ ] Fixar IP no roteador (seção 7)

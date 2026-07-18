# Planejamento de E-mail — Pousada Vô Testa

**Data:** 16 de junho de 2026
**Domínio:** `pousadavotesta.com.br` (registrado)
**Objetivo:** criar os e-mails profissionais dos setores e habilitar o envio automático de
e-mails pelo site (confirmação de reserva etc.).

---

## 0. Dois problemas diferentes (não confundir)

| | O que é | Como se resolve |
|---|---|---|
| **A. Caixas dos setores** | Contas que pessoas acessam (ex.: `reservas@...`) | Provedor de e-mail + registros **MX/SPF/DKIM/DMARC** no DNS |
| **B. Envio pelo site** | O sistema mandar e-mail (confirmação de reserva, abandono) | **SMTP/serviço transacional** + **SPF/DKIM/DMARC** para não cair em spam |

Os dois usam o mesmo domínio e os mesmos conceitos de DNS, mas são configurações
distintas. Este documento cobre os dois.

---

## ✅ Decisões tomadas (jul/2026)

- **Provedor:** **Zoho Mail — plano Mail Lite** (5 GB/usuário, **R$ 5/usuário/mês** anual).
  O plano grátis foi descartado por **não ter SMTP** (necessário p/ o envio do site).
- **DNS:** gerenciado no **Registro.br** (Editar Zona DNS) — é onde entram MX/SPF/DKIM/DMARC.
- **Caixas reais (5 licenças ≈ R$ 25/mês):** `naoresponda@`, `reservas@`, `gerencia@`,
  `administrativo@`, `marketing@` (mkt tem pessoa dedicada). Aliases livres conforme
  necessidade (ex.: `contato@` → `reservas@`).
- **Envio do site:** SMTP do Zoho pela **`naoresponda@`** (senha de app).
- **Django (feito):** backend de e-mail por variável de ambiente — **console em dev**,
  **SMTP em produção** (basta definir `EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD`).
  E-mail de **confirmação de reserva** ligado ao `finalizar_reserva` do site
  (`apps/site/emails.py` + templates `site/emails/confirmacao.{txt,html}`), com teste.

**Falta só (do lado de vocês):** criar as caixas no Zoho, adicionar os registros no
Registro.br e gerar a **senha de app da `naoresponda@`** → preencher as variáveis de
ambiente em produção e o envio real liga.

---

## A. Caixas de e-mail dos setores

### A.1 Provedores — comparação

| Provedor | Custo aprox. | Prós | Contras |
|---|---|---|---|
| **Zoho Mail** ⭐ | **Grátis** até 5 contas (5 GB cada, 1 domínio); pago ~US$1/conta/mês | Mais barato; webmail + apps; ótimo p/ negócio pequeno | Marca menos "conhecida" que Google |
| **Google Workspace** | ~US$6–7/conta/mês | Gmail/Drive/Meet; padrão de mercado; ótima entrega | Custo por conta sobe rápido |
| **Microsoft 365** | ~US$6/conta/mês | Outlook/Office; bom se já usam Office | Custo por conta |
| **Hospedagem do registrador** | às vezes incluso no plano | "De graça" se já tem hospedagem | Recursos/entrega geralmente inferiores |

> **Recomendação:** **Zoho Mail** para começar — cobre todos os setores com custo baixo
> ou zero. Dá para migrar para Google Workspace depois, se quiser.

### A.2 Estrutura: caixas reais × aliases (apelidos)

Para ter "todos os setores" **sem pagar por cada endereço**, usa-se **aliases**:
poucas caixas reais e vários apelidos que caem nelas.

- **Opção 1 — Enxuta (recomendada p/ início):** 1–2 caixas reais + aliases.
  Ex.: caixa real `contato@`; `reservas@`, `financeiro@`, `recepcao@` como aliases que
  caem em `contato@` (ou redirecionam). **Custo mínimo.**
- **Opção 2 — Uma caixa por setor:** cada setor com login próprio.
  Mais organizado e escalável, **custo maior** (uma licença por caixa).

### A.3 Endereços sugeridos para a pousada

| Endereço | Uso |
|---|---|
| `contato@` | Geral / fallback |
| `reservas@` | Reservas e dúvidas de hospedagem |
| `financeiro@` | Pagamentos, notas, cobranças |
| `recepcao@` | Operação / check-in |
| `gerencia@` | Gestão |
| `marketing@` | Parcerias, redes sociais |
| `naoresponda@` (no-reply) | **Envios automáticos do site** (ver parte B) |

### A.4 DNS necessário (onde o domínio é gerenciado)

Independentemente do provedor, é preciso adicionar no painel de DNS do domínio:

- **MX** — para onde os e-mails do domínio são entregues (apontam para o provedor).
- **SPF** (TXT) — autoriza quem pode enviar em nome do domínio.
- **DKIM** (TXT) — assinatura criptográfica das mensagens (anti-falsificação).
- **DMARC** (TXT) — política do que fazer com e-mails que falham SPF/DKIM.

O provedor (ex.: Zoho) fornece os valores exatos no assistente de configuração.

> **Pendência:** confirmar **onde o DNS é gerenciado** (Registro.br, ou painel de
> hospedagem como Locaweb/Hostinger/Cloudflare). É lá que os registros entram.

---

## B. Envio de e-mails pelo site (transacional)

O site precisa mandar a **confirmação de reserva** (e futuramente o e-mail de abandono de
carrinho — FASE 5). Isso **não** usa "uma caixa de pessoa"; usa um remetente como
`naoresponda@pousadavotesta.com.br` via SMTP/serviço transacional.

### B.1 Opções de envio

| Opção | Custo | Observações |
|---|---|---|
| **SMTP do próprio provedor** (Zoho/Google) | incluso | Simples; limites diários de envio menores |
| **Resend** | grátis até ~3.000/mês | Moderno, fácil de integrar, bom para devs |
| **Amazon SES** | ~US$0,10/mil e-mails | Muito barato em escala; setup um pouco mais técnico |

> **Recomendação:** começar com o **SMTP do Zoho** (já vem com as caixas) usando
> `naoresponda@`. Se o volume crescer, migrar para Resend/SES.

### B.2 Integração no Django (eu implemento)

Depois que o SMTP existir, configuro no `settings.py` (por variáveis de ambiente,
sem expor senha):

```
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = <smtp do provedor>           # ex.: smtp.zoho.com
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = naoresponda@pousadavotesta.com.br
EMAIL_HOST_PASSWORD = <env: EMAIL_PASSWORD>
DEFAULT_FROM_EMAIL = 'Pousada Vô Testa <naoresponda@pousadavotesta.com.br>'
```

E ligo o disparo na confirmação da reserva (hoje a `finalizar_reserva` só cria a reserva).
Itens relacionados no roadmap: **e-mail de confirmação** e **e-mail de abandono** (FASE 5),
idealmente assíncronos via **Celery + Redis**.

### B.3 Entregabilidade (não cair em spam)

- SPF, DKIM e **DMARC** bem configurados (mesmos registros da parte A).
- Remetente no próprio domínio (`@pousadavotesta.com.br`), nunca Gmail genérico.
- Conteúdo com link de descadastro quando for marketing.

---

## C. Decisões pendentes (para avaliarmos)

1. **Provedor das caixas:** Zoho (recomendado) / Google Workspace / Microsoft 365 / hospedagem.
2. **Estrutura:** 1–2 caixas + aliases (recomendado) **ou** uma caixa por setor.
3. **Lista final de setores/endereços** (a partir da sugestão em A.3).
4. **Onde está o DNS** do domínio (para adicionar os registros).
5. **Envio do site:** SMTP do provedor (recomendado p/ início) / Resend / SES.
6. **Quem opera** cada caixa (definir responsáveis por setor).

---

## D. Passos de implementação (ordem sugerida)

1. Escolher o provedor e criar a conta no domínio `pousadavotesta.com.br`.
2. Adicionar **MX/SPF/DKIM/DMARC** no DNS (valores fornecidos pelo provedor).
3. Criar a caixa principal + aliases dos setores (ou uma por setor).
4. Criar `naoresponda@` para o site e gerar uma senha de app/SMTP.
5. **(Eu)** configurar o Django (SMTP por env) e ligar o e-mail de confirmação de reserva.
6. Testar envio/recebimento e validar entregabilidade (SPF/DKIM/DMARC).
7. (FASE 5) E-mail de abandono de carrinho + envio assíncrono (Celery/Redis).

---

## E. Estimativa de custo (mensal)

| Cenário | Custo aprox. |
|---|---|
| **Zoho grátis** (até 5 contas) + SMTP Zoho | **R$ 0** |
| Zoho pago (~US$1/conta) p/ 5 setores | ~US$5 (~R$ 25–30) |
| Google Workspace, 3 contas | ~US$18–21 (~R$ 100–120) |
| Envio transacional (Resend/SES) | grátis no início; centavos por mil e-mails |

---

*Documento para avaliação. Nenhuma configuração foi aplicada ainda — aguarda as decisões da seção C.*

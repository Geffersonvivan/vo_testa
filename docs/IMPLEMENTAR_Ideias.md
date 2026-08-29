# Ideias a Implementar — Backlog priorizado

Ideias extraídas da análise da proposta **Foco Multimídia**, cruzadas com o estado atual
do CRM. Foco: **aquisição, conversão e distribuição** — a camada onde ainda temos espaço
(o núcleo do PMS já está em paridade).

📎 **PDF de referência:** [`docs/Foco_Tecnologia.pdf`](./Foco_Tecnologia.pdf)

**Legenda de esforço:** 🟢 baixo · 🟡 médio · 🔴 alto
**Prioridade:** ordenada por impacto ÷ esforço (topo = fazer primeiro).

---

## ✅ Já temos (paridade — não implementar)

PDV, mapa de reservas, reserva manual + link de pagamento, manutenção/bloqueio,
governança, disponibilidade/tarifário, orçamentos, 100% nuvem, site + motor de reservas,
pagamentos (Safrapay), portal do hóspede, trilha de auditoria.

> O slide "Plus PMS" da Foco = coisas que o nosso sistema já faz, várias com mais profundidade.

---

## 🎯 Fazer agora — gatilhos de conversão (baixo esforço, alto retorno)

Aumentam **reserva direta** e cortam comissão de OTA. Quase todos apoiam-se em coisas
que já existem no sistema.

- [ ] 🟢 **Selo de escassez** na vitrine — "Resta 1 unidade" / "Últimas 2".
      *Já sabemos disponibilidade em tempo real; é só exibir.*
- [ ] 🟢 **Comparador de preço direto** — "No nosso site R$ X · Booking R$ Y".
      *Bloco na página do tipo, reforça o "reserve direto e pague menos".*
- [ ] 🟢 **URL amigável + GA4/GTM** no site — melhor indexação e mensuração.
- [ ] 🟡 **Preço por forma de pagamento** — Pix com desconto vs. cartão.
      *Já temos Safrapay + formas de pagamento; falta expor na vitrine.*
- [ ] 🟡 **Recuperação de carrinho** — pré-reserva expirando dispara WhatsApp/e-mail
      com desconto. *Já temos expiração de pré-reserva; falta o gatilho de recuperação.*
- [ ] 🟡 **Gatilho cronológico** — countdown em pacotes/promoções por tempo limitado.

## 🎁 Fazer na sequência — pacotes e experiência

- [ ] 🟡 **Pacotes e Promoções** com destaque na home (ex.: pacote Pesca + Diária,
      Black Friday). *Conecta com o tarifário e a estrutura náutica (`docs/Tarifario.pdf`).*
- [ ] 🟡 **Pré check-in / check-in online (FNRH digital)** antes da chegada — estende o
      Portal do Hóspede. *FNRH já está como pendente em Reservas; equivale ao "Foco Pass".*

## 🚀 Fase 2 — maior esforço, já no roadmap

- [ ] 🔴 **Channel Manager** — inventário central → OTAs, com **markup de tarifa por
      canal** e antioverbooking central. *Item §8 (Canais/OTAs) da especificação.*
- [ ] 🔴 **Rate Shopper** — monitorar tarifa/ocupação de até 10 concorrentes (30 dias) e
      alertar quando estivermos mais caros. *Casaria com o tarifário — preço com dado da concorrência.*
- [ ] 🟡 **Google Hotel Ads / Free Booking Links / Hotel Center** — integração (gratuita)
      que alimenta o motor direto. Canal de aquisição.
- [ ] 🔴 **Fidelidade com cashback** — programa de relacionamento (CRM do Hóspede, Fase 2).
- [ ] 🟡 **B2B self-service** — portal de reserva online para agências/empresas.
      *Já temos os models `Agencia`/`Empresa`; falta a tela de reserva deles.*
- [ ] 🟡 **Chatbot + WhatsApp** para reservas (Foco usa Asksuite).
      *Há projeto WhatsApp em paralelo — integrar.*

---

## 🔎 SEO e presença digital (site dentro do CRM)

Kit de "ser achado no Google e converter reserva direta". Hoje o site **não tem nenhum
destes** — terreno virgem, ganho rápido. Como o CRM serve `/crm/`, o **robots.txt é
importante** para o Google não indexar o sistema interno.

### Implementável no código (rápido, alto valor)

- [x] 🟢 **robots.txt** — diz aos robôs o que rastrear; **bloqueia `/crm/`, admin e
      `/hospede/`** (só o site público entra) e aponta o sitemap. ✅ `apps/site/views.py:robots_txt`.
- [x] 🟢 **sitemap.xml** — lista as URLs para o Google indexar. ✅ `apps/site/sitemaps.py`
      (home + reservar; ampliar com tipos de quarto/day use depois).
- [x] 🟢 **meta description** por página — ✅ bloco `meta_description` no `site/base.html`
      (+ canonical e Open Graph); home já com descrição própria. Falta preencher tipos/day use/eventos.
- [x] 🟢 **llms.txt** — ✅ `apps/site/views.py:llms_txt` na raiz.
- [x] 🟡 **Google Analytics (GA4)** — ✅ tag no `site/base.html`, gated por
      `GA_MEASUREMENT_ID` (env). **Pendente:** criar a conta GA4 e **banner de consentimento (LGPD)**
      antes de ligar em produção.

### Contas externas (você cria, eu ajudo a plugar)

- [ ] 🟢 **Google Search Console** — painel de indexação/ranking; submeter o sitemap e
      corrigir páginas não achadas. Verifica o domínio (meta-tag no código).
- [ ] 🟢 **Google Meu Negócio** (Business Profile) — **maior ROI da lista**: ficha no
      Maps/Busca com fotos, avaliações e botão de reserva direto ao nosso motor, sem OTA.
- [ ] 🟡 **Conta GA4** — par da tag do código.

### Infra / cutover

- [x] 🟡 **Domínio personalizado** — ✅ `www.pousadavotesta.com.br` já no app unificado
      (Railway `Site_CRM_Pousada_Vo_Testa`, auto-deploy no push da main). Cutover feito.
- [~] 🟡 **Mídia em object storage (Cloudflare R2)** — **CÓDIGO FEITO, aguarda credenciais.**
      Hoje a mídia vive no filesystem efêmero do Railway → fotos subidas pelo admin em
      produção **somem no próximo deploy** (por isso as fotos curadas foram commitadas
      no git como gambiarra). Com R2 (S3-compatível, **sem taxa de egress**, 10GB grátis/mês),
      a mídia persiste e independe de git/deploy.
      **✅ Código:** `django-storages`+`boto3` no requirements; `STORAGES["default"]` vira R2
      **só quando as 5 env vars existem** (`R2_BUCKET`, `R2_ACCESS_KEY_ID`,
      `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_PUBLIC_DOMAIN`) — sem elas cai no
      filesystem (dev/fallback), nada quebra. Comando `manage.py migrar_media_r2` (idempotente)
      sobe as fotos atuais. `.env.example` documentado.
      **▶ Para ativar (você, ~10min):** criar bucket R2 → **ativar acesso público** (pega o
      domínio `pub-xxxx.r2.dev` ou custom) → gerar **API Token** (Access Key/Secret) → pôr as 5
      vars no Railway. **Eu:** rodo `railway ssh … migrar_media_r2`, valido as fotos, e então
      **removo `media/` do git** (volta ao gitignore). **Bônus:** casa com backup 3-2-1 (NAS QNAP
      puxa do R2 com `rclone`). Alternativa mais simples: **Railway Volume** (sem conta externa,
      mas preso ao Railway, sem CDN/backup offsite) — R2 é melhor.

### Atividade contínua (não é "arquivo")

- [x] 🟡 **Tailwind: CDN → build estático** — ✅ trocado o `cdn.tailwindcss.com` (que
      compilava no navegador + avisava "não use em produção") por CSS minificado de 30K
      (`apps/site/static/site/css/tailwind.css`). Fonte: `tailwind.config.js` + `tailwind.src.css`;
      regenerar com `npx tailwindcss@3 -i tailwind.src.css -o apps/site/static/site/css/tailwind.css --minify`
      após mudar classes. Console limpo, visual idêntico (verificado no Playwright). Lab (beta) segue no CDN.
- [ ] 🟡 **Performance test** — medir Core Web Vitals (PageSpeed/Lighthouse) e ajustar
      imagens/cache. Site rápido ranqueia e converte mais.
- [ ] 🟡 **SEO keywords** — usar termos de alta intenção local nos títulos/textos:
      "pousada lago de itá", "pesca esportiva itá sc", "day use piscina", "pousada com píer".

---

## 🤖 IA/LLM para convencer o hóspede a reservar (persuadir com verdade)

Uso de LLM (API da Claude) na jornada do site, na página do quarto e no pós-clique.
Início sugerido: **#2 (descrições geradas)** + **#1 (concierge)**.

> **Regra de ouro (Responsabilidade / CDC / LGPD):** persuadir ≠ enganar. Escassez,
> urgência e prova social só aparecem se forem **reais** e verificáveis (ver "Selo de
> escassez" acima — baseado em disponibilidade real). O LLM responde fatos **fundamentado
> nos dados do CRM** (disponibilidade, tarifa, políticas) via tool-use/RAG, não geração
> livre. Personalização exige base legal/consentimento. O LLM **não** fabrica selos tipo
> "Última vaga!" / "Fulano reservou há X".

- [ ] 🟡 **1. Concierge conversacional** (maior impacto) — chat na página do quarto que
      responde na hora ("aceita pet?", "vista pro lago?", "estacionamento?"), **fundamentado
      no CRM** (qualidades da UH, tarifa por temporada, disponibilidade, políticas) via
      RAG/tool-use. Tira objeções e leva ao "Reservar". *Modelo: Claude Haiku + streaming.
      Integra `reservas.services`.*
- [ ] 🟢 **2. Copy persuasivo gerado** (storytelling da marca) — LLM escreve descrição e
      títulos de cada quarto na voz "Vô Testa" (ofícios de outrora) a partir das
      características reais. **Gera uma vez e salva** (`site.VitrineQuarto.descricao`), custo
      mínimo. Resolve as descrições vazias/placeholder de hoje. *Modelo: Sonnet/Opus, batch.*
- [ ] 🟡 **3. Personalização por contexto** — adapta o discurso a sinais **não sensíveis**
      (datas/temporada, nº de hóspedes, origem, aparelho): "ideal para casais", "perfeito
      com crianças". *Cuidado LGPD.*
- [ ] 🟡 **4. Prova social verdadeira + resposta a objeções** — LLM **resume avaliações
      reais** (NPS/depoimentos) por quarto e responde dúvidas (cancelamento, café, pet).
      Só sobre dados reais. *Integra `apps/nps` + depoimentos.*
- [ ] 🟡 **5. Recuperação de pré-reserva (nudge com LLM)** — reforça o item "Recuperação de
      carrinho" acima: LLM escreve o lembrete pessoal ("seu Oficina do Relojoeiro está
      guardado por mais X min"). *Integra `reservas.Reserva.expira_em`, `pendentes_de_sinal`.*
- [ ] 🟡 **6. Assistente de decisão ("me ajuda a escolher")** — com 24 quartos há paralisia
      de escolha; o LLM faz 2–3 perguntas e recomenda o quarto certo. *Integra a vitrine
      (`_vitrines_publicadas`), qualidades e faixa de preço.*

**Stack:** API da Claude — Haiku (chat/volume), Sonnet/Opus (geração rica). Sinergia com o
**Caçador** (Comercial, análise de leads) e services de Reservas/NPS. Cachear copy gerada;
streaming no chat; escolher o modelo por custo/latência.

---

## 🌦️ Previsão do tempo no CRM (ferramenta pro vendedor + precificação)

Pousada de lago/ao ar livre = o **tempo é o fator nº 1** da experiência e da demanda.
Ter isso na mão do **vendedor** (informar o hóspede + ajustar a oferta) é acionável.
*Relacionado: o clima como **fator de precificação** está em
[`docs/Precificação/precificação.md`](./Precificação/precificação.md).*

- [ ] 🟢 **Widget de clima — curto prazo (até ~14 dias)** — sol/chuva/temperatura no
      **dashboard** e na **tela de reserva/lead**. Fonte **Open-Meteo** (grátis, sem chave),
      coordenada de Itá; cache diário via cron. *Feature real e barata; preciso o bastante p/ operar.*
- [ ] 🟡 **Card de panorama sazonal — longo prazo (3–6 meses)** — **ENSO (El Niño/La Niña)**
      + tendência da estação, **probabilístico** (não é previsão diária). Fontes NOAA/CPC,
      INMET, CPTEC; atualização ~mensal (manual ou API). Contexto pra **precificar a alta**.
      *Médio prazo (2–6 semanas) = tendência, não certeza.*
- [ ] 🟡 **Gatilhos de venda** — "chuva no fim de semana → sugerir **cancelamento flexível /
      last-minute**"; "sol + feriado → **segurar tarifa**".
- ⚠️ **Regra de ouro:** nunca vender previsão como **certeza** ao hóspede — sempre
      "previsão, sujeita a mudança" (senão vira reclamação).

**Conclusão:** curto prazo é feature real e barata; longo prazo é panorama probabilístico
(bem enquadrado, ainda muito útil pra precificar).

---

## ⛔ Não replicar (é rede/serviço da Foco, não software)

- **Rede de 800 canais / 500 agências / Abracorp** (R$ 15/reserva) — é o *negócio* deles.
  No máximo integrar a OTAs diretos.
- **FocoSafe** (cofre de cartão) — o padrão útil ("logs públicos de acesso a dado
  sensível") já é coberto pela nossa **trilha de auditoria**.

---

## Próximo passo sugerido

Começar pelo **selo de escassez + comparador de preço** na vitrine do site — menor
esforço, retorno imediato, apoia-se em dados que já temos.

*Fonte: [`docs/Foco_Tecnologia.pdf`](./Foco_Tecnologia.pdf) · relacionado: [`docs/Tarifario.pdf`](./Tarifario.pdf), [`docs/ESPECIFICACAO.md`](./ESPECIFICACAO.md) (§8)*

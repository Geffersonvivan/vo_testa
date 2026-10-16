# Plano de implementação — Áudio (mensagens de voz) no WhatsApp do CRM

> Passo a passo para **receber** e **enviar** mensagens de **áudio/voz** pela conversa
> de WhatsApp do funil, usando a Cloud API da Meta. Espelha o fluxo de texto que já
> existe e reaproveita o storage (R2) do projeto.
>
> **Regra da Meta:** áudio é **mensagem de sessão** — só dá pra enviar **dentro da janela
> de 24h** (depois que o cliente falou). **Não entra em template.** Receber é sempre ok.
> Formatos: AAC, MP4, MPEG, AMR, OGG/Opus · até ~16 MB.

---

## 0. O que já existe (reusar)

| Peça | Onde |
|---|---|
| Webhook + parser | `apps/comercial/views_whatsapp.py` + `services.processar_webhook_whatsapp` (hoje trata text/button/interactive; outros viram `[tipo]`) |
| Registro de mensagem | `services.receber_mensagem_whatsapp` → cria `MensagemWhatsApp` |
| Envio | `services.enviar_mensagem_whatsapp` (texto livre, respeita janela 24h) |
| Gateway Cloud | `apps/comercial/whatsapp_gateways.py` → `GatewayCloud` + `_api_post` (Graph API, Bearer token) |
| Modelo | `comercial.MensagemWhatsApp` (conversa, direcao, texto, status, id_externo, horario) |
| UI da conversa | `templates/comercial/oportunidade.html` (`.wpp-thread`/`.wpp-msg`/`.wpp-form`) |
| Storage de mídia | R2/S3 via `django-storages` (já configurado p/ `MEDIA`) |

---

## 1. Modelo — guardar a mídia (migração)

Adicionar campos em `comercial.MensagemWhatsApp` (`apps/comercial/models.py`):
- [ ] `tipo` (TextChoices: `texto` default, `audio`, `imagem`, `documento`…) — começa com `texto`/`audio`.
- [ ] `midia_id_externo` (CharField, blank) — o `media id` da Meta.
- [ ] `midia_arquivo` (FileField, `upload_to="whatsapp/audio/%Y/%m/"`, null/blank) — o binário no R2.
- [ ] `midia_mime` (CharField, blank) · `midia_voz` (Boolean, default False — "nota de voz") · `duracao_seg` (PositiveInt, null).
- [ ] `texto` continua servindo de **legenda/placeholder** (ex.: `"[áudio]"`).
- [ ] Migração.

---

## 2. RECEBER áudio (inbound)

### 2.1 — Baixar a mídia da Meta (service novo)
- [ ] `baixar_midia_whatsapp(media_id) -> (conteudo_bytes, mime)` em `services.py`:
  1. `GET https://graph.facebook.com/{v}/{media_id}` (Bearer `WHATSAPP_CLOUD_TOKEN`) → devolve `url` + `mime_type`.
  2. `GET` na `url` **com o header Authorization** (a URL é temporária, expira em minutos) → bytes.
  3. Reusa o padrão de `_api_post` (urllib) do gateway. Melhor método no `GatewayCloud` (`baixar_midia`) pra manter plugável/simulado.

### 2.2 — Parser do webhook
- [ ] Em `processar_webhook_whatsapp`, tratar `tipo == "audio"`:
  - `audio = m.get("audio")` → `media_id = audio["id"]`, `mime = audio.get("mime_type")`, `voz = audio.get("voice", False)`.
  - `texto = "[áudio]"` (placeholder) — e **gate**: áudio **conta como conteúdo do cliente** → `permitir_criar=True` (abre lead, igual texto). Adicionar `"audio"` ao `_TIPOS_CONTEUDO_WHATSAPP`.
  - Passar o media_id/mime/voz pro `receber_mensagem_whatsapp`.

### 2.3 — Gravar + persistir
- [ ] `receber_mensagem_whatsapp(...)` ganha params `tipo="texto"`, `midia_id=""`, `midia_mime=""`, `midia_voz=False`.
  - Mantém a idempotência por `id_externo` (constraint já existe) e a lógica de lead.
  - Quando `tipo=="audio"`: baixa a mídia (`baixar_midia_whatsapp`), salva em `midia_arquivo` (R2) via `ContentFile`, grava `tipo=audio`, `midia_mime`, `midia_voz`.
  - **Best-effort:** se o download falhar, grava a mensagem com `tipo=audio` + só o `midia_id_externo` (pra retentar depois) — nunca perde o registro.
- [ ] (Opcional) cron `reprocessar_midias_whatsapp` pra baixar as que falharam (a URL da Meta expira; mas o `media_id` ainda resolve por alguns dias).

---

## 3. ENVIAR áudio (outbound)

### 3.1 — Upload + envio (gateway)
- [ ] `GatewayCloud.upload_midia(bytes, mime) -> media_id`: `POST /{phone_id}/media` (multipart: `messaging_product=whatsapp`, `file`, `type=<mime>`).
- [ ] `GatewayCloud.enviar_audio(conversa, media_id)`: `POST /{phone_id}/messages` com `type:"audio"`, `audio:{id: media_id}`.
- [ ] Stubs no `GatewaySimulado` (retornam ok sem rede, p/ testes).

### 3.2 — Service
- [ ] `enviar_audio_whatsapp(*, conversa, arquivo, usuario)`:
  - **Checa a janela de 24h** (igual `enviar_mensagem_whatsapp`): fora da janela → `ValidationError` (áudio não vai por template).
  - `upload_midia` → `enviar_audio` → grava `MensagemWhatsApp(direcao=saida, tipo=audio, midia_arquivo=<salvo no R2>, status=enviada/erro, id_externo=wamid, autor=usuario)`.
  - Guarda o próprio áudio enviado no R2 (pra reproduzir no histórico).

### 3.3 — View + URL
- [ ] Rota `whatsapp/<pk>/audio/` → `views.whatsapp_enviar_audio` (`@requer_modulo(Modulo.COMERCIAL)`), recebe o arquivo (multipart) e chama `enviar_audio_whatsapp`. Responde JSON `{ok, erro}`.

---

## 4. UI na conversa (`oportunidade.html`)

### 4.1 — Mostrar áudio recebido/enviado
- [ ] No loop de `mensagens_wpp`, quando `m.tipo == "audio"`: renderizar um **player** em vez de texto:
  `<audio controls preload="none" src="{url protegida}">` dentro do balão `.wpp-entrada`/`.wpp-saida`.
  - A **URL do áudio** deve ser **protegida** (ver §5), não o link público do R2.

### 4.2 — Gravar e enviar voz (no `.wpp-form`)
- [ ] Botão **🎤 Gravar** ao lado do "Enviar": usa a **MediaRecorder API** do navegador (`audio/webm;codecs=opus` ou `audio/ogg`).
  - Ao parar, faz `fetch` multipart pra `whatsapp/<pk>/audio/`.
  - Mostra o tempo de gravação + botões gravar/parar/cancelar (Alpine).
- [ ] (Alternativa simples) um `input type=file accept="audio/*"` pra anexar um áudio pronto.
- [ ] **Design Lampião:** botão no padrão `.botao-mini`/`.botao-primario`, feedback no `:active`, respeitar `prefers-reduced-motion`.

> Nota de formato: pra sair como **"nota de voz"** (bolha push-to-talk) no WhatsApp do cliente, enviar **OGG/Opus**. `webm/opus` do navegador pode precisar de **transcode p/ ogg** no backend (ex.: `ffmpeg`, que já existe na máquina) — senão vai como "arquivo de áudio" comum (funciona, só não é a bolha de voz).

---

## 5. Storage & segurança (importante)

- Áudio de conversa é **dado privado do hóspede** → **NÃO servir pela URL pública do R2.**
- [ ] Servir por uma **view autenticada**: `midia/whatsapp/<msg_id>/` (`@requer_modulo(Modulo.COMERCIAL)`) que faz **stream** ou **redirect assinado (URL temporária do R2)**. O `<audio src>` aponta pra essa view.
- [ ] Guardar sob `MEDIA`/R2 com chave não-adivinhável.
- [ ] Baixar a mídia **no ato do webhook** (a URL da Meta expira em minutos).

---

## 6. Conformidade / limites
- **Janela de 24h:** enviar áudio só com a conversa aberta (cliente falou nas últimas 24h). Fora disso → bloqueia (não existe template de áudio).
- **Tamanho:** ≤ 16 MB; validar no upload.
- **Custo:** dentro da janela de serviço é **grátis** (como o texto) — áudio não é cobrado à parte.
- **LGPD:** áudio é conteúdo pessoal; aplicar a mesma política de retenção/acesso das demais mensagens.

---

## 7. Testes
- [ ] Webhook `type=audio` (payload com `audio.id`) → cria/anexa lead + grava `MensagemWhatsApp` tipo=audio (gateway `simulado`, download mockado).
- [ ] Áudio de **número novo** abre lead (igual texto).
- [ ] `enviar_audio_whatsapp` **dentro** da janela = enviada; **fora** = `ValidationError`.
- [ ] Idempotência (mesmo wamid) não duplica.
- [ ] View de mídia exige login/módulo (não serve público).

---

## 8. Ordem sugerida
1. **Receber** (§1 modelo + §2) — valor imediato: ouvir o que o hóspede manda. Testável no `simulado`.
2. **Storage protegido** (§5).
3. **Enviar** (§3 + §4.2) — gravar/mandar voz.
4. **UI/player** (§4.1) + testes (§7).
5. (Opcional) transcode p/ OGG-Opus (nota de voz "de verdade") + cron de reprocesso.

## Arquivos tocados
`comercial/models.py` (+migração), `comercial/services.py`, `comercial/whatsapp_gateways.py`,
`comercial/views.py` + `views_whatsapp.py`, `comercial/urls.py`,
`templates/comercial/oportunidade.html`, `comercial/tests.py`.

## Referências no repo
- Texto (espelho): `enviar_mensagem_whatsapp`, `receber_mensagem_whatsapp`, `processar_webhook_whatsapp`,
  `_TIPOS_CONTEUDO_WHATSAPP`, `GatewayCloud._api_post`.
- Conta WhatsApp ativa + credenciais: [[whatsapp-cloud-api-live]].
- Campanhas (outro plano): `docs/WhatsAppAPI/Plano_Campanhas_e_Optin_WhatsApp.md`.

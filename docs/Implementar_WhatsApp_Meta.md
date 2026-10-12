# Implementar — WhatsApp Cloud API oficial (Meta) no CRM

Plano por fases para colocar o **WhatsApp Business Platform (Cloud API)** da Meta
operando no funil do CRM. Responsável: `[EU]` = código no CRM/site · `[DANI/VOCÊ]` =
administrativo no Gerenciador de Negócios/Meta.

> Não confundir com a **CAPI de marketing** (Pixel/Conversions API), que já está live em
> produção (`MIDIA_GATEWAY=meta`). Este plano é só a **mensageria** do funil
> (`WHATSAPP_GATEWAY`, hoje `simulado`).

App Meta: **"Pousada Vô Testa CRM"** (ID 28500031722959772). Portfólio "Pousada Vô Testa"
(ID 1320673763168182). Contato/DPO: danielafloresgg@gmail.com.

## Fase 0 — Pré-requisitos ✅
- [x] **Acesso ao portfólio Meta** — Dani tem acesso (destrava as fases 2–7).
- [x] **Home do site: tirar a LP, voltar o index** — `[EU]` removida a env `HOME_MODO`
  no Railway (produção); `/` volta a ser o index do site. A LP Fundador segue viva em
  `/lp/fundador/` (toggle `HOME_MODO=lp_fundador` religa quando quiser).

## Fase 1 — Páginas legais no site ✅ `[EU]`
- [x] `/politica-de-privacidade/`, `/termos-de-servico/`, `/exclusao-de-dados/` criadas
  (app `site`, visual do site, `<style>` escopado — sem depender do build do Tailwind).
- [x] Rodapé religado (Privacidade, Termos, Exclusão de dados, Cancelamento→âncora).
- [x] Conteúdo LGPD + menção ao WhatsApp Business/Meta + parceiros reais (Safrapay,
  hospedagem, Embratur/FNRH). CNPJ 26.003.246/0001-00, Itá/SC.
- [x] Testes (`PaginasLegaisTests`). **URLs para colar no app Meta:**
  - `https://www.pousadavotesta.com.br/politica-de-privacidade/`
  - `https://www.pousadavotesta.com.br/termos-de-servico/`
  - `https://www.pousadavotesta.com.br/exclusao-de-dados/`

## Fase 2 — Configuração básica do App `[DANI/VOCÊ]`
- [ ] Colar as 3 URLs da Fase 1 (Privacidade, Termos, Exclusão de dados).
- [ ] Domínio do app: `pousadavotesta.com.br`.
- [ ] **País: Brasil** (hoje está Estados Unidos).
- [ ] Ícone do app (logo), Categoria, contato do DPO.

## Fase 3 — Verificação do Negócio `[DANI/VOCÊ]`
- [ ] Submeter CNPJ + documentos no Gerenciador de Negócios; aguardar aprovação.

## Fase 4 — Número + nome de exibição + credenciais `[DANI/VOCÊ]`
- [ ] Registrar/confirmar o número no WABA e aprovar o nome de exibição.
- [ ] Gerar token permanente (System User), `phone_number_id`, `waba_id`, `verify_token`.

## Fase 5 — Ligar no CRM `[EU]` + `[DANI/VOCÊ]`
- [ ] `[EU]` Auditar o provider `meta` de `WHATSAPP_GATEWAY` (envio) e o **webhook de
  recebimento** — revisar versão da Graph API e campos (a API mudou; conferir).
- [ ] `[DANI/VOCÊ]` Setar no Railway: `WHATSAPP_GATEWAY=meta`, `WHATSAPP_TOKEN`,
  `WHATSAPP_PHONE_ID`, `WHATSAPP_WABA_ID`, `WHATSAPP_VERIFY_TOKEN`.
- [ ] Teste: mensagem real sai do funil e a resposta do cliente entra na conversa.

## Fase 6 — Templates de mensagem `[EU]` + `[DANI/VOCÊ]`
- [ ] Cadastrar templates aprovados (boas-vindas, retomada de cotação, proposta/sinal) e
  mapeá-los no CRM — fora da janela de 24h a Meta só aceita template aprovado.

## Fase 7 — Publicar + validar ponta a ponta `[DANI/VOCÊ]` + `[EU]`
- [ ] Publicar o app (sai do modo desenvolvimento).
- [ ] Teste real: lead responde → entra no funil → vendedora responde → chega no cliente
  → proposta/sinal pelo link.

---
**Caminho crítico:** Fases 2–4 (admin Meta) são o que libera a mensageria real. As fases
`[EU]` (1 e a parte de código da 5/6) não dependem desse processo.

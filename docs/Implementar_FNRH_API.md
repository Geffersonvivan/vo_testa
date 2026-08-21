# Integração com a API FNRH Digital (Embratur/Serpro)

Estado: **scaffold pronto** (gateway `simulado` funcionando). Falta ligar o provider
real (`serpro`) quando houver credenciais.

Fonte: [Documentação da API FNRH v2 (gov.br, 09/03/2026)](https://www.gov.br/turismo/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/ficha-nacional-de-registro-de-hospedes/modulo-meio-de-hospedagem/meios-de-hospedagem-com-pms/documentacao-api-v2-20260309.pdf)

## Como funciona a API

- **Autenticação:** HTTP Basic Auth (`usuário:senha` → Base64). Sem certificado A1.
- **Base URLs:**
  - Produção: `https://fnrh.turismo.serpro.gov.br/FNRH_API/rest/v2`
  - Homologação: `https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2`
- **Fluxo (estratégia B — empurramos nossos dados):**
  1. `POST /reservas` → devolve `reserva_id`
  2. `POST /pessoas` (por hóspede) → devolve `pessoa_id`
  3. `POST /reservas/{id}/hospedes` (com bloco `fnrh`: motivo + transporte)
  4. `POST /reservas/{id}/checkin` (lote) — e `/checkout`, `/cancelar`, `/noshow`
- **Domínios** (`GET /dominios/...`): listas canônicas de códigos (motivo, transporte,
  gênero, tipo de documento, etc.). Os choices de `FichaFNRH` **já usam esses ids**
  como valor — sem de-para.

## O que já está pronto no CRM

- `apps/reservas/fnrh_gateway.py` — `simulado` + `serpro` (HTTP real via urllib) + de-para.
- `services.enviar_fnrh(reserva)` — orquestra, idempotente, best-effort.
- Gatilho: check-in marca `pendente`; a view empurra na hora; cron reprocessa.
- Campos de sincronização em `Reserva` e `FichaFNRH`.
- Cron: `manage.py enviar_fnrh_pendentes` (rodar a cada poucos minutos).
- UI: status + botão "Reenviar" no detalhe da reserva.

## Para ligar em produção

1. **Obter credenciais SNRHos** (usuário/senha) — cadastro do estabelecimento no sistema
   do Ministério do Turismo, via Cadastur.
2. **Testar em homologação** primeiro:
   ```env
   FNRH_GATEWAY=serpro
   FNRH_API_URL=https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2
   FNRH_API_USER=...
   FNRH_API_SENHA=...
   ```
3. **Fechar as lacunas de dados** (hoje mapeadas com fallback):
   - **País** em ISO 3166-1 alpha-2 no cadastro (guardamos texto livre → assume `BR`).
   - **Cidade** em código IBGE (guardamos texto).
   - Campos opcionais que não coletamos: raça/etnia, deficiência, nome social.
4. **Virar a chave** para produção (`FNRH_API_URL` de produção) após validar em HML.

## Checklist de campos por hóspede (mínimo aceito)

nome · data_nascimento · tipo+número de documento (CPF nacional / PASSAPORTE estrangeiro)
· país (ISO) · motivo da viagem · meio de transporte · is_principal (titular).

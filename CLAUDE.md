# CRM Pousada Vô Testa

Sistema de gestão (PMS/CRM) para a Pousada Vô Testa — 24 quartos.
**Fonte da verdade do produto:** `docs/ESPECIFICACAO.md` (módulos, regras de negócio, fases).
Pesquisa de mercado: `docs/REFERENCIA_DESBRAVADOR.md`.

## Stack

- Python 3.14 + Django 6.x + PostgreSQL (local: banco `crm_vo_testa`, Postgres 14 via brew)
- Templates Django + HTMX + Alpine.js (CDN) — sem SPA
- API pública (módulo APP/Site) com Django REST Framework — ainda não instalado
- Deploy: Railway (gunicorn + whitenoise)

## Comandos

```bash
.venv/bin/python manage.py runserver      # dev server
.venv/bin/python manage.py test           # testes (obrigatório antes de commit)
.venv/bin/python manage.py makemigrations # após mudar models
.venv/bin/python manage.py migrate
```

Config por variável de ambiente (`.env` local — ver `.env.example`). `DEBUG=1` no dev.

## Deploy, commit e push

**NUNCA fazer deploy, commit ou push sem comando explícito do usuário.** Trabalhar
normalmente no código local (editar, migrar, testar); versionar e subir, só quando
ele mandar. Quando o deploy for autorizado: criar projeto Railway novo para o CRM —
o projeto `pousada-vo-testa` existente é o SITE em produção (repo
`Pousada_Vo_Testa.git`), não tocar.

## Processo por módulo

Ao iniciar qualquer fase/módulo, **consultar primeiro como o Desbravador resolve**:
<https://www.desbravador.com.br/produtos/hoteis-e-pousadas> (+ resumo em
`docs/REFERENCIA_DESBRAVADOR.md`) — funcionalidades, fluxos e telas — antes de
desenhar o nosso.

## Arquitetura (regras que não se quebram)

- **Núcleo + módulos contratáveis.** Cada módulo é um app Django em `apps/`.
  Catálogo e dependências em `apps/nucleo/modulos.py`; ativação na tabela
  `ModuloContratado`. Menus/comportamentos consultam `modulo_ativo()` — nunca hard-code.
- **Módulos só conversam por services/interfaces públicas**, nunca importam models
  internos uns dos outros (exceto do núcleo). Degradação graciosa: módulo funciona
  sem os opcionais (ex.: Loja sem Reservas = só venda balcão).
- **Fonte de verdade única:** disponibilidade → Reservas; dinheiro → Financeiro (núcleo);
  estoque → motor de estoque (núcleo).
- **Dinheiro:** `DecimalField`, nunca float. Movimentos de caixa e estoque são
  imutáveis — correção é movimento inverso, nunca update/delete.
- **Overbooking:** impedido por `ExclusionConstraint` (PostgreSQL) quando o módulo
  Reservas for implementado.
- **Auditoria:** operações sensíveis (estorno, cancelamento, ajuste, reabertura de
  caixa) registram quem/quando/por quê.
- `AUTH_USER_MODEL = nucleo.Usuario` — nunca usar `django.contrib.auth.models.User`.
- **Acesso por usuário × módulo, gerido pelo Admin:** toda view de módulo usa
  `@requer_modulo(Modulo.X)` (`apps/nucleo/permissoes.py`). Módulo inativo → 404;
  usuário sem o módulo em `Usuario.modulos` → 403. Superusuário acessa tudo.

## Convenções

- Domínio em português: models, campos, verbose_names, templates, testes
  (ex.: `Reserva`, `UH`, `ModuloContratado`). Infra em inglês quando for padrão Django.
- UI em pt-BR; `TIME_ZONE = America/Sao_Paulo`.
- Testes em `apps/<app>/tests.py` (TestCase); regras de dinheiro e disponibilidade
  sempre testadas.
- Antes de finalizar entrega de módulo: testes passando → skill django-verification →
  /code-review → commit → deploy.

## Estado atual

- **Fase 0 concluída**: núcleo com login, dashboard, registro de módulos (11 da fase 1
  ativos via migração seed), layout base, deploy Railway.
- **Núcleo completo implementado** (aguardando validação do usuário): cadastros
  (Pessoa + especializações, TipoUH/UH, temporadas), financeiro/caixa (sessão por
  operador×módulo, movimentos imutáveis, conferência cega, estorno/reabertura
  auditados, lançamentos, contas a pagar/receber), logbook e dashboard com
  indicadores. Models em `apps/nucleo/models/` (pacote); gerência =
  `eh_gerente()`/`@requer_gerencia` em `permissoes.py` (staff/superuser até perfis
  por módulo). Formas de pagamento seedadas; categorias financeiras no admin.
- **Núcleo validado pelo usuário** (caixa testado em 04/07/2026).
- **Reservas implementado** (aguardando validação): app `apps/reservas` com
  ciclo de estados, antioverbooking via `ExclusionConstraint` (btree_gist),
  mapa UH×dias, conta da hospedagem (naturezas serviço×consumo), pagamento e
  adiantamento via caixa do operador, tarifas TipoUH×temporada (admin) com
  precedência de feriado. Interface pública em `apps/reservas/services.py`.
  Pendente para iterações seguintes: FNRH, wait list, arrastar no mapa,
  expiração automática de pré-reserva, auditoria diária.
- **Pessoas evoluído**: campo `tipo` PF/PJ (com sigla), papel **Agência/Empresa**
  (`Agencia`, OneToOne), tabela com filtros por papel + contadores + coluna Tipo.
  Reserva agora tem `faturamento` (particular/agência/empresa) + `titular` — quem
  paga pode não ser quem se hospeda (`reserva.pagador`).
- **Estoque implementado** (aguardando validação): motor no núcleo
  (`apps/nucleo/models/estoque.py` — Produto/custo médio ponderado, LocalEstoque,
  MovimentoEstoque kardex imutável, Inventário; services `saldo`, `registrar_entrada`,
  `registrar_saida`, `transferir`, `ajustar`, `posicao_estoque` — interface pública
  para os outros módulos). App `apps/estoque` = telas de gestão (@requer_modulo):
  posição com alertas de mínimo, produtos, entrada/saída/transferência/ajuste, kardex,
  inventário. Saída não deixa saldo negativo; ajuste/transferência/inventário auditados.
- **Redesign moderno aplicado** ("Lampião"): canvas branco-quente + cartões com
  elevação, cores semânticas, tokens em `static/css/app.css` (`--canvas`, `--superficie`,
  `--sombra-*`, `--raio*`, semânticas). App-shell novo em `base.html`: sidebar Noturno
  recolhível com ícones/pílula ativa (⌘\\), topbar com busca ⌘K, avatar. **Paleta de
  comandos** (⌘K / `/`) com busca global (`busca_global`) e ações. **Toasts** (mensagens
  Django viram notificações). **Atalhos** (N = nova reserva). Dashboard com **KPIs** +
  chegadas/saídas do dia. Modais com header/footer e escala. Ícones = SVG inline.
  **Pendente (fast-follow):** Modo Noturno (dark) como alternador de tema.
- **Dashboard operacional**: bloco "Precisa de atenção" (contas vencidas, estoque
  mínimo, pré-reservas a confirmar, recados importantes — acionáveis) + módulos como
  atalhos clicáveis ("em breve" nos sem tela). **Central de Módulos**
  (`/configuracoes/modulos/`, gerência): catálogo dos 14 módulos com status
  funcionando/construção/disponível, dependências e ativar/desativar respeitando
  `DEPENDENCIAS` (reverso incluído). Item "Configurações → Módulos" no menu (só staff).
- **Gráficos de decisão no dashboard** (Chart.js CDN, tematizado com a paleta):
  ocupação 14 dias (linha), ocupação por tipo (barras), receita da semana
  serviço×consumo (barras empilhadas), origem das reservas e mix de pagamento
  (donuts), funil de reservas. Dados em `reservas.services.dados_graficos()` +
  mix de pagamento (MovimentoCaixa) no dashboard view; passados via `json_script`.
- **Loja implementada** (§5.6, primeiro PDV — valida estoque + caixa juntos):
  app `apps/loja` com Venda/ItemVenda; `finalizar_venda` baixa estoque
  (`registrar_saida`) e cobra por dois destinos — pagamento imediato
  (`receber_no_caixa`, novo helper público no núcleo) OU conta do quarto
  (`reservas.services.lancar_na_conta`, degrada se Reservas inativo). Cancelamento
  (gerência) devolve estoque via ajuste + estorna o caixa; conta bloqueada.
  PDV com carrinho Alpine, recibo, histórico. Menu `loja:pdv`.
- **Mapa de quartos** (Reservas): grid dos 24 quartos como portas (estilo
  Desbravador — aberta/fechada, cores, símbolo pessoa/chave/lixeira), 8 por linha,
  filtros por situação/tipo. **Troca de quarto** (`services.trocar_quarto`): muda
  `reserva.uh`; a conta/consumo segue a reserva; antioverbooking valida; auditado.
  Feita **arrastando** um quarto ocupado sobre um livre no mapa, ou pelo botão
  "Trocar de quarto" no detalhe. Botão "Voltar" (history.back) no detalhe.
- **Governança implementada** (§5.2): app `apps/governanca` com StatusLimpeza (por
  quarto: limpa/suja/em limpeza/inspecionada) + TarefaGovernanca; painel com fila de
  faxinas e situação dos quartos. **Integração por sinal**: reservas emite
  `quarto_liberado` no check-out e na troca; governanca (se ativa) ouve, marca o
  quarto sujo e gera a faxina — sem inverter dependência. O **Mapa de quartos** passa
  a ler o status real de limpeza (a limpar/em limpeza/livre) quando Governança ativa.
  Pendente: bloquear check-in em quarto sujo (hook opcional), integração Lavanderia.
- Modo Noturno (dark): **descartado** pelo usuário — não implementar.
- **Restaurante Piscina implementado** (§5.7): app `apps/restaurante` com Mesa,
  Comanda (aberta/fechada), ItemComanda. Comanda aberta por mesa/hóspede/avulso;
  cada item baixa estoque na hora (add via HTMX); fechamento por caixa
  (`receber_no_caixa`) OU conta do quarto (`reservas.lancar_na_conta`); remover item
  e cancelar devolvem estoque; transferir de mesa. Reaproveita o visual do PDV da
  Loja. Ficha técnica (item→insumos) fica para depois (MVP = 1 produto = 1 baixa).
  Pontos de atendimento (antes "Mesa") = mesa/guarda-sol/bar; Mesa 01–24 seedadas.
- **Combobox de pessoa** (`templates/componentes/combo_pessoa.html`): seletor com
  busca instantânea + agrupamento por papel (Hóspedes → Clientes avulsos → Agências e
  empresas → Funcionários → Fornecedores), cabeçalho de grupo sticky. Componente
  Alpine `comboPessoa` registrado global em `base.html`; dados via
  `nucleo.seletores.pessoas_agrupadas(queryset=None)` → `json_script`. Renderiza um
  `<input type=hidden name=…>` (o form Django valida igual). Usado em: abrir comanda
  (Restaurante) e modal de nova reserva (hóspede + titular). Params do include:
  `dados`, `dados_id`, `campo`, `placeholder`, `valor_id`.
- **Manutenção implementado** (§5.3): app `apps/manutencao` com OrdemServico
  (quarto OU área comum, tipo corretiva/preventiva, prioridade, responsável, custos
  mão de obra+peças, status aberta→em andamento→concluída/cancelada). **Bloqueio de
  quarto** = `uh.status = BLOQUEADA` (disponibilidade/mapa/troca/ReservaForm já
  respeitam ATIVA); não bloqueia quarto ocupado (consulta `reservas.uh_ocupada`).
  Concluir **libera** o quarto e emite sinal `reparo_concluido` → Governança (se
  ativa) abre faxina (origem="manutencao"), mesmo padrão do check-out. Preventiva com
  `recorrencia_meses` agenda a próxima OS ao concluir. Bloqueio/liberação/cancelamento
  auditados. Menu `manutencao:painel`. Peças via motor de Estoque = fast-follow (hoje
  custo manual). OS tem ainda **prestador externo** (FK Pessoa fornecedor/empresa, via
  combobox), **nota fiscal**, **garantia até** e **previsto para** — todos opcionais.
  Seed: `manage.py popular_manutencao --limpar` (mix de estados + ciclo completo).
- **Lavanderia implementada** (§5.8, duas metades): app `apps/lavanderia`.
  **(a) Serviço ao hóspede** — `ServicoLavanderia` (tabela de preços), `OrdemLavanderia`
  + `ItemOrdemLavanderia`; ciclo recebida→lavando→pronta→entregue; entrega cobra no
  caixa (`receber_no_caixa`) OU na conta do quarto (`reservas.lancar_na_conta`,
  tipo="servico", natureza SERVIÇO). Reusa combobox de pessoa e visual do PDV.
  **(b) Rouparia interna** — `ItemEnxoval` (mínimo + `por_faxina`) e `MovimentoEnxoval`
  (livro-razão imutável por estado: limpa/em_uso/suja/lavando); services
  adquirir/distribuir/coletar_suja/enviar_lavar/receber_limpo/baixar (auditada),
  `posicao_enxoval` com alerta de mínimo. **Integração Governança**: governança emite
  `faxina_concluida` (novo `governanca/signals.py`) ao concluir faxina; lavanderia
  ouve e recolhe o kit `por_faxina` de cada item (em uso→suja) para aquele quarto.
  Seed `manage.py popular_lavanderia --limpar`. Insumos de lavagem via Estoque =
  fast-follow.
- **Frigobar implementado** (§5.9): app `apps/frigobar`. `ItemComposicao` = kit padrão
  por TipoUH; `Conferencia` (arrumação/check-out) + `ItemConferencia`. A conferência
  registra o consumido sobre a composição e **lança na conta do quarto**
  (`reservas.lancar_na_conta`, natureza CONSUMO); a **reposição** baixa o **estoque
  central** de frigobar (`registrar_saida` do LocalEstoque modulo=frigobar); painel
  com **lista de reposição** agregada das conferências pendentes. Composições geridas
  em `frigobar:composicoes`. Seed `manage.py popular_frigobar --limpar`. Pendente
  (fast-follow): **check-out bloqueado até conferência** (precisa de guard no check-out
  do Reservas, sem inverter dependência) e estorno de conferência.
- **Escala implementada** (§5.4, diferencial — Desbravador não tem): app `apps/escala`.
  `Turno` (setor + faixa de horário), `Atribuicao` (funcionário×dia×turno, única),
  `Ausencia` (folga/férias/atestado — bloqueia escalar o ausente), `TrocaTurno`
  (solicitação → aprovação da gerência reatribui o turno). **Grade semanal** por setor
  (turnos×7 dias com chips de funcionários, navegação de semana), **Minha escala**
  (funcionário vê a sua via `Funcionario.usuario`), turnos/ausências/trocas em telas
  próprias. Depende só do Núcleo (usa `Funcionario`). Seed
  `manage.py popular_escala --limpar`. Fast-follow: atribuir tarefas de
  Governança/Manutenção a quem está de turno.
- **Pagamentos Online implementado** (§5.10): app `apps/pagamentos`, **gateway
  plugável** (`gateways.py` — `PAGAMENTOS_GATEWAY` no settings; **Simulado/sandbox** por
  padrão, provedor real a definir §9). `Cobranca` (Pix/cartão/boleto/link, token público
  UUID, status pendente→pago/estornado/cancelado, dados do gateway + payload p/
  conciliação) e `EventoPagamento` (trilha/webhooks). Services: `criar_cobranca`
  (chama o gateway), `confirmar_pagamento` (**idempotente**; sinal de reserva →
  `reservas.confirmar_reserva`), `estornar` (auditado), `cancelar`, `conciliacao`.
  **Webhook** `pagamentos:webhook` (csrf-exempt, acha a cobrança por `gateway_id`);
  **link de pagamento público** (`pagar/<token>/`, sem login, template standalone) com
  botão "Já paguei" (sandbox). Painel (criar/listar + conciliação), detalhe (Pix
  copia-e-cola, link, simular/estornar/cancelar, histórico). Reservas ganhou
  `confirmar_reserva` e `pendentes_de_sinal`. Fast-follow (amarrado ao gateway real):
  **lançamento financeiro do dinheiro online sem caixa** (adiantamento/folio) e estorno
  integrado ao Financeiro.
- **Comercial implementado (plano P0–P3)**: funil Kanban com ganho só via
  conversão, perda com motivo, cotação real, sinal opcional (Pagamentos), SLA
  24h/48h na Auditoria, score/metas/forecast no painel, templates copiáveis,
  hand-off pós checkout/cancelamento. Site: form «Pedir proposta» (`#contato` /
  `#eventos`) → `capturar_lead_site` com `tipo_interesse`. Doc:
  `docs/Plano_Comercial.md`.
- **Dia na Pousada (day use)**: `TipoUH.modalidade=day_use` + UHs `DAY-01..08`
  (fora do mapa dos 24). Mesmo fluxo de reserva do site (`?modalidade=day_use`),
  conta/consumo no CRM. Seção `#dia-pousada` na home. Eventos: seção `#eventos`
  com lead comercial (não é self-service de salão).
- **NPS (esqueleto / proposta)**: app `apps/nps` — item **NPS** na sidebar
  (Relacionamento), ícone no portal do hóspede (`/hospede/<token>/nps/`), API stub
  `/api/nps/v1/` (HTTP 501). Contrato em `apps/nps/proposta.py` e
  `docs/Proposta_NPS.md`. Coleta real = fase CRM do Hóspede.
- **Portal do Hóspede implementado** (§5.11 metade B): app `apps/portal`. Acesso
  público por **token opaco/QR** durante a estadia (`/hospede/<token>/`), sem login.
  `AcessoPortal` (token por reserva) e `SolicitacaoPortal` (trilha). Lê a conta via
  `reservas.dados_estadia`/`estadia_ativa` (novos services); ações do hóspede
  encaminhadas aos services dos módulos e atribuídas ao usuário de sistema `_portal`:
  **pedir no restaurante** (abre comanda no quarto, baixa estoque), **limpeza extra**
  (`governanca.abrir_faxina`, origem="portal"), **manutenção** (`manutencao.abrir_os`),
  **check-out expresso** (`pagamentos.criar_cobranca` finalidade=saldo_conta → página
  pública de pagamento; recepção finaliza). Degrada se um módulo estiver inativo. QR
  gerado inline (SVG, lib `qrcode`) na tela da recepção (`portal:qr`, em Reserva
  hospedada); painel interno `portal:solicitacoes`. Template mobile standalone com a
  logo. Filtro `{% ... |modulo_ativo %}` em `nucleo/templatetags/nucleo_extras.py`.
- **Integração site↔CRM — um projeto, um banco, roteado por URL** (em andamento).
  Decisão: trazer o site pra dentro do CRM. Domínio único servirá `/` = site público e
  `/crm/` = sistema (admin/funcionários).
  - **Passo 1 (feito):** todo o CRM movido para `/crm/…` (nucleo, módulos, admin, login);
    portal do hóspede segue em `/hospede/`; login/redirect usam nomes de rota (ajuste
    automático). Corrigido 1 fetch hardcoded no mapa (via `{% url %}`).
  - **Passo 2 (feito):** site copiado **verbatim** do `../Site_Vo_Testa` para `apps/site`
    (label `core`, tabelas `core_*`, migrations reusadas). Templates namespaced sob
    `templates/site/`, estáticos sob `static/site/`, mídia em `media/`. Dados migrados
    (dumpdata→loaddata: quartos, fotos, temporadas, hóspedes, depoimentos, galeria).
    Site servido em `/`, idêntico ao de produção (fluxo reservar→confirmada, **sem
    pagamento ativo** — Etapa B do próprio site). Context processors `reserva_passos`/
    `prova_social` adicionados. `MEDIA_URL/ROOT` configurados.
  - **Passo 3 (feito) — "Reservar" religado ao CRM (venda por tipo):** `site.Quarto`
    ganhou FK `tipo_uh`→`nucleo.TipoUH`; a vitrine agora é **1 card por tipo do CRM**
    (comando `manage.py sincronizar_quartos`; os 6 quartos temáticos antigos ficam
    ocultos). Disponibilidade e preço vêm do CRM (`reservas.tipo_disponivel`,
    `diaria_media`). `finalizar_reserva` cria o hóspede (`reservas.obter_ou_criar_hospede`
    → Pessoa+Hospede) e uma **PRÉ-RESERVA no CRM** num quarto físico livre
    (`reservas.criar_reserva_site`, canal SITE, antioverbooking pela constraint);
    `site.Reserva` vira o **recibo do canal** com `crm_reserva_id`. Uma reserva do site
    já aparece no mapa e conta na ocupação. **Fim do overbooking entre canais.**
  - **Passo 4 (feito) — expiração automática da retenção:** `reservas.Reserva` ganhou
    `expira_em`; `criar_reserva_site` grava `now + RESERVA_RETENCAO_MINUTOS` (settings,
    default 30). A disponibilidade (`reservas_ativas_qs`/`uhs_disponiveis`) **ignora
    pré-reservas vencidas em tempo real** (quarto já aparece livre antes do job).
    `expirar_vencidas()` cancela as vencidas (motivo registrado) e roda no
    `criar_reserva_site` (antes de alocar) + comando de cron
    `manage.py expirar_reservas` (backstop). `confirmar()` limpa `expira_em`.
  - **Pendente (fase 2, cutover):** (1) **gateway de pagamento = Safrapay** no módulo
    Pagamentos (o site hoje finaliza sem pagamento) — implementar provider Safrapay em
    `pagamentos/gateways.py` e ligar o sinal ao `confirmar_reserva`; (2) reconciliar/
    limpar os models duplicados do site (core.Reserva/Quarto/Hospede vs CRM) e telas de
    gestão do site no CRM; (3) apontar DNS `www.pousadavotesta.com.br` pro app unificado
    e aposentar o `Site_Vo_Testa`. Até o cutover, não tocar no site em produção.
- **Fiscal — esqueleto implementado** (§14, fase 2, **inativo por padrão**): app
  `apps/fiscal` com **gateway plugável** (`FISCAL_GATEWAY`: `simulado` sandbox ativo /
  `focus` Focus NFe / `governo` direto — os dois últimos são **stubs** a preencher).
  `DocumentoFiscal` (tipo nfse/nfce/nfe, natureza, status, número/chave/protocolo,
  tomador, referência solta, payload) + `EventoFiscal` (trilha) + `ConfigFiscalProduto`
  (NCM/CFOP/CST por produto). Services `emitir` (natureza SERVIÇO→NFS-e, CONSUMO→NFC-e)
  e `cancelar` (auditado). Painel/detalhe (`fiscal:painel`, gerência p/ cancelar).
  **Fluxo NFS-e da diária esboçado:** `emitir_nfse_da_conta(conta_id)` (idempotente) pega
  a parte SERVIÇO da conta via `reservas.resumo_fiscal_conta` e emite com os parâmetros
  confirmados pelo contador (settings: código **090101**, ISS **4%**, Lucro Presumido);
  botão "Emitir NFS-e da hospedagem" no detalhe da reserva. NFC-e aguarda **Inscrição
  Estadual** (empresa não tem — em curso).
  Pendente: provider real (Focus/governo) + **certificado A1** + cadastro de produtos
  (NCM). **Plano e custos em `docs/Implementar_fiscal.md`**
  (NFS-e Nacional desde 01/07/2026; Focus NFe R$89,90/mês × rota grátis governo;
  município Itá/SC; pagamento do site = **Safrapay**).
- **Auditoria implementada** (módulo `Modulo.AUDITORIA`, grupo Gestão, ativo por
  migração própria): app `apps/auditoria`, **read-only**. **(1) Varredura de pendências**
  — `services.varrer()` agrega checagens do núcleo (caixa aberto de dia anterior, contas
  a pagar/receber vencidas, estoque abaixo do mínimo) + `pendencias_auditoria()` que cada
  módulo dono expõe (Reservas: check-out vencido, conta com saldo, pré-reserva vencida,
  confirmada sem sinal; Manutenção: OS antiga, quarto bloqueado; Fiscal: nota rejeitada).
  Cada achado tem gravidade + link "Resolver". Painel com KPIs. **(2) Trilha de auditoria**
  — tela de leitura/filtro da `TrilhaAuditoria` (usuário/ação/período) + **exportar CSV**.
  Não altera dados; correção nos módulos donos. Decoupling: auditoria só chama services
  (sem import cruzado de models).
- Fase 1 de módulos concluída. Fase 2 (§8): CRM do Hóspede, Canais/OTAs, Fiscal
  (provider real), integração site↔CRM (cutover), Safrapay.
- Perguntas de negócio em aberto: §9 da especificação (parâmetros, não bloqueiam).

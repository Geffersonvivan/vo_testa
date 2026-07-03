# Referência: Produtos Desbravador (pesquisa de mercado)

Levantamento feito em 03/07/2026 a partir de https://www.desbravador.com.br/produtos/hoteis-e-pousadas
e das 9 páginas de produto, complementando o PDF `BASE_Projeto/apresentacao_easy_web.pdf`.
Serve de base para a especificação do CRM da Pousada Vô Testa (24 quartos).

## 1. Produtos encontrados

| # | Produto | Descrição |
|---|---------|-----------|
| 1 | **PMS Desbravador 5.0** | PMS mais recente e completo, para grande porte e redes; multiempresa, cloud, interface moderna (Cockpit, Dark Mode) |
| 2 | **Light Web** | PMS 100% na nuvem para pequeno/médio porte, hostels e **pousadas** — o produto mais análogo ao nosso caso |
| 3 | **iService** | Web app de autoatendimento do hóspede (check-in/out online, serviço de quarto, extrato, pesquisa de satisfação) |
| 4 | **3.0 Web by Desbravador** | PMS online para pequeno/médio porte com foco em agilidade, painéis gerenciais e integração com canais de venda |
| 5 | **Reservas Online** | Motor de reservas (booking engine) para o site do hotel, com pagamento online e integração com os PMS |
| 6 | **Gestão de Multipropriedade** | Gestão de propriedades compartilhadas por cotas de tempo (condomínio, proprietários, boletos) |
| 7 | **PMS Desbravador 4.1** | PMS modular para redes e grande porte: do front office à contabilidade, incluindo CRM e fidelidade |
| 8 | **Desbravador 3.1** | PMS de entrada para hotéis, hostels e pousadas; check-in ágil, reserva fácil |
| 9 | **Analyzer** | BI hoteleiro: centraliza dados do PMS em dashboards, indicadores e relatórios estratégicos |

Obs.: o **Easy Web** (do PDF) aparece hoje apenas como sistema legado integrável ao Reservas Online.
O channel manager não é produto separado — é funcionalidade embutida no Reservas Online / Light Web / 3.0 Web.
Nenhum produto Desbravador oferece **escala/RH** — será diferencial nosso.

## 2. Funcionalidades detalhadas por produto

### 2.1 PMS Desbravador 5.0 (grande porte/redes)
- **Cockpit**: visão geral personalizável, menu de favoritos, busca de funcionalidades
- **Multi**: multiempresa, multi-idioma, multipaís, multimoeda
- **Múltiplos caixas**: controle individual de caixa por operador, operações simultâneas
- **Orçamento de reservas**: orçamento para posterior confirmação; reservas previstas vs. efetivas com motivos de desistência
- **Consulta de disponibilidade**: visão infográfica com mapa de calor por tipo de apartamento, por diária
- **Mapa de reservas flexível**: registrar/modificar reservas, check-in/walk-in em poucos cliques, atalhos de teclado, transferência de reserva, alteração de período e status da UH
- **Agenda de governança**: serviços associados a pacotes ou in/out, troca de roupa de cama, turn down
- **Agenda de manutenção**: UHs e áreas comuns, com recorrência, setor e equipe de execução
- **Day Use** (entrada e saída no mesmo dia) e **Day Pass** (capacidade/consumo em áreas comuns)
- **Gestão de consumo de pensão**: refeições inclusas ou não na diária
- **Auditoria**: pendências (contas vencidas, check-outs não realizados, consumos não lançados)
- **Empréstimo de objetos**: saldo e previsão (cama extra, berço etc.)
- **Notificações + Logbook**: registro de ocorrências diárias compartilhado entre usuários/turnos

### 2.2 Light Web (referência principal — pequeno porte/pousadas)
- Gerência hoteleira: recepção, reservas, UHs, caixa, relatórios gerenciais/operacionais/estatísticos
- Reservas: disponibilidade e ocupação; integração com canais de venda online
- Gerência financeira: classificação de receitas e despesas
- Caixa: processamento e fechamento de contas
- Controle de estoque com leitura de XML de NF
- Emissão de documentos fiscais: NF-e, NFC-e, CF-e-SAT
- Revenue Manager: tarifas variáveis
- Painéis gerenciais interativos: metas e indicadores (vendas, reservas, cancelamentos, ocupação), acessíveis no celular
- Channel management embutido: envio de disponibilidade/tarifas e recebimento automático de reservas
- Modo offline para comandas abertas

### 2.3 iService (autoatendimento do hóspede)
- Check-in online pelo smartphone; check-out online com pagamento
- Serviço de quarto: pedidos de A&B direto à cozinha, restrições alimentares
- Cardápio do restaurante; múltiplos PDVs
- Informações do hotel (horários, regras da casa)
- Extrato da conta durante a estadia
- Pesquisa de satisfação durante a estadia
- Acesso por QR Code (sem instalar app), multi-idioma PT/EN/ES

### 2.4 3.0 Web by Desbravador
- Cloud, Revenue Manager, Reservas Online integradas
- Painéis gerenciais, metas e indicadores, acesso móvel
- Integração automática com canais de venda

### 2.5 Reservas Online (motor de reservas)
- Tarifas e disponibilidade em tempo real, sincronizado com o PMS
- Alteração e cancelamento pelo próprio hóspede
- Tarifas diferenciadas para empresas/agências; pacotes promocionais; upsell de adicionais
- Pagamento online: cartão de crédito e boleto; gateways seguros
- Identificação de hóspede recorrente
- Mobile, multi-idioma, monitoramento de acessos

### 2.6 Gestão de Multipropriedade (pouco aplicável; ideias de cobrança)
- Títulos a receber/pagar; boletos e CNAB; e-mails de lembrete de vencimento
- Controle de inadimplência; temporadas (super alta/alta/média/baixa)

### 2.7 PMS Desbravador 4.1
- Módulos: gerência hoteleira, estoque, financeiro, tarifador, POS, eventos & convenções, **CRM**, **fidelidade**, contabilidade, livros fiscais, condomínio

### 2.8 Desbravador 3.1
- Front desk completo, check-in ágil, reserva fácil, estoque, financeiro, POS, gestão fiscal, senha individual por usuário

### 2.9 Analyzer (BI)
- Dashboards em tempo real, histórico de longo prazo, geolocalização de origem dos hóspedes, relatórios estratégicos

## 3. Aplicável ao nosso CRM (pousada de 24 quartos)

### Reservas — ESSENCIAL
- Mapa de reservas visual (grade quartos × dias): criar/mover/redimensionar reserva, walk-in, troca de quarto
- Consulta de disponibilidade com mapa de calor por tipo de quarto/data
- Ciclo de estados: orçamento → pré-reserva → confirmada → hospedado → check-out (+ cancelada, no-show, com motivo)
- Fase 2: reservas de grupo/família (múltiplas UHs), day use

### Hospedagem / Front desk — ESSENCIAL
- Check-in/check-out ágeis; ficha do hóspede (FNRH)
- Conta do hóspede: consumos (frigobar, restaurante, serviços) na conta da UH
- Auditoria diária de pendências (check-outs atrasados, contas vencidas, consumos não lançados)
- Fase 2: check-in online / portal do hóspede via QR Code; empréstimo de objetos

### Tarifas / Revenue — ESSENCIAL (versão simples)
- Tarifas por tipo de quarto e por temporada/calendário
- Fase 2: tarifas por segmento (balcão, agência, empresa); revenue dinâmico por ocupação

### Financeiro / Pagamentos — ESSENCIAL
- Caixa com abertura/fechamento por operador
- Classificação de receitas e despesas
- Adiantamentos/sinal de reserva; estornos e devoluções
- Pagamentos: cartão, Pix, boleto (via gateway), múltiplas formas na mesma conta
- Fase 2: NF-e/NFC-e (intermediador), cobranças automáticas por e-mail/WhatsApp

### Governança / Manutenção — ESSENCIAL
- Status de limpeza por UH (sujo/limpo/inspecionado/bloqueado) integrado ao mapa
- Agenda de governança gerada por evento (check-out → faxina; estadia longa → troca de roupa a cada N dias)
- Agenda de manutenção com recorrência, responsável e bloqueio de UH

### Equipe / RH — diferencial nosso
- Usuários com login individual, perfis de permissão, caixa por operador
- Logbook: livro de ocorrências do dia compartilhado entre turnos
- Atribuição de tarefas de limpeza/manutenção a pessoas
- Escala de trabalho formal (Desbravador não oferece)

### Relatórios / BI — ESSENCIAL (versão enxuta)
- Painel: taxa de ocupação, diária média (ADR), RevPAR, receita, reservas e cancelamentos
- Relatórios do dia: chegadas, saídas, hóspedes na casa, mapa de limpeza
- Fase 2: origem dos hóspedes, histórico longo

### CRM de hóspedes / Canais — 
- ESSENCIAL: cadastro único do hóspede com histórico de estadias, preferências, hóspede recorrente
- ESSENCIAL (fase 1 manual, fase 2 API): integração com OTAs (Booking/Airbnb) — começar com lançamento manual + iCal
- Fase 2: motor de reservas próprio com pagamento online; pesquisa de satisfação pós-estadia; fidelidade

### Fora de escopo
- Multiempresa/multimoeda, eventos & convenções, contabilidade gerencial/livros fiscais, multipropriedade, POS completo de restaurante, tarifador telefônico

## 4. Priorização

- **MVP (fase 1)**: mapa de reservas + disponibilidade; ciclo completo da reserva; check-in/out + conta do hóspede; tarifas por temporada; caixa por operador + receitas/despesas; adiantamentos e estornos; status de limpeza + tarefas de governança; manutenção com bloqueio de UH; cadastro/histórico de hóspedes; logbook; painel de ocupação/ADR/receita; usuários com permissões.
- **Fase 2**: channel manager/OTAs via API; motor de reservas com Pix/cartão online; portal do hóspede (QR Code); pesquisa de satisfação; revenue dinâmico; NF-e; cobranças automáticas; BI histórico; fidelidade.

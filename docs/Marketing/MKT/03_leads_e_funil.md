# Leads e Funil Comercial — como ler e atualizar

> Snapshot em **07/09/2026**. Dado bruto no arquivo **`leads_funil.csv`** (mesma pasta).
> ⚠️ O CSV tem dados pessoais de clientes (LGPD) — **não versionar no git** e não
> compartilhar fora do necessário. Está no `.gitignore` desta pasta.

## Etapas do funil (Comercial → Kanban)
| Ordem | Etapa | O que significa |
|---|---|---|
| 10 | **Novo lead** | Entrou (site/LP), ainda sem contato feito |
| 20 | **Contato feito** | Já falamos (WhatsApp/e-mail) |
| 30 | **Cotação enviada** | Proposta/valores enviados |
| 40 | **Negociação** | Ajustando datas/valores |
| 50 | **Ganho** | Vira reserva (conversão) |
| 60 | **Perdido** | Com motivo registrado |

Regras do CRM: só vira **Ganho** por conversão real; **Perdido** exige motivo; SLA de
resposta (24h/48h) monitorado na Auditoria.

## Retrato deste snapshot (19 leads)
- **Todos em "Novo lead"** — ou seja, ninguém foi trabalhado ainda. **Ação nº 1:
  fazer o primeiro contato** (a lista está esfriando por hora).
- **Origem:** 100% do **site/LP Fundador**, quase todos vindos do **Instagram** (`ig`).
- **Interesse:** hospedagem. **Região:** predominância de **DDD 49** (Oeste de SC) —
  público local/regional, coerente com a pousada em Itá.
- **Sem cotação, sem ganho, sem perdido** ainda → conversão real = 0 (esperado nesta
  fase de captação pré-abertura).

## O que fazer com esses leads (fundadores)
1. **Mensagem de boas-vindas no WhatsApp** (tom da marca — ver `02_guia_de_marca.md`):
   confirmar que entraram na lista de fundadores e que serão os primeiros a saber.
2. **Manter aquecido** até definir a condição de fundador e a data de abertura de
   reservas — sequência curta (2–3 toques) por WhatsApp/e-mail.
3. **Segmentar** por perfil quando houver dados (casal x família; interesse em cabana).
4. Registrar cada contato no CRM (empurra a etapa: Novo lead → Contato feito).

## Como atualizar este CSV (exportar de novo)
Rodar no servidor de produção (não é deploy):
```bash
railway ssh "python manage.py shell -c \"
import csv,sys
from apps.comercial.models import Oportunidade
w=csv.writer(sys.stdout)
w.writerow(['criado_em','nome','telefone','email','etapa','status','origem','tipo_interesse','utm_source','utm_campaign'])
for o in Oportunidade.objects.select_related('pessoa','etapa').order_by('-criado_em'):
    r=o.origem_rastreio or {}
    w.writerow([o.criado_em.strftime('%d/%m/%Y %H:%M'),o.pessoa.nome,o.pessoa.telefone,o.pessoa.email,o.etapa.nome if o.etapa else '',o.status,o.origem,o.tipo_interesse,r.get('utm_source',''),r.get('utm_campaign','')])
\"" > docs/Marketing/MKT/leads_funil.csv
```
> Também dá para exportar pela tela de Relatórios/Auditoria do CRM (CSV).

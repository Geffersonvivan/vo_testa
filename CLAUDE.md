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
- Próximo: módulo Núcleo completo (cadastros, financeiro/caixa) — ver §8 da especificação.
- Perguntas de negócio em aberto: §9 da especificação (parâmetros, não bloqueiam).

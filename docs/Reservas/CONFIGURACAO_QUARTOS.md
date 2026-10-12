# Configuração de Quartos e Estoque de Colchões — Pousada Vô Testa

## Objetivo

Implementar no PMS (Django) o cadastro de configuração de camas das 24 unidades da pousada e o controle de um **estoque global de colchões**. O estoque limita quantas camas podem ser montadas por noite.

Antes de criar qualquer coisa, inspecione o projeto existente: se já houver models de quarto (`Room`, `Quarto`, `Unidade` etc.) ou de reserva, **estenda-os** em vez de criar duplicados. Os nomes abaixo são sugestões. Siga as convenções de nomenclatura, idioma e estrutura de apps já usadas no repositório.

---

## Regras de negócio

1. **Todos os colchões são de solteiro.**
2. **Cama de casal = 2 camas de solteiro unidas = 2 colchões.** As **35 posições de casal
   = 70 colchões de solteiro FIXOS**: cada posição pode virar **1 casal OU 2 solteiros** —
   a **montagem muda, a quantidade (2 por posição) não**.
3. Cada pessoa em cama consome **1 colchão**, seja em solteiro ou em casal.
4. **Sofá-cama não consome colchão.** Comporta **1 adulto** ou **até 2 crianças com 15 anos ou menos**.
5. **Cada quarto tem suas camas FIXAS** — a base de **2 colchões por posição de casal** é
   sempre daquele quarto e **nunca entra em disputa**. **Só os 10 colchões EXTRAS** são um
   **recurso compartilhado** (pool global), usados quando um quarto é montado com **mais
   solteiros do que sua base**. O estoque de extras é editável (não hardcoded).
6. Restrições por quarto para uma configuração com `c` casais e `s` solteiros:
   - `c <= casais_max`
   - `2*c + s <= camas_solteiro`
   - **colchões EXTRA deste quarto** = `max(0, (2*c + s) − 2*casais_max)` (o que passa da base fixa)
7. Restrição global, para cada noite: a soma dos **colchões EXTRA** de todas as reservas ativas
   naquela noite deve ser `<= estoque de extras` (10). A **base fixa de cada quarto nunca entra
   nessa conta** — está sempre garantida.

### Números de referência

| Indicador | Valor |
|---|---|
| Unidades | 24 |
| Camas de solteiro (estruturas físicas) | 112 |
| Casais possíveis | 35 |
| **Camas fixas dos quartos (35 casais ou 70 solteiros)** | 70 |
| Vagas extras de solteiro demandadas | 42 |
| **Colchões extra (pool compartilhado, editável)** | 10 |
| Vagas extras cobertas pelo pool | 10 (as outras 32 disputam o pool por noite) |
| Sofás-cama | 13 |

Capacidade da pousada:

- Base, só com as camas fixas: 70 em cama + 13 sofás = **83 adultos**.
- Com os 10 colchões extra: 80 em cama + 13 sofás = **93 adultos**, ou 80 adultos + 26 crianças.
- Teto físico (se um dia houvesse colchão para as 112 camas): **125 adultos**.

---

## Dados das unidades (seed)

Layout:

- `separado`: quarto e cozinha em ambientes separados.
- `conjugado`: quarto e cozinha no mesmo ambiente.
- `meia_divisao`: quarto e cozinha separados por meia parede.

| Unidade | Layout | camas_solteiro | casais_max | sofa_cama | Perfil |
|---|---|---|---|---|---|
| 01 | separado | 6 | 2 | sim | 6 camas |
| 02 | separado | 6 | 2 | sim | 6 camas |
| 03 | meia_divisao | 3 | 1 | não | 3 camas |
| 04 | conjugado | 3 | 1 | não | 3 camas |
| 05 | conjugado | 3 | 1 | não | 3 camas |
| 06 | conjugado | 3 | 1 | não | 3 camas |
| 07 | conjugado | 3 | 1 | não | 3 camas |
| 08 | conjugado | 3 | 1 | não | 3 camas |
| 09 | separado | 4 | 1 | sim | 4 camas |
| 10 | separado | 4 | 1 | não | 4 camas |
| 11 | conjugado | 2 | 1 | não | 2 camas |
| 12 | conjugado | 2 | 1 | não | 2 camas |
| 13 | conjugado | 3 | 1 | não | 3 camas |
| 14 | conjugado | 3 | 1 | não | 3 camas |
| 15 | separado | 4 | 1 | sim | 4 camas |
| 16 | separado | 7 | 2 | sim | 7 camas |
| 17 | separado | 7 | 2 | sim | 7 camas |
| 18 | separado | 7 | 2 | sim | 7 camas |
| 19 | separado | 6 | 2 | sim | 6 camas |
| 20 | separado | 6 | 2 | sim | 6 camas |
| 21 | separado | 6 | 2 | sim | 6 camas |
| 22 | separado | 7 | 2 | sim | 7 camas |
| 23 | separado | 7 | 2 | sim | 7 camas |
| 24 | separado | 7 | 2 | sim | 7 camas |

### Configurações de referência por perfil

Estas configurações são apenas presets para a interface. A validação usa a regra geral da seção de regras de negócio, então combinações intermediárias (ex.: 2 casais + 1 solteiro) também são válidas.

| Perfil | Base (só casais) | Completa | Só solteiros |
|---|---|---|---|
| 2 camas | 1 casal (2 colchões) | — | 2 solteiros (2) |
| 3 camas | 1 casal (2) | 1 casal + 1 solteiro na sala (3) | 3 solteiros (3) |
| 4 camas | 1 casal (2) | 1 casal + 2 solteiros na sala (4) | 4 solteiros (4) |
| 6 camas | 2 casais (4) | 2 casais + 2 solteiros na sala (6) | 6 solteiros (6) |
| 7 camas | 2 casais (4) | 2 casais + 3 solteiros, 1 no quarto e 2 na sala (7) | 7 solteiros (7) |

### Fixture sugerida (JSON)

```json
[
  {"numero": "01", "layout": "separado",     "camas_solteiro": 6, "casais_max": 2, "sofa_cama": true},
  {"numero": "02", "layout": "separado",     "camas_solteiro": 6, "casais_max": 2, "sofa_cama": true},
  {"numero": "03", "layout": "meia_divisao", "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "04", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "05", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "06", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "07", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "08", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "09", "layout": "separado",     "camas_solteiro": 4, "casais_max": 1, "sofa_cama": true},
  {"numero": "10", "layout": "separado",     "camas_solteiro": 4, "casais_max": 1, "sofa_cama": false},
  {"numero": "11", "layout": "conjugado",    "camas_solteiro": 2, "casais_max": 1, "sofa_cama": false},
  {"numero": "12", "layout": "conjugado",    "camas_solteiro": 2, "casais_max": 1, "sofa_cama": false},
  {"numero": "13", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "14", "layout": "conjugado",    "camas_solteiro": 3, "casais_max": 1, "sofa_cama": false},
  {"numero": "15", "layout": "separado",     "camas_solteiro": 4, "casais_max": 1, "sofa_cama": true},
  {"numero": "16", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true},
  {"numero": "17", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true},
  {"numero": "18", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true},
  {"numero": "19", "layout": "separado",     "camas_solteiro": 6, "casais_max": 2, "sofa_cama": true},
  {"numero": "20", "layout": "separado",     "camas_solteiro": 6, "casais_max": 2, "sofa_cama": true},
  {"numero": "21", "layout": "separado",     "camas_solteiro": 6, "casais_max": 2, "sofa_cama": true},
  {"numero": "22", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true},
  {"numero": "23", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true},
  {"numero": "24", "layout": "separado",     "camas_solteiro": 7, "casais_max": 2, "sofa_cama": true}
]
```

Carregue via data migration ou management command idempotente (`update_or_create` por `numero`).

---

## Modelagem sugerida

Adapte aos models existentes.

**Quarto / Unidade** (estender, se já existir):

- `numero` (CharField, único)
- `layout` (choices: `separado`, `conjugado`, `meia_divisao`)
- `camas_solteiro` (PositiveSmallIntegerField)
- `casais_max` (PositiveSmallIntegerField)
- `sofa_cama` (BooleanField)
- Propriedades derivadas, que não devem ser persistidas:
  - `colchoes_base = 2 * casais_max`
  - `vagas_extras = camas_solteiro - 2 * casais_max`
  - `capacidade_max_cama = camas_solteiro`

**Estoque de colchões**:

- Configuração global com `quantidade` (default 80). Pode ser um model singleton, um model `RecursoInventario` genérico ou um setting editável no admin, conforme o padrão do projeto.
- Se houver chance de variação ao longo do tempo (compra de colchões), prefira registro com `vigente_desde` (data) para que o cálculo por noite use a quantidade vigente naquela data.

**Configuração da reserva** (campos na reserva, ou na relação reserva↔quarto se uma reserva puder ter vários quartos):

- `casais` (PositiveSmallIntegerField)
- `solteiros` (PositiveSmallIntegerField)
- `usa_sofa_cama` (BooleanField)
- `colchoes_consumidos` (derivado: `2 * casais + solteiros`)
- Hóspedes com idade ou data de nascimento, ou ao menos contagem de adultos e crianças ≤ 15 anos, para validar o sofá.

---

## Validações

Implemente as validações em camada de serviço/domínio, reutilizável por admin, API e formulários, e não só no `clean()` do form.

1. `casais <= quarto.casais_max`
2. `2 * casais + solteiros <= quarto.camas_solteiro`
3. `usa_sofa_cama` só se `quarto.sofa_cama`
4. Ocupação do sofá: 1 adulto **ou** até 2 crianças ≤ 15 anos.
5. Total de hóspedes ≤ `2 * casais + solteiros` + capacidade do sofá em uso.
6. **Estoque por noite**: para cada noite `d` da estadia (check-in inclusive, check-out exclusivo), `soma(colchoes_consumidos das reservas ativas em d) + colchoes desta reserva <= estoque vigente em d`.
   - Considere apenas reservas em status que ocupam o quarto (confirmada, check-in). Exclua canceladas e no-show, conforme os status do projeto.
   - Ao editar uma reserva, exclua ela própria da soma.
   - Proteja contra condição de corrida com `select_for_update` / transação atômica no momento de confirmar.
7. A mensagem de erro deve indicar a(s) noite(s) sem colchão e quantos faltam.

---

## Funcionalidades de interface e relatórios

- No formulário de reserva, mostrar os presets do perfil do quarto e o campo livre de casais/solteiros.
- Exibir **colchões livres por noite** no período selecionado.
- **Lista diária de montagem** para a governança: quarto, nº de casais, nº de solteiros, sofá aberto (sim/não).
- **Painel de ocupação de colchões** por noite (usados / estoque).
- Admin: estoque de colchões editável e quartos editáveis.

---

## Testes de aceite (implementar como testes automatizados)

1. Seed carregado → totais: 24 quartos, 112 camas, 35 casais, 70 colchões base, 42 vagas extras, 13 sofás-cama.
2. Todos os 24 quartos reservados na mesma noite em configuração base → consumo 70, aceito.
3. Após o cenário 2, adicionar 10 solteiros extras distribuídos em quartos com vaga → aceito (consumo 80). O 11º solteiro extra → recusado, com mensagem indicando a noite.
4. Quarto 11: `1 casal + 1 solteiro` → recusado (excede camas). `2 solteiros` → aceito.
5. Quarto 03: `2 casais` → recusado (`casais_max = 1`).
6. Quarto 10: `usa_sofa_cama = true` → recusado (sem sofá).
7. Quarto 22 com 3 colchões livres: `2 casais + 3 solteiros` + sofá com 2 crianças de 10 anos → aceito (9 hóspedes).
8. Sofá com 2 adultos → recusado. Sofá com 1 adulto → aceito. Sofá com 1 criança de 16 anos e 1 de 8 → recusado.
9. Estadia de 3 noites em que só a 2ª noite está sem colchão → recusada, apontando apenas a 2ª noite.
10. Reserva cancelada deixa de consumir colchões.
11. Editar uma reserva existente sem mudar a configuração não conta o próprio consumo em dobro.
12. Alterar o pool de extras para 42 → todas as vagas extras de solteiro ficam disponíveis.

---

## Resolvido

- **Configuração "só solteiros":** toda posição de casal pode ser montada como **1 casal
  OU 2 solteiros** (mesma quantidade de colchões — ver regra 2). Não há casais fixos; o que
  um quarto monta **além das suas camas fixas** sai dos **10 colchões extra** compartilhados.

## Fora de escopo / em aberto

- Integração com channel manager (OTAs): a capacidade anunciada por quarto deve respeitar o pool de extras. Definir depois se o sistema publica a capacidade base ou a máxima.

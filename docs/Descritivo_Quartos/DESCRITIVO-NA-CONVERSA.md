# Descritivo dos quartos dentro da conversa do lead

Para o Claude Code, no repositório do CRM Vô Testa (Django).

Base: `uploads/descritivo-quartos-vo-testa.md` (29/09/2026, Gefferson Vivan),
copiado para esta pasta como `descritivo-quartos-vo-testa.md`.

---

## O pedido

O vendedor precisa ver, **dentro da conversa de cada lead**, o descritivo de cada
quarto: acomodação, capacidade, equipamentos, cozinha, para quem é indicado. O
descritivo tem uma ficha por quarto, com os mesmos campos na mesma ordem, para
consultar e comparar rápido.

A regra que mais importa no descritivo:

> O sofá-cama acomoda 1 adulto **ou** 2 crianças até 15 anos. Nunca venda a
> capacidade com crianças como se fosse de adultos.

Essa regra tem que estar no sistema, não na memória do vendedor.

---

## Antes de tudo: o descritivo discorda do cadastro atual

O cadastro de unidades que o CRM usa hoje (camas, capacidade, tipo) **não bate**
com o descritivo:

| | Descritivo | Cadastro atual |
|---|---|---|
| Cabana Hobbit | quartos 22, 23, 24 | 20, 23, 24 |
| Cabana Intermediária | quartos 16 a 21 | inclui o 22 |
| Capacidade Hobbit | 6 adultos, ou 5 + 2 crianças | 7 adultos |
| Colchão extra no 01 e 02 | não cabe | 2 colchões |
| Nomes temáticos | "Oficina do Relojoeiro", "Torre do Astrônomo"… | não existem |

Se o vendedor lê o descritivo e o sistema vende pelo cadastro, os dois se
contradizem na frente do cliente.

**O descritivo passa a ser a fonte única.** Cada quarto vira um registro no
banco, e texto, capacidade e disponibilidade saem dele. Registre cada
divergência encontrada no `ROTEIRO.md` e **pergunte antes de sobrescrever** o
cadastro em produção — há reservas apontando para essas unidades.

### Pendências do descritivo que bloqueiam

Estão no fim do arquivo. Não invente valor para nenhuma delas:

- Sofás-cama: o total é 11, mas a lista soma 13 (01, 02, 09, 15, 16 a 24).
  Faltam definir quais 2 quartos não têm.
- Quais quartos padrão (03–08, 10–14) comportam colchão extra.
- Nome temático dos quartos 21 e 23.
- Nome definitivo das duas categorias "Intermediário".
- Capacidade total recalculada: 100 a 111 adultos (antes eram 118).

Enquanto estiverem em aberto, o campo fica marcado como **não confirmado** (ver
item 3 abaixo) — nunca preenchido com palpite.

---

## Modelo

Estenda o model de unidade habitacional existente, não crie um paralelo.

```python
class FichaQuarto(models.Model):
    """Descritivo comercial de uma unidade. Uma por quarto."""
    uh = models.OneToOneField("reservas.UnidadeHabitacional", on_delete=models.CASCADE,
                              related_name="ficha")
    nome_tematico = models.CharField(max_length=80, blank=True)   # "Oficina do Relojoeiro"
    resumo = models.CharField(max_length=200)                     # a frase abaixo do título
    categoria = models.CharField(max_length=60)

    # Capacidade separada, nunca um número só
    max_adultos = models.PositiveSmallIntegerField()
    max_adultos_com_criancas = models.PositiveSmallIntegerField()
    max_criancas = models.PositiveSmallIntegerField(default=0)    # via sofá-cama
    idade_limite_crianca = models.PositiveSmallIntegerField(default=15)

    acomodacao = models.TextField()          # "Quarto 1: 1 cama de casal · …"
    colchao_extra = models.CharField(max_length=120, blank=True)
    equipamentos = models.TextField()
    cozinha = models.TextField()
    indicado_para = models.CharField(max_length=160)

    # Campos que o descritivo ainda marca como "a levantar"
    vista = models.CharField(max_length=120, blank=True)
    andar_acesso = models.CharField(max_length=120, blank=True)
    metragem = models.CharField(max_length=40, blank=True)
    banheiro = models.CharField(max_length=160, blank=True)
    area_externa = models.CharField(max_length=160, blank=True)
    ar_condicionado = models.CharField(max_length=120, blank=True)
    acessibilidade = models.CharField(max_length=160, blank=True)
    historia_e_venda = models.TextField(blank=True)

    pontos_atencao = models.TextField(blank=True)   # "Colchão extra não cabe", "sem fogão"
    equivalentes = models.ManyToManyField("self", blank=True, symmetrical=True)

    confirmados = models.JSONField(default=list)    # quais campos já foram conferidos
    atualizado_em = models.DateTimeField(auto_now=True)
```

**Vazio não é "não tem".** Campo em branco significa *não levantado*. A tela
distingue os dois (item 3).

Migração de dados: carregue as 24 fichas a partir do descritivo. Campos "A
levantar" entram em branco; "A conferir" entram em branco e fora de
`confirmados`.

---

## Onde aparece: painel lateral na ficha do lead

Ao abrir o lead no funil comercial, um painel fixo à direita mostra os quartos.
Não os 24: **só os que servem para aquele pedido**.

### 1. Filtro por composição e datas

O lead guarda **adultos e crianças separados**, não "pax":

```python
class Lead(models.Model):
    ...
    adultos = models.PositiveSmallIntegerField(default=2)
    criancas = models.PositiveSmallIntegerField(default=0)
    idades_criancas = models.JSONField(default=list, blank=True)
    checkin = models.DateField(null=True, blank=True)
    checkout = models.DateField(null=True, blank=True)
```

Um quarto só aparece se comportar a composição exata:

```python
def comporta(ficha, adultos, criancas, idades):
    if any(i > ficha.idade_limite_crianca for i in idades):
        # criança acima do limite conta como adulto
        extras = sum(1 for i in idades if i > ficha.idade_limite_crianca)
        adultos, criancas = adultos + extras, criancas - extras
    if criancas == 0:
        return adultos <= ficha.max_adultos
    return (adultos <= ficha.max_adultos_com_criancas
            and criancas <= ficha.max_criancas)
```

Exemplos com o descritivo:
- 3 adultos + 2 crianças → aparece o 09 e o 15; o 01 também (4 + 2)
- 5 adultos → aparece o 01, o 02 e as cabanas; o 09 não
- 2 adultos + 1 criança de 16 anos → conta como 3 adultos

Com datas preenchidas, tira os ocupados no período. Sem datas, mostra todos os
que comportam, com o aviso "sem datas — disponibilidade não conferida".

### 2. Cartão compacto por quarto

Nome temático, número e categoria · capacidade no formato do descritivo ("5
adultos, ou 4 adultos + 2 crianças até 15 anos") · preço do período, se houver
datas · um selo quando houver ponto de atenção.

Clicar abre a ficha completa no próprio painel, sem sair da conversa.

### 3. "A levantar" aparece como lacuna

Campo em branco ou fora de `confirmados` aparece em cinza, com o texto **"não
confirmado — não prometa"**. O vendedor precisa saber o que **não** pode dizer
tanto quanto o que pode.

Cada lacuna é uma tarefa: a tela de cadastro lista quartos com campos pendentes
e quantos faltam, para quem cuida do descritivo ir fechando.

### 4. Pontos de atenção no topo

O que evita reclamação no check-in fica acima de tudo, em destaque de alerta:

- "Colchão extra não cabe — espaço apertado" (01, 02)
- "Sem fogão" (03 a 15)
- Escada, barulho, vista parcial — quando levantados

Não pode ficar no pé da tabela.

### 5. "Enviar ao cliente"

Gera um texto curto e bem escrito para colar no WhatsApp: nome do quarto,
acomodação, capacidade para a composição do lead, valor do período. **Sem**
campos internos, **sem** pontos de atenção e **sem** nada "não confirmado".
Quando houver fotos, vão junto.

Exemplo:

> **Torre do Astrônomo** — cabana com dois quartos de casal e cozinha completa.
> Para vocês 4 adultos + 2 crianças: duas camas de casal, e as crianças no
> sofá-cama. Tem fogão, geladeira dupla, louças e utensílios. De 12 a 15/09,
> R$ 2.480,00.

### 6. Comparar lado a lado

Selecionar dois ou três quartos abre uma tabela de colunas: capacidade,
colchões extras, equipamentos, cozinha, preço. Responde em segundos o "qual a
diferença entre a cabana e a hobbit?".

### 7. Alternativa quando o escolhido está ocupado

Usa `equivalentes`. Se o 17 está ocupado no período, o cartão dele aparece
esmaecido com "ocupado · veja o 16 ou o 18", que são idênticos.

O campo está nas pendências do descritivo; enquanto vazio, sugira por mesma
categoria e mesma capacidade.

### 8. Histórico do que foi oferecido

Cada "enviar ao cliente" vira evento na linha do tempo do lead: "Ofereceu
Torre do Astrônomo · R$ 2.480,00 · 12/09 · gvivan". Quando outro vendedor pegar
a conversa, não oferece de novo o que o cliente já recusou.

---

## Ordem de implementação

1. **Model `FichaQuarto` + migração de dados** das 24 fichas. Divergências com
   o cadastro atual vão para o `ROTEIRO.md`, e pergunte antes de sobrescrever.
2. **Adultos e crianças separados no lead** + função `comporta()` com testes.
3. **Painel lateral com filtro** (itens 1 e 2). É o que o vendedor usa todo dia.
4. **Lacunas em cinza e pontos de atenção** (itens 3 e 4). Custam pouco e
   evitam promessa errada.
5. **Enviar ao cliente, comparar, alternativas** (itens 5 a 7).
6. **Histórico do oferecido** (item 8).
7. **Tela de pendências do cadastro**: quais quartos têm campo por levantar.

---

## Regras

- **Capacidade nunca é um número só.** Sempre adultos e adultos + crianças.
- **Não invente dado.** Tudo que o descritivo marca como "a levantar" ou "a
  conferir" fica em branco e aparece como não confirmado.
- **O texto enviado ao cliente não leva nada não confirmado.**
- **Uma fonte.** Capacidade do motor de reservas, do site e da ficha do lead
  vêm da mesma `FichaQuarto`. Se hoje há capacidade em outro lugar, passe a ler
  daqui e registre no roteiro.
- **Layout do CRM:** tokens do `app.css`, painel no padrão das gavetas
  existentes, sem cor nova.

## Testes

- `comporta()` com as composições dos exemplos, incluindo criança acima de 15
- Quarto ocupado no período não aparece como disponível
- Texto de envio não contém campo vazio, "a levantar" nem ponto de atenção
- Campo fora de `confirmados` renderiza como "não confirmado"
- Evento de oferta gravado na linha do tempo do lead

## Dúvida em aberto

**Onde a conversa acontece?** Se o atendimento é pelo WhatsApp e o CRM só
registra o lead, o painel vive na ficha do lead no funil (é o que este
documento assume). Se a ideia é trazer a conversa para dentro do CRM, pare e
pergunte antes do passo 3.

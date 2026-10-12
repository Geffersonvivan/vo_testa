# Parâmetros dos Quartos para o CRM — fonte do seed

> Consolidação de `Manual_de_Vendas_Vo_Testa.pdf` + plantas (`Projeto_Pousada/`) +
> decisões confirmadas pelo dono (06/10/2026). Vira o comando de seed que carrega os 24
> quartos, 8 categorias, 4 temporadas e o motor de preço. **CRM em beta** → pode remodelar
> os tipos/quartos livremente (sem migrar reserva).
>
> ⏳ Pendências do dono (não bloqueiam o resto): (1) colchão extra por quarto, (2) berço,
> (3) metragem dos 13 quartos de corredor (03-15).

## 1. Categorias × quartos × capacidade × preço (diária 2 pax, com café/taxas — FINAL)

| Categoria | Quartos | Até (ad.) | Baixa | Média | Alta | Feriado | P. adic. | Metragem |
|---|---|---|---|---|---|---|---|---|
| Cabana Recepção | 01, 02 | 5 | 560 | 630 | 710 | 860 | 250 | **67,03 m²** |
| Corredor Engenhoca | 03-08 | 3* | 420 | 470 | 520 | 640 | 190 | ⏳ a confirmar |
| Engenhoca Mirante | 09 | 4 | 560 | 630 | 710 | 860 | 250 | ⏳ a confirmar |
| Corredor Histórias | 10-14 | 3* | 360 | 400 | 440 | 550 | 160 | ⏳ a confirmar |
| Histórias Mirante | 15 | 4 | 480 | 540 | 600 | 730 | 215 | ⏳ a confirmar |
| Cabana Superior | 16-18 | 7 | 780 | 890 | 1010 | 1220 | 350 | **86,74 m²** |
| Cabana Central | 19-21 | 7 | 680 | 770 | 870 | 1050 | 300 | **64,08 m²** |
| Cabana Hobbits | 22-24 | 6 | 900 | 1040 | 1170 | 1440 | 400 | **62,04 m²** |

\* **03-08 e 10-14: capar em 2 adultos por enquanto** (não vender 3ª pessoa) até o dono
confirmar o colchão extra por quarto. A tabela diz "até 3", mas o manual manda não vender a
3ª pessoa enquanto o colchão está "?". Alternativa a oferecer: 09 ou 15.

## 2. Motor de preço (determinístico — "não some nada à mão")
- **Base = diária de 2 pessoas** da categoria/temporada.
- **Pessoa adicional:** `preço(N adultos) = base + (N − 2) × P.adic`, até o máximo da categoria.
- **Hóspede sozinho:** paga **70%** da diária de 2 pessoas (confirmado — convenção single).
- **Criança:** ≤5 anos **grátis** · 6-15 anos **metade** da pessoa adicional · 16+ **adulto**.
- **Sofá-cama** acomoda **1 adulto ou 2 crianças** (≤15). Colchão extra = capacidade a definir
  por quarto (pendência 1).
- **Tarifa não-reembolsável:** **−12%** sobre a tabela, paga na reserva, sem cancelamento.
  Réveillon e Carnaval **só** nessa tarifa.

## 3. Temporada por DATA (preço é por NOITE — estadia pode misturar)
Precedência: **Feriado → Alta → (dia da semana)**.
- **FERIADO:** blocos abaixo (tarifa feriado em TODAS as noites do bloco).
- **ALTA:** 01/01–14/02 · 10/07–25/07 · 15/12–31/12.
- **MÉDIA:** toda **sexta e sábado** do restante do ano.
- **BAIXA:** **domingo a quinta** do restante do ano.

**Feriados 2027:** Réveillon 29/12/26–02/01 · Carnaval 06/02–09/02 · Paixão de Cristo
25/03–27/03 · Tiradentes 20/04 · Dia do Trabalho 30/04–01/05 · Corpus Christi 26/05–29/05 ·
Independência 04/09–06/09 · N. Sra. Aparecida 09/10–11/10 · Finados 30/10–01/11 ·
Proclamação da República 12/11–14/11 · Consciência Negra 19/11–20/11 · Natal 24/12–25/12 ·
Réveillon 2028 29/12–31/12.

## 4. Regras de reserva
- **Check-in** 14h · **check-out** 12h · **café** buffet 8h-10h (incluso).
- **Pets:** não aceita (nenhuma unidade).
- **Estadia mínima:** 1 noite (normal); **Réveillon e Carnaval 3 noites**; feriados prolongados
  e fins de semana de alta **2 noites** (sex a dom).
- **Cancelamento (tarifa normal):** grátis até **15 dias** antes (cabanas) / **7 dias** (corredor).
  Não-reembolsável: sem devolução.
- **PCD:** quartos **04 e 14** adaptados — **garantidos por número** na reserva (exceção à regra
  de "não prometer quarto específico").
- **Quarto específico pedido:** registra como **preferência**, não garante (salvo 04/14).
  Alternativas por categoria na pág. 6 do manual.

## 5. Day use
- **R$ 180/pessoa**, sem almoço. Vagas por ocupação: lotada **4** · ~50% **8** · ~30% ou menos
  **10**. Hóspede hospedado tem prioridade. **Nunca vender sem conferir ocupação no sistema.**

## 6. Amenidades (manual pág. 3)
- **Em TODOS:** banheiro privativo, ar-condicionado, cama casal pillow-top, enxoval Teka, Wi-Fi,
  TV 50" smart, micro-ondas, cozinha com fogão. **Cofre: NÃO tem** (confirmado).
- **Varia por quarto:** ambientes (1 ou 2 quartos), sofá-cama, colchão extra, geladeira
  (frigobar/dupla), fogão (1 ou 2 bocas — 2 bocas em 01,02 e 16-24), piso aquecido, **lavabo**
  (19,20,21), sacada, passarela (22-24), **PCD (04,14)**. Detalhe completo na tabela da pág. 3.
- **Piscina:** 10h-22h.

## 7. Mapeamento pro modelo do CRM
- **8 `TipoUH`** = as 8 categorias (preço por temporada no nível do tipo — é uniforme na
  categoria; só usar `TarifaUnidade` se algum quarto fugir).
- **24 `UH`** apontando pro tipo + descritivo (nome temático, vista, destaque, corredor
  sup/inf, acessibilidade PCD, lavabo, sacada, passarela, metragem).
- **Temporada:** classificação Baixa/Média/Alta/Feriado + a **regra de data** (§3) no cálculo
  por noite.
- **Pessoa adicional / criança / single 70% / não-reembolsável −12%:** motor de tarifa.

## 8. Pendências (preencher e rodar o seed)
1. **Colchão extra por quarto** (03-08, 10-14): cabe 3ª pessoa? → libera "até 3".
2. **Berço:** tem? em quais quartos (será um que caiba cama extra)?
3. **Metragem dos corredores** 03-15 (não está nas plantas da pasta; falta a planta do
   corredor ou os m²).
4. ~~Hóspede sozinho~~ → **70% (confirmado)**.

**Secundários (outros módulos, não travam o quarto):** preço de bebidas/lanches (Loja/
Restaurante), passeio de barco/pesca/caiaque, formas de pagamento/parcelamento (casa com a
negociação Safrapay), horário do bar.

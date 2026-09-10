# MKT — Base de conhecimento para Comercial & Marketing

Documentos de referência da **Pousada Vô Testa** para usar no **Projeto do Claude**
(claude.ai) que acompanha as ações comerciais e de marketing.

## O que subir no "Contexto" do Projeto
| Arquivo | Conteúdo |
|---|---|
| `01_servicos_e_precos.md` | Tipos de quarto, capacidade, preços por temporada, day use, eventos |
| `02_guia_de_marca.md` | História, tom de voz, paleta, tipografia, público |
| `03_leads_e_funil.md` | Etapas do funil, leitura do snapshot, como reexportar |
| `04_lp_fundador.md` | Estratégia e copy oficial da LP de captação |
| `05_calendario.md` | Feriados 2026, faixas de temporada, datas de campanha |
| `leads_funil.csv` | Dados brutos dos leads (**LGPD — não versionar**) |

> Suba os `.md` como Contexto do Projeto. O `leads_funil.csv` você atualiza e sobe
> manualmente de tempos em tempos (ele muda; os `.md` são mais estáveis).

## Manutenção
- Preços mudaram no CRM? Atualize `01_servicos_e_precos.md`.
- Novos leads? Reexporte o CSV (comando em `03_leads_e_funil.md`) e suba de novo.
- Definiu a condição de fundador / data de abertura? Atualize `04_` e `05_`.

## Aviso LGPD
`leads_funil.csv` contém nome, telefone e e-mail de pessoas reais. Não commitar, não
subir em local público, usar só para a operação comercial da pousada.

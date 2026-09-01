# Dicionário de dados

Cada campo da solução, sua origem e o tratamento aplicado.

---

## Fonte 1 — SIH/SUS (relacional)

Sistema de Informações Hospitalares do SUS. Uma linha por **AIH**
(Autorização de Internação Hospitalar). Extração: `src/ingestao/ingest_sih.py`.

| Campo original | Campo do projeto | Tipo | Descrição |
|---|---|---|---|
| `N_AIH` | `nu_aih` | texto | Número da AIH — chave natural da internação |
| `ANO_CMPT` | `ano_competencia` | inteiro | Ano da competência |
| `MES_CMPT` | `mes_competencia` | inteiro | Mês da competência |
| `UF_ZI` | `co_uf_gestor` | texto | Código IBGE da UF gestora |
| `MUNIC_RES` | `co_municipio_residencia` | texto | Município de residência do paciente |
| `MUNIC_MOV` | `co_municipio_internacao` | texto | Município onde ocorreu a internação |
| `CNES` | `co_cnes` | texto(7) | Estabelecimento executante — chave de junção com o CNES |
| `DIAG_PRINC` | `cid_principal` | texto(4) | CID-10 do diagnóstico principal |
| `DIAG_SECUN` | `cid_secundario` | texto(4) | CID-10 secundário |
| `DT_INTER` | `dt_internacao` | data | Data de entrada |
| `DT_SAIDA` | `dt_saida` | data | Data de saída |
| `DIAS_PERM` | `qt_dias_permanencia` | inteiro | Dias internado |
| `IDADE` | `nu_idade` | inteiro | Idade do paciente |
| `COD_IDADE` | `co_unidade_idade` | inteiro | Unidade da idade (3 = anos) |
| `SEXO` | `co_sexo` | inteiro | 1 = masculino, 3 = feminino |
| `MORTE` | `fl_obito` | inteiro | 1 = óbito durante a internação |
| `VAL_TOT` | `vl_total_aih` | decimal | Valor total pago, em reais |
| `CAR_INT` | `co_carater_internacao` | texto(2) | 01 = eletivo, 02 = urgência |

## Fonte 2 — CNES (JSON)

Cadastro Nacional de Estabelecimentos de Saúde, via API REST do Ministério da
Saúde. O documento JSON é preservado íntegro; abaixo o recorte projetado.
Extração: `src/ingestao/ingest_cnes.py`.

| Campo | Tipo | Descrição |
|---|---|---|
| `co_cnes` | texto(7) | Código do estabelecimento |
| `nm_estabelecimento` | texto | Nome fantasia ou razão social |
| `co_municipio` | texto | Código IBGE do município |
| `sg_uf` | texto(2) | Sigla da UF |
| `co_tipo_unidade` | texto(2) | Código do tipo de unidade |
| `ds_tipo_unidade` | texto | CAPS, HOSPITAL GERAL, HOSPITAL ESPECIALIZADO, PRONTO SOCORRO, UNIDADE BÁSICA, CLÍNICA/AMBULATÓRIO |
| `qt_leitos_sus` | inteiro | Leitos SUS de saúde mental |
| `latitude`, `longitude` | decimal | Coordenadas, quando disponíveis |

> O documento JSON original fica em `cnes_documento.documento`, coluna JSON
> nativa do Oracle, porque o schema da API varia entre competências. Ver
> `sql/02_ddl_json.sql`.

## Fonte 3 — IBGE e CID-10 (CSV)

Dados de referência versionados em `data/reference/`. Validação:
`src/ingestao/ingest_csv.py`.

### `uf_populacao.csv` — Censo Demográfico 2022

27 linhas, uma por unidade federativa.

| Campo | Tipo | Descrição |
|---|---|---|
| `co_uf` | texto(2) | Código IBGE da UF |
| `sg_uf` | texto(2) | Sigla |
| `nm_uf` | texto | Nome do estado |
| `regiao` | texto | Norte, Nordeste, Centro-Oeste, Sudeste, Sul |
| `populacao_2022` | inteiro | População residente — **denominador de todas as taxas** |

### `cid10_saude_mental.csv` — CID-10, Capítulo V

48 códigos, cobrindo os 10 blocos do capítulo.

| Campo | Tipo | Descrição |
|---|---|---|
| `cid10` | texto(3) | Código de 3 posições (ex.: F20) |
| `grupo_cid` | texto | Agrupamento (ex.: F20-F29) |
| `descricao` | texto | Nome oficial do transtorno |
| `descricao_curta` | texto | Rótulo curto para gráficos e painel |
| `gravidade_relativa` | texto | baixa, media, alta |
| `permanencia_esperada_dias` | inteiro | Referência de permanência típica |

**Blocos cobertos:** F00-F09 (orgânicos), F10-F19 (substâncias psicoativas),
F20-F29 (esquizofrenia e psicoses), F30-F39 (humor), F40-F48 (neuróticos),
F50-F59 (síndromes comportamentais), F60-F69 (personalidade), F70-F79 (retardo
mental), F80-F89 (desenvolvimento), F90-F98 (infância e adolescência).

> Com dados oficiais, a cobertura é ainda maior: o `ingest_sih.py` filtra por
> prefixo "F" e traz o capítulo inteiro. A lista de 48 códigos é do modo
> amostra.

---

## Campos derivados no tratamento

Criados em `src/etl/tratamento.py`.

| Campo | Regra |
|---|---|
| `cid_grupo` | 3 primeiras posições de `cid_principal` |
| `competencia` | `ano_competencia` + `mes_competencia` no formato AAAAMM |
| `dt_competencia` | `competencia` convertida em data |
| `ds_sexo` | 1 → Masculino, 3 → Feminino, demais → Não informado |
| `faixa_etaria` | Faixas 0-17, 18-29, 30-44, 45-59, 60+ |
| `fl_permanencia_prolongada` | 1 quando `qt_dias_permanencia` > 30 |
| `fl_tem_leito` | 1 quando `qt_leitos_sus` > 0 |

## Regras de qualidade aplicadas

Cada regra é contabilizada em `data/processed/relatorio_qualidade.json`.

| Regra | Critério | Ação |
|---|---|---|
| Deduplicação | `nu_aih` repetido | mantém o primeiro |
| Escopo diagnóstico | `cid_principal` não começa com F | remove |
| Permanência plausível | fora de 0 a 365 dias | remove |
| Idade plausível | fora de 0 a 110 anos | remove |
| CNES obrigatório | `co_cnes` nulo ou vazio | remove — sem ele não há junção |
| Coerência de datas | `dt_saida` anterior a `dt_internacao` | remove |
| Outliers | IQR de Tukey sobre permanência e valor | **documenta, não remove** |

> Outliers de permanência não são removidos de propósito: internações
> psiquiátricas longas são clinicamente reais e justamente o que mais pressiona
> a rede. Removê-las esconderia o problema que o projeto quer mostrar.

---

## Indicadores calculados

Definidos em `src/etl/indicadores.py` e replicados em SQL em
`sql/04_views_analiticas.sql`. As duas versões produzem o mesmo resultado.

| Indicador | Fórmula | Interpretação |
|---|---|---|
| Internações por 10 mil hab./ano | `internações ÷ população × 10.000 ÷ anos` | Comparação justa entre UFs de tamanhos diferentes |
| Permanência média | `média(qt_dias_permanencia)` | Complexidade dos casos |
| Taxa de ocupação estimada | `dias-paciente ÷ (leitos × dias do período)` | Quão perto do limite a rede opera |
| Leitos por 10 mil hab. | `leitos ÷ população × 10.000` | Capacidade instalada relativa |
| CAPS por 100 mil hab. | `CAPS ÷ população × 100.000` | Cobertura da atenção psicossocial |
| Índice de carga de leito | `% dias de leito ÷ % internações` | > 1 significa consumo acima do peso em volume |
| **IPA** | `0,5×demanda + 0,3×complexidade + 0,2×escassez` (normalizados 0-100) | Prioridade de investimento |

### Classificação do IPA

| Faixa | Situação |
|---|---|
| 0 a 25 | Baixa |
| 25 a 50 | Moderada |
| 50 a 75 | Alta |
| 75 a 100 | Crítica |

---

## Modelo dimensional no Oracle

Esquema estrela definido em `sql/01_ddl_relacional.sql`, criado no schema
`ADMIN` da instância `synodosdb`.

```
                    dim_tempo
                        │
   dim_territorio ── fato_internacao ── dim_estabelecimento
                        │                      │
                    dim_cid10           cnes_documento (JSON)
```

| Tabela | Tipo | Granularidade | Origem | Linhas carregadas |
|---|---|---|---|---|
| `fato_internacao` | Fato | uma linha por AIH | SIH/SUS | 49.997 |
| `dim_tempo` | Dimensão | uma por competência | derivada | 24 |
| `dim_estabelecimento` | Dimensão | uma por CNES | CNES (JSON) | 9.928 |
| `dim_territorio` | Dimensão | uma por UF | IBGE (CSV) | 27 |
| `dim_cid10` | Dimensão | uma por CID de 3 posições | CID-10 (CSV) | 48 |
| `cnes_documento` | Documento | uma por estabelecimento | CNES (JSON íntegro) | 9.928 |

As chaves estrangeiras estão declaradas, e os campos degenerados (`sg_uf`,
`competencia`, `cid_grupo`, `co_cnes`) são mantidos na tabela fato de propósito:
reduzem o número de junções que o Select AI precisa acertar para responder uma
pergunta simples.

### Views analíticas

| View | O que entrega |
|---|---|
| `vw_panorama_geral` | KPIs consolidados |
| `vw_serie_temporal` | Evolução mensal com média móvel e variação |
| `vw_taxa_por_uf` | Internações por 10 mil habitantes por estado |
| `vw_perfil_diagnostico` | Volume e consumo de leito por CID |
| `vw_ocupacao_rede` | Leitos, CAPS e taxa de ocupação |
| `vw_pressao_assistencial` | IPA com ranking e classificação |
| `vw_ranking_unidades` | Estabelecimentos por volume e ocupação |
| `vw_perfil_demografico` | Faixa etária e sexo |
| `vw_integracao_tres_formatos` | **Relacional + JSON + CSV numa consulta só** |
| `vw_cnes_json`, `vw_cnes_tabular` | Projeções do documento JSON |

---

## Privacidade

Nenhum campo identifica pessoas. O SIH/SUS é divulgado pelo Ministério da Saúde
já anonimizado: não há CPF, Cartão Nacional de Saúde, nome, endereço ou data de
nascimento. A menor granularidade é a internação, e todas as saídas do painel
são agregações por município, UF ou região.

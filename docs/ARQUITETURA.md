# Arquitetura da solução

Documento técnico da Sprint 2. Descreve o fluxo dos dados ponta a ponta, as
decisões que sustentam cada escolha, e separa com clareza o que foi construído
do que ficou planejado.

---

## Visão em camadas

| Camada | Responsabilidade | Tecnologias | Situação |
|---|---|---|---|
| **Origem** | Três fontes públicas em três formatos | SIH/SUS, API CNES, CSV IBGE | Implementado |
| **Ingestão** | Extração, paginação, validação de schema | Python, PySUS, requests, pandas | Implementado |
| **Tratamento** | Qualidade, deduplicação, padronização | pandas, regras auditáveis | Implementado |
| **Integração** | Junção das três fontes | pandas (Parquet) e SQL (Oracle) | Implementado |
| **Persistência** | Esquema estrela + coluna JSON | Oracle Autonomous AI Database 26ai | **Provisionado e carregado** |
| **Analítica** | Views curadas e indicadores | SQL, Python | Implementado |
| **Modelos** | Clusterização, projeção, decomposição | scikit-learn, statsmodels, numpy | Implementado |
| **Linguagem natural** | Pergunta em português → SQL → resposta | Oracle Select AI | **Funcionando** |
| **Consumo** | Painel do gestor | Streamlit, Plotly | Implementado e publicado |

---

## O ambiente Oracle

| Item | Valor |
|---|---|
| Instância | `synodosdb` — Autonomous AI Database Serverless |
| Versão | 26ai (23.26.3.2.0) |
| Tier | Always Free |
| Região | Brazil East (`sa-saopaulo-1`) |
| Workload | Lakehouse |
| Acesso | TLS, mTLS opcional |
| Schema | `ADMIN` |

**Carga atual:** 49.997 internações, 9.928 estabelecimentos na dimensão, 9.928
documentos JSON, 27 UFs, 48 códigos CID-10 e 24 competências.

O recorte de 50 mil internações é uma amostra estratificada por UF e
competência, gerada pelo `--limite` do `carga_oracle.py`. Ela preserva os 27
estados, as 24 competências e os 48 diagnósticos, com a distribuição dentro de
0,2 ponto percentual da base completa de 438 mil linhas. A base cheia carrega
com o mesmo comando, sem o parâmetro.

---

## Fluxo dos dados ponta a ponta

### Trilha A — SIH/SUS (relacional)

```
FTP DATASUS (.dbc)
   → PySUS baixa a competência                       ingest_sih.py
   → filtra Capítulo V do CID-10 (prefixo F)
   → seleciona 18 colunas e renomeia para nomes de negócio
   → tipagem de datas, numéricos e códigos
   → data/raw/sih_internacoes.parquet
        ↓
   → deduplicação por nu_aih                         tratamento.py
   → plausibilidade clínica (permanência, idade, datas)
   → campos derivados (faixa etária, competência, flags)
   → data/processed/fato_internacao.parquet
```

### Trilha B — CNES (JSON)

```
API apidadosabertos.saude.gov.br
   → paginação de 100 em 100 registros               ingest_cnes.py
   → preserva o documento JSON íntegro       → cnes_estabelecimentos.json
   → projeta o recorte tabular estável       → cnes_estabelecimentos.parquet
        ↓
   → deduplicação por CNES, padronização de código e leitos
   → data/processed/dim_estabelecimento.parquet
```

### Trilha C — IBGE e CID-10 (CSV)

```
data/reference/*.csv (versionados no git)
   → validação de schema, unicidade e totais          ingest_csv.py
   → agregação regional (denominadores)
   → data/processed/dim_territorio.csv, dim_cid10.csv
```

### Confluência

```
fato_internacao  ⋈(co_cnes)   dim_estabelecimento    integracao.py
                 ⋈(sg_uf)     dim_territorio
                 ⋈(cid_grupo) dim_cid10
   → analitico_internacoes.parquet   (438 mil × 38 colunas)
        ↓
   → indicadores de gestão                            indicadores.py
        ↓
   ├─→ modelos analíticos                             modelos.py
   ├─→ análise exploratória e 9 gráficos              eda.py
   ├─→ carga no Oracle                                carga_oracle.py
   └─→ dashboard                                      dashboard/app.py
```

No Oracle, a mesma confluência acontece em SQL — a view
`vw_integracao_tres_formatos` cruza tabela relacional, documento JSON e a
dimensão vinda do CSV em uma consulta única.

---

## Decisões técnicas e por quê

### Três formatos de persistência, deliberadamente

O challenge pede o uso justificado de relacional, JSON e CSV. A justificativa
não é a exigência — cada formato resolve um problema real.

**Relacional para o SIH/SUS.** Volume alto, schema estável há anos,
granularidade fixa. É o caso canônico de tabela: índices em competência, UF e
CID atendem todos os filtros do painel.

**JSON para o CNES.** O schema da API muda entre competências — campos de
habilitação, equipes e serviços especializados aparecem e desaparecem por tipo
de unidade. Modelar em colunas fixas exigiria `ALTER TABLE` a cada mudança do
Ministério e descartaria informação. O Oracle armazena o documento em coluna
JSON nativa, indexa com `SEARCH INDEX`, e o consulta com o **mesmo SQL** das
tabelas relacionais.

**CSV para IBGE e CID-10.** Dados de referência: pequenos, mudam raramente,
publicados como CSV. Ficam versionados em `data/reference/` e alimentam as
dimensões.

### Esquema estrela, não normalizado

A carga é em lote e a leitura é analítica. Um esquema estrela com dimensões
desnormalizadas reduz junções e melhora o desempenho. Mantemos campos
degenerados na tabela fato (`sg_uf`, `competencia`, `cid_grupo`, `co_cnes`) por
um motivo específico: **quanto menos junções o Select AI precisa acertar, maior
a taxa de acerto do SQL gerado.**

### `COMMENT ON` como infraestrutura, não documentação

Os comentários de tabela e coluna em `sql/01_ddl_relacional.sql` são o
vocabulário que o Select AI usa para traduzir português em SQL. Escrever
`COMMENT ON COLUMN fato_internacao.cid_grupo IS 'Código CID-10 de 3 posições
(ex.: F20 esquizofrenia, F31 transtorno bipolar)'` é o que permite ao gestor
perguntar "quantas internações por esquizofrenia" sem saber o que é F20.

Pela mesma razão, o perfil de IA expõe as **views com nomes em português**, não
as tabelas cruas — e restringe a superfície de dados visível ao modelo àquilo
que já é agregado.

### Outliers documentados, não removidos

Internações psiquiátricas muito longas são clinicamente reais e são exatamente
o que mais pressiona a rede. O relatório de qualidade registra a análise de IQR,
mas o pipeline não descarta esses registros.

### Taxa por 10 mil habitantes como métrica primária

Em números absolutos, São Paulo lidera qualquer ranking — tem 44 milhões de
habitantes. A normalização populacional é o que transforma o painel em
ferramenta de decisão em vez de mapa demográfico.

---

## Select AI

A camada de perguntas em português está implementada em dois modos, com a mesma
interface (`src/db/select_ai.py`).

**Modo Oracle.** A consulta acontece em duas etapas: pedimos ao modelo apenas o
SQL (ação `showsql`) e o próprio banco executa essa consulta. É melhor que usar
`runsql` direto por dois motivos — o resultado volta como tabela e não como
texto, e ficamos com o SQL em mãos para exibir ao gestor, que é o que torna a
resposta auditável.

Se a pergunta não for sobre os dados, a geração de SQL falha e caímos na ação
`chat`. A interface rotula essa resposta como vinda do conhecimento do modelo,
e não da base. **A distinção é deliberada:** se todas as respostas parecessem
iguais, o gestor não saberia quando confiar no número.

**Modo local.** Um classificador de intenção mapeia a pergunta para um template
SQL, executado pelo DuckDB. Existe para que o pipeline rode sem instância
Oracle. A diferença honesta: no Oracle quem escreve o SQL é um modelo de
linguagem, capaz de responder perguntas nunca antecipadas; no local o
vocabulário é finito. O SQL e a execução são reais nos dois casos.

**Provedor:** OCI Generative AI com resource principal
(`OCI$RESOURCE_PRINCIPAL`), sem chave de API paga, na região `sa-saopaulo-1`.

---

## Modelos analíticos

| Modelo | Técnica | Escolha de parâmetros |
|---|---|---|
| Clusterização de UFs | K-Means sobre 5 atributos padronizados | k por coeficiente de silhueta |
| Projeção de demanda | Regressão OLS com tendência e 11 dummies de mês | validação em 6 meses retidos |
| Decomposição sazonal | STL robusto, período 12 | — |
| Correlação | Spearman entre indicadores por UF | — |
| Outliers | IQR de Tukey | — |

**Por que Spearman e não Pearson:** distribuições assimétricas entre UFs; a
correlação de postos é mais robusta e não pressupõe linearidade.

**Por que padronizar antes do K-Means:** os atributos têm escalas muito
diferentes. Sem `StandardScaler`, a distância euclidiana seria dominada pela
variável de maior escala.

---

## Segurança e conformidade

| Aspecto | Implementação |
|---|---|
| Dados pessoais | Nenhum — o SIH/SUS é público e anonimizado na origem |
| Granularidade mínima | Internação (AIH), sem vínculo com indivíduo |
| Saídas do painel | Sempre agregadas por município, UF ou região |
| Credenciais | Fora do versionamento — `.env` no `.gitignore` |
| Conexão | TLS; mTLS via wallet disponível |
| Superfície exposta à IA | Restrita às views agregadas pelo `object_list` |
| Usuário do app público | `sql/06_usuario_publico.sql` cria um usuário só-leitura, sem acesso às tabelas cruas |
| Auditoria | `showsql` permite ver e registrar o SQL gerado |

Sobre o usuário só-leitura: o Select AI gera SQL a partir de texto livre. A
defesa contra um comando destrutivo não é filtrar a pergunta — é tirar o poder.
O usuário do app tem apenas `SELECT`, e apenas sobre as views.

---

## O que falta e como está planejado

| Item | Situação | Plano |
|---|---|---|
| Ingestão com dados oficiais | Código pronto, não executado | Rodar `ingest_sih.py` e `ingest_cnes.py` em rede com acesso ao DATASUS |
| External table sobre CSV | Codificada em `sql/03`, não executada | Exige bucket no OCI Object Storage; hoje a dimensão é carregada via Python |
| Select AI no app publicado | Funciona local; publicado roda em modo local | Configurar os Secrets do Streamlit com o usuário só-leitura |
| Granularidade municipal | Agregado por UF | O campo `co_municipio_residencia` já é carregado; falta a dimensão de municípios do IBGE |
| Mapa coroplético | Não implementado | Depende da malha territorial do IBGE (GeoJSON) |
| Reincidência em 30 dias | Não implementado | **Inviável com dados públicos** — ver abaixo |

**Sobre a reincidência.** O indicador foi previsto na Sprint 1 e não é viável
com dados públicos: o SIH anonimizado não permite ligar duas internações ao
mesmo paciente. Dentro da rede de uma secretaria, com base identificada e
controle de acesso, o cálculo é direto. É uma limitação de fonte, não de
arquitetura.

---

## Evolução da Sprint 1 para a Sprint 2

| Dimensão | Sprint 1 | Sprint 2 |
|---|---|---|
| Arquitetura | Desenho conceitual com Kafka, Databricks, BigQuery | Consolidada no Oracle Autonomous Database, provisionado e carregado |
| Dados | Protótipo com dados fictícios de interface | Pipeline de três fontes, 438 mil registros integrados, 27 estados |
| Painel | Protótipo React (Lovable), sem dados | Dashboard funcional publicado, com filtros sobre a base tratada |
| Análise | Indicadores propostos | 7 indicadores calculados + o IPA, indicador próprio |
| Modelos | Mencionados | 3 modelos implementados e validados |
| IA | LLM para gerar textos de insight | Select AI: pergunta em português vira SQL executado no banco |
| Código | — | 16 módulos Python, 7 scripts SQL, notebook, dashboard, validador |

A mudança mais relevante foi de **narrativa técnica**: a Sprint 1 desenhou uma
arquitetura de produção com muitos componentes; a Sprint 2 escolheu o
Autonomous Database como núcleo integrador e construiu. Kafka, Databricks e
Delta Lake continuam válidos como caminho de escala, e estão descritos como
evolução — não como o que foi entregue.

# Synodos

Painel de acesso hospitalar e perfil de atendimento em saúde mental no SUS.

Projeto do Challenge FIAP + Oracle 2026, turma 1TSCO — Sprint 2.

---

## O problema que a gente foi atrás

Uma secretaria de saúde precisa responder perguntas que parecem simples e não
consegue: onde as internações por transtornos mentais estão crescendo, quais
regiões estão sobrecarregadas, onde faltam leitos, e para onde mandar o próximo
investimento.

Os dados existem. SIH/SUS, CNES, IBGE — tudo público. O problema é que cada um
mora em um formato diferente: uma base relacional de internações, uma API que
devolve JSON com estrutura que muda de mês para mês, e planilhas CSV de
população. Cruzar isso exige um analista, um script e alguns dias de trabalho.
Quando a resposta chega, o momento da decisão já passou.

## O que construímos

O Synodos junta essas três fontes em um único lugar consultável por SQL no
Oracle Autonomous Database, calcula indicadores de gestão em cima dessa base
integrada, e entrega isso ao gestor de duas formas:

1. Um painel com KPIs, séries temporais, rankings e filtros.
2. O Oracle Select AI, que responde perguntas escritas em português. O gestor
   pergunta, o banco gera o SQL, executa e devolve a resposta.

Esse segundo ponto é o que a gente considera o diferencial do projeto. E vale
explicar por quê: os números nunca são inventados pela IA. O modelo de
linguagem escreve a **consulta**; quem produz o resultado é o banco de dados.
Isso muda tudo em termos de confiança, porque o gestor pode auditar o SQL.

---

## Como os dados percorrem a solução

```
FONTES                     SIH/SUS          CNES API        IBGE + CID-10
                          (relacional)       (JSON)             (CSV)
                               |                |                 |
INGESTÃO                  ingest_sih.py   ingest_cnes.py   ingest_csv.py
                               |                |                 |
                               +----------------+-----------------+
                                                |
TRATAMENTO                              tratamento.py
                          deduplicação, plausibilidade clínica, outliers
                                                |
INTEGRAÇÃO                              integracao.py
                          é aqui que os três formatos se encontram
                                                |
PERSISTÊNCIA                  ORACLE AUTONOMOUS DATABASE
                    esquema estrela + coluna JSON + external table CSV
                                                |
CAMADA ANALÍTICA              8 views curadas + indicadores.py
                    pressão assistencial, taxas por 10 mil hab., ocupação
                                                |
                        +-----------------------+------------------+
                        |                                          |
MODELOS              modelos.py                              SELECT AI
                K-Means, projeção, STL                 pergunta em português
                        |                                          |
                        +-----------------------+------------------+
                                                |
CONSUMO                              Dashboard Streamlit
                                                |
                                    GESTOR TOMA A DECISÃO
```

### Por que três formatos diferentes

O challenge pedia o uso justificado de relacional, JSON e CSV. Mas a
justificativa não é a exigência — cada formato resolve um problema real.

**O SIH/SUS vai para tabela relacional.** São centenas de milhares de linhas
por competência, o schema é estável há anos, e a granularidade é fixa: uma
linha por AIH. É o caso clássico de tabela. Índices em competência, UF e CID
atendem todos os filtros do painel.

**O CNES vai para JSON.** Esse foi o caso que mais nos convenceu. A API do
Ministério da Saúde muda de estrutura entre competências: campos de
habilitação, equipes e serviços especializados aparecem e somem dependendo do
tipo de unidade. Se a gente modelasse isso em colunas fixas, precisaria alterar
a tabela toda vez que o Ministério mudasse alguma coisa, e ainda perderia
informação no caminho. Guardando o documento inteiro em coluna JSON nativa, o
Oracle indexa e consulta com o mesmo SQL das tabelas relacionais. Só projetamos
para colunas o pedaço estável que os indicadores usam.

**População e CID-10 vão para CSV lido como external table.** São dados de
referência: pequenos, mudam raramente, já publicados em CSV. Carregar
fisicamente seria manutenção sem ganho nenhum. Deixando o arquivo no Object
Storage, atualizar o denominador populacional vira trocar um arquivo no bucket.
Sem ETL, sem recarga.

No fim, o Oracle consulta os três com a mesma linguagem. Tem uma view em
`sql/02_ddl_json.sql` chamada `vw_integracao_tres_formatos` que faz isso numa
consulta só, justamente para deixar essa ideia visível.

---

## O que está pronto e o que não está

Achamos importante ser claro sobre isso, porque parte do projeto ficou pela
metade dentro da janela da sprint.

**Funcionando:**

- ingestão das três fontes, cada uma no seu formato
- tratamento com regras de qualidade auditáveis
- integração das três fontes numa tabela analítica única
- 7 indicadores de gestão, incluindo um índice composto que criamos
- 3 modelos analíticos (clusterização, projeção e decomposição sazonal)
- dashboard com filtros por período, estado, região e diagnóstico
- perguntas em linguagem natural, em modo local

**Escrito mas ainda não executado:**

- toda a modelagem Oracle (`sql/01` a `sql/05`) e a carga (`carga_oracle.py`)
- o Select AI com modelo de linguagem de verdade

O motivo é direto: **não conseguimos provisionar a instância do Autonomous
Database dentro do prazo da sprint.** O código está escrito e versionado, e a
ordem de execução está mais abaixo. O que falta é rodar contra uma instância
real.

Enquanto isso não acontece, a camada de perguntas em português funciona em modo
local: um classificador de intenção mapeia a pergunta para um template SQL, e o
DuckDB executa isso sobre os dados. A diferença honesta entre os dois modos é
essa:

- no **Oracle**, quem escreve o SQL é um modelo de linguagem, então ele
  responde perguntas que ninguém antecipou;
- no **modo local**, o SQL vem de templates, então o vocabulário é finito.

Nos dois casos o SQL é real e a execução é real. O que muda é a capacidade de
generalizar.

**Coisas que ficaram para depois:** granularidade por município (o campo já é
carregado, falta a dimensão do IBGE), mapa coroplético, e o cálculo de
reincidência em 30 dias. Esse último merece uma nota: ele estava previsto desde
a Sprint 1, e descobrimos no meio do caminho que **não é viável com dados
públicos**. O SIH anonimizado não permite ligar duas internações ao mesmo
paciente. Dentro da rede de uma secretaria, com base identificada e controle de
acesso, o cálculo é direto. É uma limitação da fonte, não da arquitetura.

---

## Sobre os dados

O pipeline tem dois modos de entrada, e vale entender a diferença.

O **modo oficial** (`ingest_sih.py` e `ingest_cnes.py`) baixa dados públicos
reais do FTP do DATASUS e da API do Ministério da Saúde.

O **modo amostra** (`gerar_amostra.py`) gera registros com a mesma estrutura de
colunas dos extratores reais. Ele existe por uma razão prática: o FTP do
DATASUS cai com frequência, e sem esse modo qualquer pessoa que clonasse o
repositório ficaria travada. Assim o pipeline inteiro roda em qualquer máquina.

O que é real na amostra:

- população por UF, direto do Censo IBGE 2022
- códigos e descrições do CID-10, Capítulo V
- códigos IBGE de UF e a divisão regional oficial
- a calibragem dos parâmetros, que conferimos contra as ordens de grandeza
  publicadas:

| Indicador | Na amostra (27 UFs) | Referência publicada |
|---|---|---|
| Internações psiquiátricas por 10 mil hab./ano | 10,79 | cerca de 9 a 10 |
| Leitos de saúde mental por 10 mil hab. | 0,77 | cerca de 0,7 |
| Permanência média | 17,8 dias | 15 a 25 |
| Taxa de ocupação | 67,7% | 60% a 80% |
| CAPS no país | 2.707 | cerca de 2.800 |

O que é sintético: os registros individuais de AIH. Nenhum dado de paciente é
usado. O SIH/SUS é público e já vem anonimizado da origem, e a amostra é gerada
estatisticamente em cima das taxas.

**Uma limitação que precisamos declarar.** Como os dados da amostra são gerados
com ruído de Poisson, eles saem mais regulares que a realidade. Isso infla as
métricas de ajuste dos modelos: o R² de 0,998 e o MAPE de 0,9% da projeção **não
vão se sustentar com dados reais do SIH**, onde o esperado é algo entre 0,70 e
0,85. As forças de tendência e sazonalidade da decomposição STL saem em 1,00
pelo mesmo motivo. Os números do painel são representativos, não oficiais.

---

## Os indicadores

Os principais estão em `src/etl/indicadores.py`, e replicados em SQL em
`sql/04_views_analiticas.sql` — as duas versões dão o mesmo resultado.

O que a gente considera a métrica mais importante é a **taxa por 10 mil
habitantes**. Em números absolutos, São Paulo lidera qualquer ranking, porque
tem 44 milhões de habitantes. Isso não é informação, é demografia. Normalizar
pela população é o que transforma o painel numa ferramenta de decisão. Por isso
o denominador do IBGE entrou como fonte de primeira classe na arquitetura, e
não como um detalhe.

### Índice de Pressão Assistencial

Esse indicador a gente criou. Ele normaliza três dimensões entre 0 e 100 e
pondera:

```
IPA = 0,5 x demanda        (internações por 10 mil hab./ano)
    + 0,3 x complexidade   (permanência média)
    + 0,2 x escassez       (inverso dos leitos por 10 mil hab.)
```

Serve para responder "onde investir primeiro" com um número comparável entre
estados de tamanhos muito diferentes. Faixas: até 25 é Baixa, até 50 Moderada,
até 75 Alta, acima disso Crítica.

## Os modelos

| Modelo | A pergunta que ele responde | Técnica |
|---|---|---|
| Clusterização | Quais estados têm perfil parecido e podem receber a mesma política? | K-Means, k escolhido por silhueta |
| Projeção | Quantas internações esperar nos próximos 6 meses? | Regressão com tendência e sazonalidade |
| Decomposição | O crescimento é real ou é sazonalidade? | STL robusto |
| Correlação | Demanda e capacidade se relacionam? | Spearman |

Duas decisões que vale explicar. Usamos **Spearman e não Pearson** porque com 7
UFs e distribuições assimétricas a correlação de postos é mais robusta e não
pressupõe linearidade. E **padronizamos antes do K-Means** porque os atributos
têm escalas muito diferentes — internações por 10 mil fica na casa de 10,
população na casa de 10 milhões. Sem padronizar, a distância euclidiana seria
dominada pela variável de maior escala e o agrupamento não significaria nada.

---

## Como rodar

Precisa de Python 3.10 ou mais novo.

```bash
git clone https://github.com/GuilhermeMPereira/Synodos
cd Synodos

python -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Depois roda o pipeline. Leva menos de um minuto:

```bash
python -m src.ingestao.gerar_amostra
python -m src.ingestao.ingest_csv
python -m src.etl.tratamento
python -m src.etl.integracao
python -m src.etl.indicadores
python -m src.analytics.eda
python -m src.analytics.modelos
```

E abre o painel:

```bash
streamlit run dashboard/app.py
```

Se quiser conferir que está tudo funcionando de ponta a ponta, tem um script
que roda o pipeline do zero e checa 19 invariantes dos dados:

```bash
python scripts/validar_pipeline.py
```

### Com dados oficiais

Precisa de acesso ao FTP do DATASUS e à API do Ministério da Saúde, e do PySUS
instalado (`pip install pysus`).

```bash
python -m src.ingestao.ingest_sih --ufs SP,RJ,MG --inicio 202301 --fim 202412
python -m src.ingestao.ingest_cnes --ufs SP,RJ,MG
```

O resto do pipeline é igual.

### Perguntando aos dados pela linha de comando

```bash
python -m src.db.select_ai --local "Quais estados estão com maior pressão assistencial?"
python -m src.db.select_ai --listar
```

### Rodando contra o Oracle

1. Provisione um Autonomous Database. O tier Always Free dá conta do piloto.
2. Baixe a wallet e preencha o `.env` (tem um `.env.example` de modelo).
3. Teste a conexão com `python -m src.db.oracle_conn`.
4. Execute, no SQL Developer ou no Database Actions, nesta ordem:
   `sql/01_ddl_relacional.sql`, `sql/02_ddl_json.sql` e
   `sql/03_external_table_csv.sql`.
5. Carregue os dados com `python -m src.db.carga_oracle`.
6. Rode `sql/04_views_analiticas.sql` e depois `sql/05_select_ai_setup.sql`.

Uma dica que custou tempo para a gente descobrir: os `COMMENT ON` do
`sql/01_ddl_relacional.sql` não são documentação, são infraestrutura. O Select
AI usa esses comentários para traduzir a pergunta em português para SQL. Sem
eles, o modelo não sabe que F20 é esquizofrenia e a taxa de acerto despenca.

Por isso também expomos ao perfil de IA as **views com nomes em português**, e
não as tabelas cruas. Melhora muito o SQL gerado, e de quebra restringe o que o
modelo enxerga ao que já está agregado.

Sobre o provedor de IA: usamos o **OCI Generative AI** com resource principal,
que não precisa de chave de API paga. A região `sa-saopaulo-1` está na lista de
regiões suportadas, então dá para rodar tudo no Brasil.

---

## Organização do repositório

```
config/settings.py          configuração central, lê o .env
data/reference/             os CSV de referência (IBGE, CID-10)
data/processed/             camada tratada e indicadores
src/ingestao/               os três extratores + o gerador de amostra
src/etl/                    tratamento, integração e indicadores
src/db/                     conexão Oracle, carga e Select AI
src/analytics/              análise exploratória e modelos
sql/                        01 a 06: DDL, JSON, CSV, views, Select AI e usuário do app
notebooks/                  análise exploratória em Jupyter
dashboard/app.py            o painel
assets/graficos/            os 9 gráficos que o pipeline gera
scripts/validar_pipeline.py validação ponta a ponta
docs/ARQUITETURA.md         o fluxo dos dados e as decisões técnicas
docs/DICIONARIO_DADOS.md    cada campo, sua origem e o tratamento aplicado
docs/SELECT_AI.md           como o Select AI foi configurado e como usar
```

---

## O que os dados mostraram

Recorte atual: **27 UFs**, 24 competências, 2023 e 2024. São **438.181
internações**, com permanência média de **17,8 dias** e custo total de **R$
608,6 milhões**. A rede tem 15.732 leitos de saúde mental e opera a **67,7%** de
ocupação estimada.

Três achados que consideramos relevantes:

**A esquizofrenia consome 29,9% dos dias de leito com 19,0% das internações.**
Ou seja, o diagnóstico que mais interna não é o que mais ocupa a rede. Quem
planeja leito olhando volume de internação subdimensiona a necessidade real. O
índice de carga de leito desse diagnóstico é 1,58 — consome mais que o dobro do
peso que tem em volume, comparado ao uso de álcool (0,79).

**O Acre lidera o índice de pressão, com 66,8 pontos.** É a combinação da maior
demanda proporcional do país (12,96 internações por 10 mil habitantes por ano)
com uma rede pequena em números absolutos: 84 leitos e 11 CAPS. Logo atrás vêm
Maranhão (66,7) e Rio Grande do Norte (64,9) — o Nordeste ocupa quatro das cinco
primeiras posições.

**A correlação entre leitos por habitante e taxa de ocupação é de −0,51.**
Moderada e negativa: a escassez de leitos não reduz a demanda, ela só empurra a
rede para perto do limite. Foi o achado que mais nos convenceu de que o índice
fazia sentido.

> Números de uma versão anterior do recorte (7 UFs, 234 mil internações,
> correlação −0,81) aparecem em materiais antigos. Os válidos são os desta
> seção, e batem com o painel e com `data/processed/`.

---

## Privacidade

O projeto usa só dados públicos e agregados. O SIH/SUS é divulgado pelo
Ministério da Saúde já anonimizado, sem identificação de paciente. Nenhuma base
tem CPF, Cartão Nacional de Saúde, nome ou endereço. A menor granularidade que
tratamos é a internação, e tudo que sai no painel é agregado por município,
estado ou região.

---

## Equipe

| Integrante | Papel |
|---|---|
| Diego Barreto | Product Owner |
| Ricardo Gnan Jr. | Scrum Master |
| Guilherme Martins | Dev — Dados |
| Claudia Obi | Dev — Análise |
| Walleska Contarini | Dev — IA e Visualização |

## Fontes de dados

- SIH/SUS — Sistema de Informações Hospitalares, DATASUS / Ministério da Saúde
- CNES — Cadastro Nacional de Estabelecimentos de Saúde, Ministério da Saúde
- Censo Demográfico 2022 — IBGE
- CID-10, Capítulo V — Classificação Internacional de Doenças, OMS

A parte de Select AI seguiu o procedimento do workshop [Chat with Your Data in
Autonomous AI Database Using Select
AI](https://livelabs.oracle.com/pls/apex/r/dbpm/livelabs/view-workshop?wid=4222),
do Oracle LiveLabs, aplicado ao nosso domínio no lugar do schema de
demonstração MovieStream que o lab usa.

-- ===========================================================================
-- SYNODOS | SETUP RAPIDO - execute TUDO conectado como ADMIN
-- ---------------------------------------------------------------------------
-- Este arquivo junta os scripts 01, 02 e 04 num unico bloco, para ser colado
-- de uma vez no Database Actions > SQL e executado com "Run Script" (F5).
--
-- Por que como ADMIN e nao com um usuario SYNODOS: usar o ADMIN dispensa
-- criar o usuario e habilita-lo no ORDS, que sao dois passos a mais e uma
-- fonte comum de erro de permissao. Para o piloto, os objetos ficam no
-- schema ADMIN e tudo funciona igual.
--
-- Depois deste arquivo:
--   1. python -m src.db.carga_oracle --limite 50000
--   2. sql/05_select_ai_setup.sql  (opcional, para o Select AI)
-- ===========================================================================



-- ======================================================================
-- ORIGEM: sql/01_ddl_relacional.sql
-- ======================================================================

-- ===========================================================================
-- SYNODOS | 01 - MODELO RELACIONAL (FONTE 1: SIH/SUS)
-- Oracle Autonomous Database 19c/23ai
-- ---------------------------------------------------------------------------
-- Modelagem dimensional (esquema estrela) sobre a AIH do SIH/SUS.
-- A granularidade da tabela fato e UMA LINHA POR INTERNACAO (AIH).
-- ===========================================================================

-- ------------------------------------------------------- DIMENSAO TEMPO
CREATE TABLE dim_tempo (
    sk_tempo          NUMBER(8)     NOT NULL,
    competencia       CHAR(6)       NOT NULL,   -- AAAAMM
    ano               NUMBER(4)     NOT NULL,
    mes               NUMBER(2)     NOT NULL,
    trimestre         NUMBER(1)     NOT NULL,
    nm_mes            VARCHAR2(20)  NOT NULL,
    dt_competencia    DATE          NOT NULL,
    CONSTRAINT pk_dim_tempo PRIMARY KEY (sk_tempo),
    CONSTRAINT uk_dim_tempo_comp UNIQUE (competencia),
    CONSTRAINT ck_dim_tempo_mes CHECK (mes BETWEEN 1 AND 12)
);

-- ------------------------------------------------- DIMENSAO ESTABELECIMENTO
-- Alimentada a partir do JSON do CNES (ver 02_ddl_json.sql)
CREATE TABLE dim_estabelecimento (
    sk_estabelecimento   NUMBER(10)     NOT NULL,
    co_cnes              CHAR(7)        NOT NULL,
    nm_estabelecimento   VARCHAR2(200),
    co_tipo_unidade      CHAR(2),
    ds_tipo_unidade      VARCHAR2(80),
    co_municipio         VARCHAR2(10),
    sg_uf                CHAR(2),
    qt_leitos_sus        NUMBER(6)      DEFAULT 0,
    fl_tem_leito         NUMBER(1)      DEFAULT 0,
    latitude             NUMBER(10,6),
    longitude            NUMBER(10,6),
    dt_carga             TIMESTAMP      DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_dim_estab PRIMARY KEY (sk_estabelecimento),
    CONSTRAINT uk_dim_estab_cnes UNIQUE (co_cnes),
    CONSTRAINT ck_dim_estab_leitos CHECK (qt_leitos_sus >= 0)
);

-- ----------------------------------------------------- DIMENSAO TERRITORIO
CREATE TABLE dim_territorio (
    sk_territorio     NUMBER(6)      NOT NULL,
    co_uf             CHAR(2)        NOT NULL,
    sg_uf             CHAR(2)        NOT NULL,
    nm_uf             VARCHAR2(60)   NOT NULL,
    regiao            VARCHAR2(20)   NOT NULL,
    populacao_2022    NUMBER(12)     NOT NULL,
    populacao_regiao  NUMBER(12),
    CONSTRAINT pk_dim_territorio PRIMARY KEY (sk_territorio),
    CONSTRAINT uk_dim_territorio_uf UNIQUE (sg_uf),
    CONSTRAINT ck_dim_territorio_pop CHECK (populacao_2022 > 0)
);

-- ---------------------------------------------------------- DIMENSAO CID
CREATE TABLE dim_cid10 (
    sk_cid                       NUMBER(6)     NOT NULL,
    cid10                        CHAR(3)       NOT NULL,
    grupo_cid                    VARCHAR2(10),
    descricao                    VARCHAR2(200),
    gravidade_relativa           VARCHAR2(10),
    permanencia_esperada_dias    NUMBER(4),
    CONSTRAINT pk_dim_cid PRIMARY KEY (sk_cid),
    CONSTRAINT uk_dim_cid_codigo UNIQUE (cid10)
);

-- ------------------------------------------------------ FATO INTERNACAO
CREATE TABLE fato_internacao (
    sk_internacao            NUMBER(12)     NOT NULL,
    nu_aih                   VARCHAR2(20)   NOT NULL,
    sk_tempo                 NUMBER(8)      NOT NULL,
    sk_estabelecimento       NUMBER(10),
    sk_territorio            NUMBER(6),
    sk_cid                   NUMBER(6),
    -- degeneradas (facilitam o Select AI a responder sem tantos joins)
    competencia              CHAR(6)        NOT NULL,
    sg_uf                    CHAR(2),
    co_cnes                  CHAR(7),
    cid_principal            VARCHAR2(4),
    cid_grupo                CHAR(3),
    -- metricas
    dt_internacao            DATE,
    dt_saida                 DATE,
    qt_dias_permanencia      NUMBER(5),
    nu_idade                 NUMBER(3),
    faixa_etaria             VARCHAR2(10),
    co_sexo                  NUMBER(1),
    ds_sexo                  VARCHAR2(15),
    fl_obito                 NUMBER(1)      DEFAULT 0,
    fl_permanencia_prolongada NUMBER(1)     DEFAULT 0,
    vl_total_aih             NUMBER(12,2),
    co_carater_internacao    CHAR(2),
    dt_carga                 TIMESTAMP      DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_fato_internacao PRIMARY KEY (sk_internacao),
    CONSTRAINT uk_fato_aih UNIQUE (nu_aih),
    CONSTRAINT fk_fato_tempo
        FOREIGN KEY (sk_tempo) REFERENCES dim_tempo (sk_tempo),
    CONSTRAINT fk_fato_estab
        FOREIGN KEY (sk_estabelecimento)
        REFERENCES dim_estabelecimento (sk_estabelecimento),
    CONSTRAINT fk_fato_territorio
        FOREIGN KEY (sk_territorio)
        REFERENCES dim_territorio (sk_territorio),
    CONSTRAINT fk_fato_cid
        FOREIGN KEY (sk_cid) REFERENCES dim_cid10 (sk_cid),
    CONSTRAINT ck_fato_permanencia
        CHECK (qt_dias_permanencia BETWEEN 0 AND 365),
    CONSTRAINT ck_fato_obito CHECK (fl_obito IN (0, 1))
);

-- ------------------------------------------------------------- INDICES
-- Suportam os filtros do painel: periodo, UF, diagnostico e unidade.
CREATE INDEX ix_fato_competencia ON fato_internacao (competencia);
CREATE INDEX ix_fato_uf_comp     ON fato_internacao (sg_uf, competencia);
CREATE INDEX ix_fato_cid         ON fato_internacao (cid_grupo);
CREATE INDEX ix_fato_cnes        ON fato_internacao (co_cnes);
CREATE INDEX ix_fato_dt_inter    ON fato_internacao (dt_internacao);

CREATE INDEX ix_estab_uf_tipo
    ON dim_estabelecimento (sg_uf, co_tipo_unidade);

-- ------------------------------------------------------------ COMENTARIOS
-- Os comentarios NAO sao decorativos: o Oracle Select AI usa os metadados
-- do dicionario de dados para traduzir perguntas em portugues para SQL.
-- Quanto melhor descritos, melhor a qualidade do SQL gerado.
COMMENT ON TABLE  fato_internacao IS
    'Internacoes hospitalares do SUS por transtornos mentais e comportamentais (CID-10 Capitulo V). Uma linha por AIH.';
COMMENT ON COLUMN fato_internacao.nu_aih IS
    'Numero da Autorizacao de Internacao Hospitalar, identificador unico da internacao';
COMMENT ON COLUMN fato_internacao.competencia IS
    'Competencia da internacao no formato AAAAMM (ex.: 202403 = marco de 2024)';
COMMENT ON COLUMN fato_internacao.qt_dias_permanencia IS
    'Quantidade de dias que o paciente permaneceu internado';
COMMENT ON COLUMN fato_internacao.cid_grupo IS
    'Codigo CID-10 de 3 posicoes do diagnostico principal (ex.: F20 esquizofrenia, F31 transtorno bipolar, F10 alcool)';
COMMENT ON COLUMN fato_internacao.vl_total_aih IS
    'Valor total pago pela internacao em reais';
COMMENT ON COLUMN fato_internacao.fl_obito IS
    'Indicador de obito durante a internacao: 1 sim, 0 nao';
COMMENT ON COLUMN fato_internacao.sg_uf IS
    'Sigla da unidade federativa onde ocorreu a internacao (ex.: SP, RJ, MG)';

COMMENT ON TABLE  dim_estabelecimento IS
    'Estabelecimentos de saude do CNES que compoem a Rede de Atencao Psicossocial';
COMMENT ON COLUMN dim_estabelecimento.qt_leitos_sus IS
    'Quantidade de leitos SUS de saude mental disponiveis no estabelecimento';
COMMENT ON COLUMN dim_estabelecimento.ds_tipo_unidade IS
    'Tipo da unidade: CAPS, HOSPITAL GERAL, HOSPITAL ESPECIALIZADO, PRONTO SOCORRO, UNIDADE BASICA';

COMMENT ON TABLE  dim_territorio IS
    'Unidades federativas do Brasil com populacao do Censo IBGE 2022';
COMMENT ON COLUMN dim_territorio.populacao_2022 IS
    'Populacao residente na UF segundo o Censo Demografico IBGE 2022, usada como denominador das taxas';

COMMENT ON TABLE  dim_cid10 IS
    'Classificacao Internacional de Doencas CID-10, Capitulo V, transtornos mentais e comportamentais';
COMMENT ON COLUMN dim_cid10.descricao IS
    'Nome da doenca ou transtorno em portugues';


-- ======================================================================
-- ORIGEM: sql/02_ddl_json.sql
-- ======================================================================

-- ===========================================================================
-- SYNODOS | 02 - MODELO SEMIESTRUTURADO / JSON (FONTE 2: CNES)
-- Oracle Autonomous Database - suporte JSON nativo
-- ---------------------------------------------------------------------------
-- POR QUE JSON AQUI E NAO UMA TABELA RELACIONAL:
--
-- A API do CNES devolve documentos cujo schema muda entre competencias:
-- campos de habilitacao, equipes e servicos especializados aparecem e
-- desaparecem conforme a unidade. Modelar isso em colunas fixas obrigaria
-- a alterar a tabela a cada mudanca do Ministerio da Saude e perderia
-- informacao no caminho.
--
-- Guardamos o documento original em coluna JSON nativa e projetamos apenas
-- os campos estaveis para a dimensao relacional. O Oracle indexa e consulta
-- o JSON com a MESMA linguagem SQL usada nas tabelas relacionais - que e
-- exatamente o argumento de unificacao do projeto.
-- ===========================================================================

-- ---------------------------------------------- TABELA DE DOCUMENTOS JSON
CREATE TABLE cnes_documento (
    id_documento    NUMBER GENERATED ALWAYS AS IDENTITY,
    co_cnes         CHAR(7),
    sg_uf           CHAR(2),
    dt_carga        TIMESTAMP DEFAULT SYSTIMESTAMP,
    documento       JSON,                      -- 23ai: tipo JSON nativo
    CONSTRAINT pk_cnes_documento PRIMARY KEY (id_documento)
);

-- Compatibilidade 19c: se o tipo JSON nativo nao existir, use
--   documento CLOB CONSTRAINT ck_cnes_json CHECK (documento IS JSON)

COMMENT ON TABLE cnes_documento IS
    'Documentos JSON originais da API do CNES, preservados sem perda de schema';

-- ------------------------------------------------------ INDICE DE BUSCA
-- Indice de pesquisa JSON: acelera consultas por qualquer chave do documento
CREATE SEARCH INDEX ix_cnes_json ON cnes_documento (documento) FOR JSON;

-- Indice funcional sobre um campo especifico muito consultado
CREATE INDEX ix_cnes_json_tipo ON cnes_documento (
    JSON_VALUE(documento, '$.co_tipo_unidade' RETURNING VARCHAR2(2))
);

-- ===========================================================================
-- CONSULTANDO O JSON COM SQL PADRAO
-- ===========================================================================

-- (a) Notacao simplificada de ponto - acessa o documento como objeto
CREATE OR REPLACE VIEW vw_cnes_json AS
SELECT
    d.co_cnes,
    d.sg_uf,
    JSON_VALUE(d.documento, '$.nm_estabelecimento'
               RETURNING VARCHAR2(200))          AS nm_estabelecimento,
    JSON_VALUE(d.documento, '$.ds_tipo_unidade'
               RETURNING VARCHAR2(80))           AS ds_tipo_unidade,
    JSON_VALUE(d.documento, '$.co_tipo_unidade'
               RETURNING VARCHAR2(2))            AS co_tipo_unidade,
    JSON_VALUE(d.documento, '$.qt_leitos_sus'
               RETURNING NUMBER)                 AS qt_leitos_sus,
    JSON_VALUE(d.documento, '$.co_municipio'
               RETURNING VARCHAR2(10))           AS co_municipio
FROM cnes_documento d;

COMMENT ON TABLE vw_cnes_json IS
    'Projecao relacional do documento JSON do CNES - permite juncao com o SIH';

-- (b) JSON_TABLE - transforma o documento em linhas relacionais on the fly
CREATE OR REPLACE VIEW vw_cnes_tabular AS
SELECT jt.*
FROM cnes_documento d,
     JSON_TABLE(
         d.documento, '$'
         COLUMNS (
             co_cnes            VARCHAR2(7)   PATH '$.co_cnes',
             nm_estabelecimento VARCHAR2(200) PATH '$.nm_estabelecimento',
             sg_uf              VARCHAR2(2)   PATH '$.sg_uf',
             co_municipio       VARCHAR2(10)  PATH '$.co_municipio',
             ds_tipo_unidade    VARCHAR2(80)  PATH '$.ds_tipo_unidade',
             qt_leitos_sus      NUMBER        PATH '$.qt_leitos_sus'
         )
     ) jt;

-- ===========================================================================
-- A CONSULTA QUE PROVA A UNIFICACAO DOS TRES FORMATOS
-- ---------------------------------------------------------------------------
-- Um unico SELECT cruzando:
--   fato_internacao   -> tabela RELACIONAL  (SIH/SUS)
--   cnes_documento    -> documento JSON     (CNES)
--   ext_populacao_uf  -> arquivo CSV        (external table, IBGE)
-- ===========================================================================
CREATE OR REPLACE VIEW vw_integracao_tres_formatos AS
SELECT
    f.sg_uf,
    t.nm_uf,
    t.regiao,
    JSON_VALUE(c.documento, '$.ds_tipo_unidade'
               RETURNING VARCHAR2(80))            AS tipo_unidade,
    COUNT(*)                                      AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)          AS permanencia_media,
    SUM(JSON_VALUE(c.documento, '$.qt_leitos_sus' RETURNING NUMBER))
                                                  AS leitos_referenciados,
    ROUND(COUNT(*) / MAX(t.populacao_2022) * 10000, 2)
                                                  AS internacoes_por_10k
FROM fato_internacao f
JOIN cnes_documento  c ON c.co_cnes = f.co_cnes      -- relacional x JSON
JOIN dim_territorio  t ON t.sg_uf  = f.sg_uf         -- relacional x CSV
GROUP BY
    f.sg_uf, t.nm_uf, t.regiao,
    JSON_VALUE(c.documento, '$.ds_tipo_unidade' RETURNING VARCHAR2(80));

COMMENT ON TABLE vw_integracao_tres_formatos IS
    'Demonstra em uma unica consulta SQL a integracao dos tres formatos: relacional (SIH), JSON (CNES) e CSV externo (IBGE)';


-- ======================================================================
-- ORIGEM: sql/04_views_analiticas.sql
-- ======================================================================

-- ===========================================================================
-- SYNODOS | 04 - CAMADA ANALITICA (VIEWS E INDICADORES)
-- ---------------------------------------------------------------------------
-- Views curadas que o dashboard e o Select AI consomem. Nomes de colunas em
-- portugues e autoexplicativos: e o vocabulario que o modelo de linguagem
-- usa para traduzir a pergunta do gestor em SQL.
-- ===========================================================================

-- ------------------------------------------------- 1. PANORAMA CONSOLIDADO
CREATE OR REPLACE VIEW vw_panorama_geral AS
SELECT
    COUNT(*)                                        AS total_internacoes,
    COUNT(DISTINCT f.competencia)                   AS competencias_analisadas,
    COUNT(DISTINCT f.co_cnes)                       AS estabelecimentos_ativos,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media_dias,
    MEDIAN(f.qt_dias_permanencia)                   AS permanencia_mediana_dias,
    ROUND(AVG(f.nu_idade), 1)                       AS idade_media,
    ROUND(SUM(f.fl_obito) / COUNT(*) * 100, 2)      AS taxa_mortalidade_pct,
    ROUND(SUM(f.fl_permanencia_prolongada) / COUNT(*) * 100, 1)
                                                    AS internacoes_longas_pct,
    ROUND(SUM(f.vl_total_aih), 2)                   AS custo_total_reais,
    ROUND(AVG(f.vl_total_aih), 2)                   AS custo_medio_aih_reais
FROM fato_internacao f;

-- --------------------------------------------------- 2. SERIE TEMPORAL
CREATE OR REPLACE VIEW vw_serie_temporal AS
SELECT
    f.competencia,
    t.ano,
    t.mes,
    t.dt_competencia,
    COUNT(*)                                     AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)         AS permanencia_media,
    SUM(f.fl_obito)                              AS qt_obitos,
    ROUND(SUM(f.vl_total_aih), 2)                AS custo_total,
    -- media movel de 3 competencias (funcao analitica)
    ROUND(AVG(COUNT(*)) OVER (
        ORDER BY f.competencia ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 1)                                        AS media_movel_3m,
    -- variacao percentual sobre a competencia anterior
    ROUND(
        (COUNT(*) - LAG(COUNT(*)) OVER (ORDER BY f.competencia))
        / NULLIF(LAG(COUNT(*)) OVER (ORDER BY f.competencia), 0) * 100
    , 2)                                         AS variacao_mensal_pct
FROM fato_internacao f
JOIN dim_tempo t ON t.competencia = f.competencia
GROUP BY f.competencia, t.ano, t.mes, t.dt_competencia;

-- --------------------------------------- 3. TAXA POR 10 MIL HABITANTES
CREATE OR REPLACE VIEW vw_taxa_por_uf AS
SELECT
    t.sg_uf,
    t.nm_uf,
    t.regiao,
    t.populacao_2022,
    COUNT(*)                                          AS qt_internacoes,
    ROUND(
        COUNT(*) / t.populacao_2022 * 10000
        / (COUNT(DISTINCT f.competencia) / 12)
    , 2)                                              AS internacoes_por_10k_ano,
    ROUND(AVG(f.qt_dias_permanencia), 1)              AS permanencia_media,
    ROUND(SUM(f.vl_total_aih) / t.populacao_2022, 2)  AS custo_per_capita,
    ROUND(SUM(f.fl_obito) / COUNT(*) * 100, 2)        AS taxa_mortalidade_pct
FROM fato_internacao f
JOIN dim_territorio t ON t.sg_uf = f.sg_uf
GROUP BY t.sg_uf, t.nm_uf, t.regiao, t.populacao_2022;

-- ------------------------------------------------ 4. PERFIL DIAGNOSTICO
CREATE OR REPLACE VIEW vw_perfil_diagnostico AS
SELECT
    f.cid_grupo,
    c.descricao,
    c.grupo_cid,
    c.gravidade_relativa,
    COUNT(*)                                        AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media,
    SUM(f.qt_dias_permanencia)                      AS dias_leito_consumidos,
    ROUND(AVG(f.nu_idade), 1)                       AS idade_media,
    ROUND(SUM(f.vl_total_aih), 2)                   AS custo_total,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER () * 100, 2)
                                                    AS pct_internacoes,
    ROUND(
        RATIO_TO_REPORT(SUM(f.qt_dias_permanencia)) OVER () * 100
    , 2)                                            AS pct_dias_leito
FROM fato_internacao f
LEFT JOIN dim_cid10 c ON c.cid10 = f.cid_grupo
GROUP BY f.cid_grupo, c.descricao, c.grupo_cid, c.gravidade_relativa;

-- ------------------------------------------------- 5. OCUPACAO DA REDE
CREATE OR REPLACE VIEW vw_ocupacao_rede AS
WITH demanda AS (
    SELECT
        f.sg_uf,
        SUM(f.qt_dias_permanencia)     AS dias_paciente,
        COUNT(*)                       AS qt_internacoes,
        COUNT(DISTINCT f.competencia)  AS qt_competencias
    FROM fato_internacao f
    GROUP BY f.sg_uf
),
rede AS (
    SELECT
        e.sg_uf,
        SUM(e.qt_leitos_sus)                                  AS qt_leitos,
        COUNT(*)                                              AS qt_unidades,
        SUM(CASE WHEN e.ds_tipo_unidade = 'CAPS' THEN 1 ELSE 0 END)
                                                              AS qt_caps
    FROM dim_estabelecimento e
    GROUP BY e.sg_uf
)
SELECT
    d.sg_uf,
    t.nm_uf,
    t.regiao,
    d.qt_internacoes,
    r.qt_leitos,
    r.qt_caps,
    r.qt_unidades,
    ROUND(
        d.dias_paciente / NULLIF(r.qt_leitos * d.qt_competencias * 30.44, 0)
        * 100
    , 1)                                            AS taxa_ocupacao_pct,
    ROUND(r.qt_leitos / t.populacao_2022 * 10000, 2)
                                                    AS leitos_por_10k_hab,
    ROUND(r.qt_caps / t.populacao_2022 * 100000, 2)
                                                    AS caps_por_100k_hab
FROM demanda d
JOIN rede r          ON r.sg_uf = d.sg_uf
JOIN dim_territorio t ON t.sg_uf = d.sg_uf;

-- --------------------------- 6. INDICE DE PRESSAO ASSISTENCIAL (IPA)
-- Indicador composto proprio: normaliza tres dimensoes entre 0 e 100 e
-- pondera demanda (50%), complexidade (30%) e escassez de leitos (20%).
CREATE OR REPLACE VIEW vw_pressao_assistencial AS
WITH base AS (
    SELECT
        x.sg_uf, x.nm_uf, x.regiao,
        x.internacoes_por_10k_ano,
        x.permanencia_media,
        o.leitos_por_10k_hab,
        o.taxa_ocupacao_pct,
        o.qt_leitos,
        o.qt_caps,
        x.qt_internacoes
    FROM vw_taxa_por_uf x
    JOIN vw_ocupacao_rede o ON o.sg_uf = x.sg_uf
),
limites AS (
    SELECT
        MIN(internacoes_por_10k_ano) AS min_dem,
        MAX(internacoes_por_10k_ano) AS max_dem,
        MIN(permanencia_media)       AS min_perm,
        MAX(permanencia_media)       AS max_perm,
        MIN(leitos_por_10k_hab)      AS min_leito,
        MAX(leitos_por_10k_hab)      AS max_leito
    FROM base
),
normalizado AS (
    SELECT
        b.*,
        ROUND((b.internacoes_por_10k_ano - l.min_dem)
              / NULLIF(l.max_dem - l.min_dem, 0) * 100, 1) AS n_demanda,
        ROUND((b.permanencia_media - l.min_perm)
              / NULLIF(l.max_perm - l.min_perm, 0) * 100, 1) AS n_complexidade,
        ROUND(100 - (b.leitos_por_10k_hab - l.min_leito)
              / NULLIF(l.max_leito - l.min_leito, 0) * 100, 1) AS n_escassez
    FROM base b CROSS JOIN limites l
)
SELECT
    n.*,
    ROUND(
        n.n_demanda * 0.5 + n.n_complexidade * 0.3 + n.n_escassez * 0.2
    , 1)                                              AS indice_pressao,
    CASE
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 75 THEN 'Critica'
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 50 THEN 'Alta'
        WHEN n.n_demanda * 0.5 + n.n_complexidade * 0.3
           + n.n_escassez * 0.2 >= 25 THEN 'Moderada'
        ELSE 'Baixa'
    END                                               AS classificacao,
    RANK() OVER (
        ORDER BY n.n_demanda * 0.5 + n.n_complexidade * 0.3
               + n.n_escassez * 0.2 DESC
    )                                                 AS ranking
FROM normalizado n;

-- ------------------------------------- 7. RANKING DE UNIDADES CRITICAS
CREATE OR REPLACE VIEW vw_ranking_unidades AS
SELECT
    e.co_cnes,
    e.nm_estabelecimento,
    e.ds_tipo_unidade,
    e.sg_uf,
    e.qt_leitos_sus,
    COUNT(*)                                        AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)            AS permanencia_media,
    SUM(f.qt_dias_permanencia)                      AS dias_leito,
    ROUND(
        SUM(f.qt_dias_permanencia)
        / NULLIF(e.qt_leitos_sus * COUNT(DISTINCT f.competencia) * 30.44, 0)
        * 100
    , 1)                                            AS ocupacao_estimada_pct,
    RANK() OVER (ORDER BY COUNT(*) DESC)            AS ranking_volume
FROM fato_internacao f
JOIN dim_estabelecimento e ON e.co_cnes = f.co_cnes
WHERE e.qt_leitos_sus > 0
GROUP BY e.co_cnes, e.nm_estabelecimento, e.ds_tipo_unidade,
         e.sg_uf, e.qt_leitos_sus;

-- --------------------------------------------- 8. PERFIL DEMOGRAFICO
CREATE OR REPLACE VIEW vw_perfil_demografico AS
SELECT
    f.faixa_etaria,
    f.ds_sexo,
    COUNT(*)                                    AS qt_internacoes,
    ROUND(AVG(f.qt_dias_permanencia), 1)        AS permanencia_media,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER () * 100, 2) AS pct
FROM fato_internacao f
GROUP BY f.faixa_etaria, f.ds_sexo;

-- ------------------------------------------------------- COMENTARIOS
COMMENT ON TABLE vw_pressao_assistencial IS
    'Indice de Pressao Assistencial por UF: quanto maior, mais sobrecarregada a rede de saude mental e maior a prioridade de investimento';
COMMENT ON TABLE vw_taxa_por_uf IS
    'Internacoes por 10 mil habitantes por ano em cada estado, permitindo comparacao justa entre UFs de tamanhos diferentes';
COMMENT ON TABLE vw_ocupacao_rede IS
    'Taxa de ocupacao dos leitos de saude mental e densidade de CAPS por estado';


-- ===========================================================================
-- VERIFICACAO - rode depois de tudo, deve devolver as tabelas e as views
-- ===========================================================================
SELECT table_name FROM user_tables ORDER BY table_name;
SELECT view_name  FROM user_views  ORDER BY view_name;

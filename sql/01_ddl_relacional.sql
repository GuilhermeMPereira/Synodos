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

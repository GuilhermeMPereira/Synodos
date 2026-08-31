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

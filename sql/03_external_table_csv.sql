-- ===========================================================================
-- SYNODOS | 03 - EXTERNAL TABLES / CSV (FONTE 3: IBGE e CID-10)
-- Oracle Autonomous Database + OCI Object Storage
-- ---------------------------------------------------------------------------
-- POR QUE CSV COMO EXTERNAL TABLE:
--
-- Populacao (Censo IBGE) e a tabela CID-10 sao dados de referencia: mudam
-- raramente, sao pequenos e vem publicados como CSV. Carregar fisicamente
-- seria trabalho de manutencao sem beneficio.
--
-- A EXTERNAL TABLE deixa o arquivo no Object Storage e o consulta por SQL
-- sob demanda. Atualizar o indicador passa a ser trocar o arquivo no
-- bucket - sem ETL, sem recarga, sem janela de indisponibilidade.
-- ===========================================================================

-- ------------------------------------------------------------- PASSO 1
-- Credencial de acesso ao bucket do OCI Object Storage.
-- Use um Auth Token gerado no perfil do usuario OCI (nao a senha da conta).
BEGIN
    DBMS_CLOUD.CREATE_CREDENTIAL(
        credential_name => 'CRED_SYNODOS_OBJ',
        username        => 'oracleidentitycloudservice/seu.email@dominio.com',
        password        => 'SEU_AUTH_TOKEN_AQUI'
    );
END;
/

-- ------------------------------------------------------------- PASSO 2
-- Envie os CSV para o bucket:
--   data/reference/uf_populacao.csv
--   data/reference/cid10_saude_mental.csv
-- Pelo console OCI ou pela CLI:
--   oci os object put -bns <namespace> -bn synodos-data \
--       --file data/reference/uf_populacao.csv

-- ------------------------------------------------------------- PASSO 3
-- External table de populacao por UF (denominador das taxas)
BEGIN
    DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
        table_name      => 'EXT_POPULACAO_UF',
        credential_name => 'CRED_SYNODOS_OBJ',
        file_uri_list   =>
            'https://objectstorage.<regiao>.oraclecloud.com/n/<namespace>/'
         || 'b/synodos-data/o/uf_populacao.csv',
        format          => JSON_OBJECT(
            'type'             VALUE 'csv',
            'delimiter'        VALUE ';',
            'skipheaders'      VALUE '1',
            'ignoremissingcolumns' VALUE 'true',
            'characterset'     VALUE 'AL32UTF8',
            'rejectlimit'      VALUE '10'
        ),
        column_list     =>
            'co_uf          VARCHAR2(2),
             sg_uf          VARCHAR2(2),
             nm_uf          VARCHAR2(60),
             regiao         VARCHAR2(20),
             populacao_2022 NUMBER'
    );
END;
/

-- External table da classificacao CID-10 (Capitulo V)
BEGIN
    DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
        table_name      => 'EXT_CID10',
        credential_name => 'CRED_SYNODOS_OBJ',
        file_uri_list   =>
            'https://objectstorage.<regiao>.oraclecloud.com/n/<namespace>/'
         || 'b/synodos-data/o/cid10_saude_mental.csv',
        format          => JSON_OBJECT(
            'type'         VALUE 'csv',
            'delimiter'    VALUE ';',
            'skipheaders'  VALUE '1',
            'characterset' VALUE 'AL32UTF8'
        ),
        column_list     =>
            'cid10                     VARCHAR2(3),
             grupo_cid                 VARCHAR2(10),
             descricao                 VARCHAR2(200),
             gravidade_relativa        VARCHAR2(10),
             permanencia_esperada_dias NUMBER'
    );
END;
/

-- ------------------------------------------------------------- PASSO 4
-- Validacao da leitura externa
SELECT COUNT(*) AS qt_ufs,
       SUM(populacao_2022) AS populacao_total
FROM   ext_populacao_uf;
-- Esperado: 27 UFs, aproximadamente 203 milhoes de habitantes

SELECT * FROM ext_cid10 ORDER BY cid10 FETCH FIRST 10 ROWS ONLY;

-- ------------------------------------------------------------- PASSO 5
-- Materializacao opcional na dimensao relacional.
-- Mantemos as duas formas de proposito: a external table prova a leitura
-- direta do CSV; a dimensao materializada acelera os joins do painel.
INSERT INTO dim_territorio (
    sk_territorio, co_uf, sg_uf, nm_uf, regiao,
    populacao_2022, populacao_regiao
)
SELECT
    ROW_NUMBER() OVER (ORDER BY e.co_uf),
    e.co_uf, e.sg_uf, e.nm_uf, e.regiao, e.populacao_2022,
    SUM(e.populacao_2022) OVER (PARTITION BY e.regiao)
FROM ext_populacao_uf e;

COMMIT;

-- ---------------------------------------------------------------------------
-- ALTERNATIVA: carga direta de CSV sem external table
-- Util quando o arquivo e grande e sera consultado com frequencia.
-- ---------------------------------------------------------------------------
-- BEGIN
--     DBMS_CLOUD.COPY_DATA(
--         table_name      => 'DIM_TERRITORIO',
--         credential_name => 'CRED_SYNODOS_OBJ',
--         file_uri_list   => 'https://.../uf_populacao.csv',
--         format          => JSON_OBJECT('type' VALUE 'csv',
--                                        'delimiter' VALUE ';',
--                                        'skipheaders' VALUE '1')
--     );
-- END;
-- /

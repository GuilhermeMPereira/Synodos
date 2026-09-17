-- ===========================================================================
-- SYNODOS | 07 - CONSULTAS DE DEMONSTRACAO PARA O DATABASE ACTIONS
-- ---------------------------------------------------------------------------
-- Este arquivo existe para a gravacao do video e para os prints do slide 22.
-- Nao faz parte do pipeline: nao cria nem altera nada, so consulta.
--
-- COMO RODAR NO DATABASE ACTIONS
--
--   O editor tem dois botoes. "Run Statement" (Ctrl+Enter) roda UMA
--   instrucao - a que estiver sob o cursor. "Run Script" (F5) roda tudo.
--
--   Para a gravacao, use Run Statement, uma consulta de cada vez: o
--   resultado aparece na grade de baixo, que e o que fica bonito no video.
--   Se usar F5 com o arquivo inteiro, a saida vira texto corrido.
--
--   Conecte como ADMIN.
-- ===========================================================================


-- ###########################################################################
-- 1. O QUE ESTA CARREGADO
--    Abre a demonstracao provando que o banco tem dados de verdade.
-- ###########################################################################

SELECT 'fato_internacao'      AS objeto, COUNT(*) AS registros FROM fato_internacao
UNION ALL
SELECT 'dim_estabelecimento',        COUNT(*) FROM dim_estabelecimento
UNION ALL
SELECT 'cnes_documento (JSON)',      COUNT(*) FROM cnes_documento
UNION ALL
SELECT 'dim_territorio (CSV IBGE)',  COUNT(*) FROM dim_territorio
UNION ALL
SELECT 'dim_cid10 (CSV OMS)',        COUNT(*) FROM dim_cid10
UNION ALL
SELECT 'dim_tempo',                  COUNT(*) FROM dim_tempo
ORDER BY registros DESC;


-- ###########################################################################
-- 2. OS TRES FORMATOS NUMA CONSULTA SO
--    Esta e a consulta mais importante do video.
--
--    fato_internacao   -> tabela RELACIONAL   (SIH/SUS)
--    cnes_documento    -> coluna JSON nativa  (API do CNES)
--    dim_territorio    -> veio do CSV do IBGE
--
--    Um SQL so, tres formatos. E o argumento central do projeto.
-- ###########################################################################

SELECT
    sg_uf,
    nm_uf,
    regiao,
    tipo_unidade,
    qt_internacoes,
    permanencia_media,
    leitos_referenciados,
    internacoes_por_10k
FROM   vw_integracao_tres_formatos
ORDER  BY qt_internacoes DESC
FETCH FIRST 12 ROWS ONLY;


-- ###########################################################################
-- 3. O JSON POR DENTRO
--    Mostra que o documento do CNES esta inteiro no banco, e que o Oracle
--    le atributo por atributo com JSON_VALUE - sem coluna fixa nenhuma.
--
--    Rode esta quando quiser justificar a escolha do JSON no video.
-- ###########################################################################

SELECT
    co_cnes,
    JSON_VALUE(documento, '$.nm_estabelecimento' RETURNING VARCHAR2(60)) AS estabelecimento,
    JSON_VALUE(documento, '$.sg_uf'              RETURNING VARCHAR2(2))  AS uf,
    JSON_VALUE(documento, '$.ds_tipo_unidade'    RETURNING VARCHAR2(40)) AS tipo,
    JSON_VALUE(documento, '$.qt_leitos_sus'      RETURNING NUMBER)       AS leitos
FROM   cnes_documento
WHERE  JSON_VALUE(documento, '$.qt_leitos_sus' RETURNING NUMBER) > 0
ORDER  BY leitos DESC
FETCH FIRST 10 ROWS ONLY;


-- ###########################################################################
-- 4. O INDICADOR PROPRIO - INDICE DE PRESSAO ASSISTENCIAL
--    Serve para o print do slide 22 ("consulta SQL executada no Oracle e
--    indicador calculado como resultado").
--
--    Repare que a formula 0,5 demanda + 0,3 complexidade + 0,2 escassez
--    esta calculada dentro da view, em SQL - nao no Python.
-- ###########################################################################

SELECT
    ranking,
    sg_uf,
    nm_uf,
    regiao,
    internacoes_por_10k_ano,
    permanencia_media,
    leitos_por_10k_hab,
    indice_pressao,
    classificacao
FROM   vw_pressao_assistencial
ORDER  BY ranking
FETCH FIRST 10 ROWS ONLY;


-- ###########################################################################
-- 5. O ACHADO DA ESQUIZOFRENIA
--    19% das internacoes, 30% dos dias de leito. O numero que sustenta a
--    tese do projeto, calculado no proprio banco.
-- ###########################################################################

SELECT
    cid_grupo,
    descricao,
    qt_internacoes,
    pct_internacoes,
    dias_leito_consumidos,
    pct_dias_leito,
    ROUND(pct_dias_leito / pct_internacoes, 2) AS indice_carga_leito
FROM   vw_perfil_diagnostico
ORDER  BY qt_internacoes DESC
FETCH FIRST 8 ROWS ONLY;


-- ===========================================================================
-- SELECT AI
-- ---------------------------------------------------------------------------
-- ATENCAO, e o erro que mais custa tempo aqui:
--
--   O atalho  SELECT AI narrate ...  NAO e SQL. Quem o traduz e o CLIENTE,
--   antes de mandar para o banco. O Database Actions nao faz essa traducao
--   de forma confiavel, e quebrar o comando em varias linhas devolve
--   ORA-00923: FROM keyword not found where expected.
--
--   Por isso as consultas abaixo usam DBMS_CLOUD_AI.GENERATE, que e uma
--   funcao PL/SQL de verdade e funciona em qualquer cliente. O resultado
--   e exatamente o mesmo.
-- ===========================================================================


-- ###########################################################################
-- 6. CONFERIR QUE O PERFIL EXISTE
--    Rode isto ANTES de gravar. Se nao voltar linha, o perfil nao foi
--    criado - rode o sql/05_select_ai_setup.sql primeiro.
-- ###########################################################################

SELECT profile_name, status
FROM   user_cloud_ai_profiles;

EXEC DBMS_CLOUD_AI.SET_PROFILE('SYNODOS_AI');


-- ###########################################################################
-- 7. SELECT AI - MOSTRAR O SQL GERADO   <<< O MOMENTO MAIS FORTE DO VIDEO
--
--    O modelo recebe a pergunta em portugues e devolve a CONSULTA.
--    Nao devolve numero nenhum. Quem produz o numero e o banco.
--
--    Deixe o SQL na tela por tres segundos antes de rodar o passo 8.
-- ###########################################################################

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Qual o custo medio por internacao em cada regiao',
           profile_name => 'SYNODOS_AI',
           action       => 'showsql'
       ) AS sql_gerado
FROM   DUAL;


-- ###########################################################################
-- 8. SELECT AI - EXECUTAR E TRAZER OS DADOS
--    A mesma pergunta, agora com o banco executando o SQL do passo 7.
-- ###########################################################################

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Qual o custo medio por internacao em cada regiao',
           profile_name => 'SYNODOS_AI',
           action       => 'runsql'
       ) AS resposta
FROM   DUAL;


-- ###########################################################################
-- 9. SELECT AI - A PERGUNTA QUE PROVA O VALOR DOS COMENTARIOS
--
--    Em lugar nenhum do banco existe a palavra "esquizofrenia" como dado.
--    Ela aparece so no COMMENT ON da coluna cid_grupo. E por isso que o
--    modelo consegue traduzir a pergunta para F20.
--
--    Se alguem perguntar por que os COMMENT ON importam, a resposta e esta.
-- ###########################################################################

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Quantas internacoes por esquizofrenia ocorreram em Sao Paulo',
           profile_name => 'SYNODOS_AI',
           action       => 'showsql'
       ) AS sql_gerado
FROM   DUAL;


-- ###########################################################################
-- 10. SELECT AI - RESPOSTA EM TEXTO CORRIDO
--     Bom para fechar a demonstracao: o gestor le a frase, nao a tabela.
-- ###########################################################################

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Quais estados estao com maior pressao assistencial e por que',
           profile_name => 'SYNODOS_AI',
           action       => 'narrate'
       ) AS resposta
FROM   DUAL;


-- ===========================================================================
-- SE ALGO FALHAR NA HORA
--
--   ORA-00923            usou o atalho SELECT AI. Use GENERATE, acima.
--   ORA-20404            o object_list aponta para view que nao existe.
--                        Rode o sql/04 (ou o sql/00_setup_rapido).
--   ORA-20401            a politica IAM nao propagou. Espere e repita.
--   Perfil nao existe    rode o sql/05_select_ai_setup.sql.
--   Banco parado         Always Free hiberna com 7 dias sem uso.
--                        Start no console OCI e espere ficar Available.
-- ===========================================================================

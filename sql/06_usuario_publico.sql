-- ===========================================================================
-- SYNODOS | 06 - USUARIO SOMENTE LEITURA PARA O APP PUBLICO
-- Executar conectado como ADMIN
-- ---------------------------------------------------------------------------
-- POR QUE ESTE ARQUIVO EXISTE
--
-- Para o painel publicado responder perguntas com o Select AI, ele precisa
-- de credenciais do banco. Usar o ADMIN seria um erro grave: o Select AI
-- gera SQL a partir de texto livre do usuario, e alguem poderia induzir o
-- modelo a escrever um DROP ou um DELETE.
--
-- A defesa nao e filtrar a pergunta - e tirar o poder. Este usuario so tem
-- SELECT, e apenas sobre as views agregadas. Mesmo que o modelo gere um
-- comando destrutivo, o banco recusa por falta de privilegio.
-- ===========================================================================

-- ------------------------------------------------------------- PASSO 1
-- Criar o usuario. Troque a senha: 12 a 30 caracteres, com maiuscula,
-- minuscula e numero, sem aspas duplas e sem a palavra "admin".
CREATE USER synodos_app IDENTIFIED BY "TrocarEstaSenhaApp123";

GRANT CREATE SESSION TO synodos_app;

-- ------------------------------------------------------------- PASSO 2
-- Somente leitura, e somente sobre as views analiticas.
-- As tabelas cruas NAO sao expostas: alem da seguranca, os nomes de
-- coluna em portugues das views elevam a qualidade do SQL gerado.
GRANT SELECT ON vw_panorama_geral       TO synodos_app;
GRANT SELECT ON vw_serie_temporal       TO synodos_app;
GRANT SELECT ON vw_taxa_por_uf          TO synodos_app;
GRANT SELECT ON vw_perfil_diagnostico   TO synodos_app;
GRANT SELECT ON vw_ocupacao_rede        TO synodos_app;
GRANT SELECT ON vw_pressao_assistencial TO synodos_app;
GRANT SELECT ON vw_ranking_unidades     TO synodos_app;
GRANT SELECT ON vw_perfil_demografico   TO synodos_app;

-- Note o que NAO foi concedido: nenhum INSERT, UPDATE, DELETE ou DROP,
-- e nenhum acesso a FATO_INTERNACAO ou as demais tabelas.

-- ------------------------------------------------------------- PASSO 3
-- Permitir que o usuario use o Select AI
GRANT EXECUTE ON DBMS_CLOUD_AI TO synodos_app;
EXEC DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL(username => 'SYNODOS_APP');

-- ------------------------------------------------------------- PASSO 4
-- Perfil de IA proprio do usuario publico, restrito as mesmas views.
-- Rodar CONECTADO COMO SYNODOS_APP.
--
-- BEGIN
--     DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'SYNODOS_AI', force => TRUE);
--
--     DBMS_CLOUD_AI.CREATE_PROFILE(
--         profile_name => 'SYNODOS_AI',
--         attributes   => '{
--             "provider":        "oci",
--             "credential_name": "OCI$RESOURCE_PRINCIPAL",
--             "region":          "sa-saopaulo-1",
--             "comments":        "true",
--             "object_list": [
--                 {"owner": "ADMIN", "name": "VW_PANORAMA_GERAL"},
--                 {"owner": "ADMIN", "name": "VW_SERIE_TEMPORAL"},
--                 {"owner": "ADMIN", "name": "VW_TAXA_POR_UF"},
--                 {"owner": "ADMIN", "name": "VW_PERFIL_DIAGNOSTICO"},
--                 {"owner": "ADMIN", "name": "VW_OCUPACAO_REDE"},
--                 {"owner": "ADMIN", "name": "VW_PRESSAO_ASSISTENCIAL"},
--                 {"owner": "ADMIN", "name": "VW_RANKING_UNIDADES"},
--                 {"owner": "ADMIN", "name": "VW_PERFIL_DEMOGRAFICO"}
--             ]
--         }'
--     );
-- END;
-- /

-- ------------------------------------------------------------- PASSO 5
-- Habilitar o usuario no Database Actions, para conseguir conectar por la
-- e rodar o passo 4. (Executar como ADMIN.)
BEGIN
    ORDS_ADMIN.ENABLE_SCHEMA(
        p_enabled             => TRUE,
        p_schema              => 'SYNODOS_APP',
        p_url_mapping_type    => 'BASE_PATH',
        p_url_mapping_pattern => 'synodosapp',
        p_auto_rest_auth      => TRUE
    );
    COMMIT;
END;
/

-- ------------------------------------------------------------- PASSO 6
-- Conferir que o usuario so enxerga as views, e nada mais.
-- Rodar CONECTADO COMO SYNODOS_APP:
--
--   SELECT table_name, privilege FROM user_tab_privs_recd ORDER BY table_name;
--   SELECT COUNT(*) FROM admin.vw_pressao_assistencial;   -- deve funcionar
--   DELETE FROM admin.fato_internacao;                    -- deve dar ORA-00942

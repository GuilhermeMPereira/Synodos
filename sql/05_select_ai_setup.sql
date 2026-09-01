-- ===========================================================================
-- SYNODOS | 05 - ORACLE SELECT AI
-- Perguntas em portugues sobre a rede de saude mental, sem escrever SQL
-- ---------------------------------------------------------------------------
-- Este script aplica ao dominio do Synodos o procedimento ensinado no
-- Oracle LiveLabs "Chat with Your Data in Autonomous AI Database Using
-- Select AI" (workshop 4222). O lab usa o schema de demonstracao
-- MOVIESTREAM; aqui a mesma mecanica opera sobre o schema SYNODOS.
--
-- Equivalencia com o lab:
--   Lab 2 (Integrate GenAI models)  -> PASSOS 1 a 4 deste script
--   Lab 3 (Natural Language Queries)-> PASSOS 5 e 6 deste script
--
-- O Select AI e o diferencial central do projeto: o gestor de saude publica
-- pergunta em linguagem natural, o Oracle usa os metadados do dicionario de
-- dados (nomes de tabelas, colunas e COMMENTs) para gerar o SQL, executa a
-- consulta sobre os dados reais e devolve a resposta.
--
-- Nao ha alucinacao de numeros: o modelo de linguagem escreve a CONSULTA,
-- quem produz o resultado e o banco.
-- ===========================================================================


-- ###########################################################################
-- OPCAO A - OCI GENERATIVE AI  (RECOMENDADA)
-- ---------------------------------------------------------------------------
-- Nao exige chave de API paga: a autenticacao usa o resource principal do
-- proprio Autonomous Database. Exige que a tenancy esteja em uma regiao
-- suportada - "Brazil East (Sao Paulo)" / sa-saopaulo-1 esta na lista.
-- ###########################################################################

-- ------------------------------------------------------------- PASSO 1
-- Politica IAM (no console OCI, em Identity > Policies).
-- Autoriza o Autonomous Database a chamar o servico de IA generativa.
--
--   allow any-user to manage generative-ai-family in compartment <compartimento>
--   where request.principal.type = 'autonomousdatabase'

-- ------------------------------------------------------------- PASSO 2
-- Resource principal (executar conectado como ADMIN).
-- E o que faz existir a credencial OCI$RESOURCE_PRINCIPAL, que dispensa
-- chave de API paga.
EXEC DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL();

-- Se voce criou um usuario separado para o projeto, habilite tambem nele e
-- conceda as permissoes. Usando o proprio ADMIN (caminho do setup rapido),
-- as duas linhas abaixo sao desnecessarias.
-- GRANT EXECUTE ON DBMS_CLOUD_AI TO synodos;
-- GRANT EXECUTE ON DBMS_CLOUD    TO synodos;
-- EXEC DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL(username => 'SYNODOS');

-- Confere se a credencial ficou disponivel
SELECT credential_name, username, comments
FROM   all_credentials
WHERE  credential_name = 'OCI$RESOURCE_PRINCIPAL';

-- ------------------------------------------------------------- PASSO 3
-- Perfil de IA: define QUAIS objetos o modelo pode enxergar.
--
-- Duas decisoes de projeto aqui, e vale explica-las na banca:
--
--   1. Expomos as VIEWS analiticas, nao as tabelas cruas. Os nomes de
--      colunas em portugues elevam muito a qualidade do SQL gerado, e a
--      superficie de dados exposta ao modelo fica restrita ao que ja e
--      agregado.
--   2. "comments":"true" faz o Oracle enviar ao modelo os COMMENT ON que
--      escrevemos em 01_ddl_relacional.sql. Sem isso o modelo nao sabe que
--      F20 e esquizofrenia, e a taxa de acerto despenca.
--
-- Os "owner" abaixo estao como ADMIN, que e onde o setup rapido
-- (sql/00_setup_rapido.sql) cria os objetos. Se voce usou um usuario
-- SYNODOS separado, troque ADMIN por SYNODOS nas 12 linhas.
BEGIN
    DBMS_CLOUD_AI.DROP_PROFILE(
        profile_name => 'SYNODOS_AI',
        force        => TRUE
    );

    DBMS_CLOUD_AI.CREATE_PROFILE(
        profile_name => 'SYNODOS_AI',
        attributes   => '{
            "provider":        "oci",
            "credential_name": "OCI$RESOURCE_PRINCIPAL",
            "region":          "sa-saopaulo-1",
            "comments":        "true",
            "object_list": [
                {"owner": "ADMIN", "name": "VW_PANORAMA_GERAL"},
                {"owner": "ADMIN", "name": "VW_SERIE_TEMPORAL"},
                {"owner": "ADMIN", "name": "VW_TAXA_POR_UF"},
                {"owner": "ADMIN", "name": "VW_PERFIL_DIAGNOSTICO"},
                {"owner": "ADMIN", "name": "VW_OCUPACAO_REDE"},
                {"owner": "ADMIN", "name": "VW_PRESSAO_ASSISTENCIAL"},
                {"owner": "ADMIN", "name": "VW_RANKING_UNIDADES"},
                {"owner": "ADMIN", "name": "VW_PERFIL_DEMOGRAFICO"},
                {"owner": "ADMIN", "name": "FATO_INTERNACAO"},
                {"owner": "ADMIN", "name": "DIM_TERRITORIO"},
                {"owner": "ADMIN", "name": "DIM_CID10"},
                {"owner": "ADMIN", "name": "DIM_ESTABELECIMENTO"}
            ]
        }'
    );
END;
/

-- ------------------------------------------------------------- PASSO 4
-- Ativar o perfil na sessao e testar
EXEC DBMS_CLOUD_AI.SET_PROFILE('SYNODOS_AI');

SELECT DBMS_CLOUD_AI.GENERATE(
    prompt       => 'o que e o Sistema de Informacoes Hospitalares do SUS',
    profile_name => 'SYNODOS_AI',
    action       => 'chat'
) AS teste
FROM DUAL;


-- ###########################################################################
-- OPCAO B - OPENAI  (alternativa, exige chave de API)
-- ---------------------------------------------------------------------------
-- Use apenas se a tenancy nao estiver em regiao com OCI Generative AI.
-- ###########################################################################

-- B.1 - Liberar a saida de rede para o provedor (como ADMIN)
-- BEGIN
--     DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
--         host => 'api.openai.com',
--         ace  => xs$ace_type(
--             privilege_list => xs$name_list('http'),
--             principal_name => 'SYNODOS',
--             principal_type => xs_acl.ptype_db
--         )
--     );
-- END;
-- /

-- B.2 - Credencial do provedor
-- BEGIN
--     DBMS_CLOUD.CREATE_CREDENTIAL(
--         credential_name => 'CRED_OPENAI_SYNODOS',
--         username        => 'openai',
--         password        => 'SUA_API_KEY_AQUI'
--     );
-- END;
-- /

-- B.3 - Perfil apontando para a OpenAI (mesmo object_list da Opcao A)
-- BEGIN
--     DBMS_CLOUD_AI.DROP_PROFILE(
--         profile_name => 'SYNODOS_AI', force => TRUE);
--
--     DBMS_CLOUD_AI.CREATE_PROFILE(
--         profile_name => 'SYNODOS_AI',
--         attributes   => '{
--             "provider":        "openai",
--             "credential_name": "CRED_OPENAI_SYNODOS",
--             "model":           "gpt-4o-mini",
--             "comments":        "true",
--             "object_list": [
--                 {"owner": "ADMIN", "name": "VW_PRESSAO_ASSISTENCIAL"},
--                 {"owner": "ADMIN", "name": "VW_TAXA_POR_UF"},
--                 {"owner": "ADMIN", "name": "VW_PERFIL_DIAGNOSTICO"},
--                 {"owner": "ADMIN", "name": "VW_OCUPACAO_REDE"},
--                 {"owner": "ADMIN", "name": "VW_SERIE_TEMPORAL"},
--                 {"owner": "ADMIN", "name": "VW_PERFIL_DEMOGRAFICO"},
--                 {"owner": "ADMIN", "name": "FATO_INTERNACAO"},
--                 {"owner": "ADMIN", "name": "DIM_TERRITORIO"},
--                 {"owner": "ADMIN", "name": "DIM_CID10"}
--             ]
--         }'
--     );
-- END;
-- /


-- ===========================================================================
-- PASSO 5 - AS QUATRO ACOES DO SELECT AI
-- ---------------------------------------------------------------------------
--   chat        conversa geral com o modelo, sem consultar os dados
--   runsql      executa e devolve o resultado (acao padrao)
--   showsql     mostra o SQL gerado, sem executar
--   narrate     devolve a resposta em texto corrido
-- ===========================================================================


-- ===========================================================================
-- PASSO 6 - PERGUNTAS DE DEMONSTRACAO (roteiro do video pitch)
-- As quatro acoes acima cobrem tanto a demonstracao quanto a auditoria.
-- ===========================================================================

-- P1. Panorama de abertura
SELECT AI narrate
    Qual o total de internacoes por transtornos mentais e a permanencia media
    em dias no periodo analisado;

-- P2. Comparacao entre estados. O "por 10 mil habitantes" evita a armadilha
--     de comparar Sao Paulo com Espirito Santo em numeros absolutos.
SELECT AI
    Quais os cinco estados com maior numero de internacoes por transtornos
    mentais a cada 10 mil habitantes por ano;

-- P3. Onde investir. Usa o indicador composto criado pelo projeto.
SELECT AI narrate
    Quais estados estao com maior pressao assistencial na rede de saude mental
    e qual a classificacao de cada um;

-- P4. Diagnosticos que mais consomem leito
SELECT AI
    Quais transtornos mentais consomem mais dias de leito e qual a permanencia
    media de cada um;

-- P5. Tendencia temporal
SELECT AI
    Como evoluiu o numero de internacoes por transtornos mentais mes a mes
    e qual competencia teve o maior volume;

-- P6. Cruzamento com a rede instalada
SELECT AI narrate
    Qual estado tem a menor quantidade de leitos de saude mental por 10 mil
    habitantes e quantos CAPS ele possui;

-- P7. Perfil dos pacientes
SELECT AI
    Qual a faixa etaria e o sexo com maior numero de internacoes por
    transtornos mentais;

-- P8. Custo assistencial
SELECT AI
    Qual o custo total das internacoes por transtornos mentais em cada estado
    e o custo per capita;

-- P9. AUDITORIA - o momento mais forte da demonstracao.
--     Mostra ao gestor o SQL que a IA escreveu, em vez de executa-lo.
SELECT AI showsql
    Quais os dez estabelecimentos com maior taxa de ocupacao estimada;

-- P10. Explicacao pedagogica da consulta gerada
SELECT AI explainsql
    Quantas internacoes por esquizofrenia ocorreram em Sao Paulo;


-- ===========================================================================
-- USO PROGRAMATICO (consumido por src/db/select_ai.py e pelo dashboard)
-- ===========================================================================
SELECT DBMS_CLOUD_AI.GENERATE(
    prompt       => 'Quais os cinco estados com maior pressao assistencial',
    profile_name => 'SYNODOS_AI',
    action       => 'narrate'
) AS resposta
FROM DUAL;

-- Recuperar apenas o SQL gerado, para registrar em log de auditoria
SELECT DBMS_CLOUD_AI.GENERATE(
    prompt       => 'Total de internacoes por estado em 2024',
    profile_name => 'SYNODOS_AI',
    action       => 'showsql'
) AS sql_gerado
FROM DUAL;

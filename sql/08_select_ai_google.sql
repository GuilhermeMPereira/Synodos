-- ===========================================================================
-- SYNODOS | 08 - SELECT AI COM GOOGLE GEMINI (alternativa gratuita ao OCI)
-- Executar conectado como ADMIN
-- ---------------------------------------------------------------------------
-- POR QUE ESTE ARQUIVO EXISTE
--
-- O caminho preferido e o OCI Generative AI, configurado no sql/05: ele
-- autentica pelo resource principal do proprio banco, sem chave nenhuma.
-- So que o OCI Generative AI e um servico pago e NAO entra no Always Free.
-- Em conta Free Tier a chamada sai do banco e nao volta - pendura, sem erro.
--
-- Confirmamos que nao e regiao (Brazil East tem o servico), nem politica
-- (a synodos-genai existe, com o statement certo), nem perfil, nem
-- credencial. E entitlement da conta.
--
-- O Select AI aceita outros provedores. O Google Gemini tem cota gratuita
-- pela API do AI Studio, entao da para ter a MESMA funcionalidade - pergunta
-- em portugues virando SQL executado pelo banco - sem custo.
--
-- A diferenca entre os dois:
--
--   OCI      autentica por resource principal, sem chave, sem liberar rede.
--            Mais elegante. Exige conta paga.
--   Google   exige uma chave de API e liberar a saida de rede do banco para
--            o host do Google. Funciona no Free Tier.
--
-- O restante - object_list, comentarios do dicionario, as quatro acoes -
-- e identico. O codigo da aplicacao nao muda em nada.
-- ===========================================================================


-- ------------------------------------------------------------- PASSO 1
-- Pegue a chave gratuita do Gemini
--
--   1. Acesse  https://aistudio.google.com/apikey
--   2. Entre com uma conta Google
--   3. "Create API key" -> copie a chave (comeca com AIza...)
--
-- A cota gratuita e suficiente com folga para a demonstracao. Nao exige
-- cartao de credito.
--
-- A chave e um segredo: ela fica guardada no banco pelo passo 3 e NAO deve
-- ser commitada no git. Nao cole a chave neste arquivo antes de rodar -
-- digite direto no Database Actions.


-- ------------------------------------------------------------- PASSO 2
-- Liberar a saida de rede do banco para o host do Google
--
-- Por padrao o Autonomous Database nao faz chamada HTTP para fora. Esta ACL
-- abre uma excecao para um host so. (Com o OCI isso nao e necessario, porque
-- a chamada nao sai para a internet publica.)

BEGIN
    DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
        host => 'generativelanguage.googleapis.com',
        ace  => xs$ace_type(
                    privilege_list => xs$name_list('http'),
                    principal_name => 'ADMIN',
                    principal_type => xs_acl.ptype_db
                )
    );
END;
/

-- Conferir que a ACL entrou:
SELECT host, lower_port, upper_port
FROM   dba_host_aces
WHERE  host = 'generativelanguage.googleapis.com';


-- ------------------------------------------------------------- PASSO 3
-- Guardar a chave como credencial do banco
--
-- TROQUE 'AIza...' pela sua chave. O username e ignorado pelo provedor
-- google, mas o parametro e obrigatorio.

BEGIN
    DBMS_CLOUD.DROP_CREDENTIAL('GOOGLE_CRED');
EXCEPTION
    WHEN OTHERS THEN NULL;   -- ainda nao existia, tudo bem
END;
/

BEGIN
    DBMS_CLOUD.CREATE_CREDENTIAL(
        credential_name => 'GOOGLE_CRED',
        username        => 'GOOGLE',
        password        => 'AIza_COLE_SUA_CHAVE_AQUI'
    );
END;
/

SELECT credential_name, username
FROM   user_credentials
WHERE  credential_name = 'GOOGLE_CRED';


-- ------------------------------------------------------------- PASSO 4
-- Recriar o perfil apontando para o Google
--
-- O object_list e o "comments" sao os MESMOS do sql/05. E isso que importa:
-- o que ensina o modelo a traduzir "esquizofrenia" para F20 sao os
-- COMMENT ON do sql/01, e eles nao dependem de provedor nenhum.

BEGIN
    DBMS_CLOUD_AI.DROP_PROFILE(
        profile_name => 'SYNODOS_AI', force => TRUE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_CLOUD_AI.CREATE_PROFILE(
        profile_name => 'SYNODOS_AI',
        attributes   => '{
            "provider":        "google",
            "credential_name": "GOOGLE_CRED",
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

EXEC DBMS_CLOUD_AI.SET_PROFILE('SYNODOS_AI');

SELECT profile_name, status FROM user_cloud_ai_profiles;


-- ------------------------------------------------------------- PASSO 5
-- O teste que decide. Se voltar texto, funcionou.

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'ola, responda em uma frase',
           profile_name => 'SYNODOS_AI',
           action       => 'chat'
       ) AS resposta
FROM   DUAL;


-- ------------------------------------------------------------- PASSO 6
-- Agora sim: pergunta em portugues virando SQL sobre os dados.

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Qual o custo medio por internacao em cada regiao',
           profile_name => 'SYNODOS_AI',
           action       => 'showsql'
       ) AS sql_gerado
FROM   DUAL;

SELECT DBMS_CLOUD_AI.GENERATE(
           prompt       => 'Quantas internacoes por esquizofrenia ocorreram em Sao Paulo',
           profile_name => 'SYNODOS_AI',
           action       => 'showsql'
       ) AS sql_gerado
FROM   DUAL;


-- ===========================================================================
-- SE ALGO FALHAR
--
--   ORA-24247: network access denied
--       A ACL do passo 2 nao entrou. Rode de novo como ADMIN e confira a
--       consulta em dba_host_aces.
--
--   ORA-20000 / 400 / API key not valid
--       A chave do passo 3 esta errada ou foi colada com espaco. Recrie a
--       credencial.
--
--   403 / quota
--       Estourou a cota gratuita do dia. Espere ou gere outra chave.
--
--   Modelo nao encontrado
--       O provedor tem um modelo padrao, mas ele muda com o tempo. Se der
--       erro de modelo, recrie o perfil acrescentando, dentro do JSON:
--           "model": "gemini-2.0-flash",
--
--   Pendurou de novo
--       Ai a saida de rede do banco esta bloqueada por outro motivo.
--       Volte para o sql/05 e apresente declarando a limitacao - o
--       docs/SELECT_AI.md ja traz a tabela de hipoteses testadas.
--
-- PARA VOLTAR AO OCI depois, se a conta virar paga: e so rodar o sql/05
-- de novo. Ele recria o mesmo perfil apontando para o OCI.
-- ===========================================================================

# Oracle Select AI no Synodos

Como a camada de perguntas em português foi configurada, e como usá-la.

Esta implementação aplica ao domínio do projeto o procedimento do workshop
[Chat with Your Data in Autonomous AI Database Using Select
AI](https://livelabs.oracle.com/pls/apex/r/dbpm/livelabs/view-workshop?wid=4222)
do Oracle LiveLabs. O lab usa o schema de demonstração `MOVIESTREAM`, com
filmes; aqui a mesma mecânica opera sobre internações de saúde mental.

---

## Como funciona

O gestor escreve a pergunta em português. O Oracle envia ao modelo de linguagem
os **metadados do dicionário de dados** — nomes de tabelas, colunas e os
`COMMENT ON` do DDL. O modelo devolve **uma consulta SQL**. O banco executa essa
consulta sobre os dados reais e devolve o resultado.

O ponto central: **o modelo nunca produz um número.** Ele produz a pergunta
formal; o banco produz a resposta. É por isso que o gestor pode auditar cada
resposta pedindo o SQL.

---

## Configuração aplicada

| Item | Valor |
|---|---|
| Perfil | `SYNODOS_AI` |
| Provedor | OCI Generative AI |
| Credencial | `OCI$RESOURCE_PRINCIPAL` — sem chave de API paga |
| Região | `sa-saopaulo-1` (Brazil East) |
| `comments` | `true` |
| Objetos expostos | 8 views analíticas + 4 tabelas |

O script completo está em `sql/05_select_ai_setup.sql`.

### Duas decisões que valem ser explicadas

**`"comments": "true"`** faz o Oracle enviar ao modelo os `COMMENT ON` escritos
em `sql/01_ddl_relacional.sql`. Sem isso, o modelo não sabe que F20 é
esquizofrenia, e a taxa de acerto do SQL despenca. **Os comentários do DDL não
são documentação — são infraestrutura do Select AI.**

**Expomos as views, não as tabelas cruas.** Os nomes de coluna em português
melhoram muito a qualidade do SQL gerado, e a superfície de dados visível ao
modelo fica restrita ao que já está agregado.

---

## Passos da configuração

### 1. Política IAM

No console OCI, em Identity & Security → Policies:

```
allow any-user to manage generative-ai-family in tenancy
where request.principal.type = 'autonomousdatabase'
```

### 2. Resource principal

Conectado como ADMIN:

```sql
EXEC DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL();

SELECT credential_name FROM all_credentials
WHERE  credential_name = 'OCI$RESOURCE_PRINCIPAL';
```

### 3. Perfil de IA

O bloco `DBMS_CLOUD_AI.CREATE_PROFILE` completo está em
`sql/05_select_ai_setup.sql`, opção A.

---

## Usando

### Pela função (funciona em qualquer cliente)

```sql
SELECT DBMS_CLOUD_AI.GENERATE(
    prompt       => 'Quais estados estao com maior pressao assistencial',
    profile_name => 'SYNODOS_AI',
    action       => 'narrate'
) AS resposta
FROM DUAL;
```

### Pelo atalho `SELECT AI`

```sql
EXEC DBMS_CLOUD_AI.SET_PROFILE('SYNODOS_AI');

SELECT AI narrate Quais estados estao com maior pressao assistencial;
```

> O `SELECT AI` é reescrito pelo **cliente** antes de chegar ao banco. Nem todo
> editor faz isso, e quebrar o comando em várias linhas costuma falhar com
> `ORA-00923`. A chamada via `DBMS_CLOUD_AI.GENERATE` é equivalente e sempre
> funciona.

### As quatro ações

| Ação | O que faz | Uso |
|---|---|---|
| `runsql` | executa e devolve o resultado (padrão) | consultas diretas |
| `narrate` | resposta em texto corrido | abertura e fechamento de demonstrações |
| `showsql` | mostra o SQL gerado, sem executar | **auditoria** |
| `chat` | conversa geral, sem consultar os dados | perguntas conceituais |

---

## Como o painel usa

A aba "Perguntar aos dados" do dashboard consome o Select AI através de
`src/db/select_ai.py`. O fluxo tem três caminhos:

**1. Pergunta sobre os dados.** Pedimos ao modelo apenas o SQL (`showsql`) e o
próprio banco executa. Escolhemos isso em vez de `runsql` direto por dois
motivos: o resultado volta como tabela e não como texto, e ficamos com o SQL em
mãos para exibir ao gestor.

**2. Pergunta conceitual** ("o que é esquizofrenia?"). A geração de SQL falha e
caímos na ação `chat`. A interface rotula a resposta como vinda do conhecimento
do modelo, **não da base**.

**3. Oracle indisponível.** Cai no modo local sem quebrar a aplicação.

A distinção entre 1 e 2 é deliberada. Se todas as respostas parecessem iguais, o
gestor não saberia quando confiar no número. É justamente por existir o caso
rotulado como "não consultado na base" que a afirmação "estes números vêm do
banco" tem peso.

---

## Perguntas de demonstração

**Panorama**
- Qual o total de internações por transtornos mentais e a permanência média?

**Comparação territorial**
- Quais os cinco estados com maior número de internações a cada 10 mil habitantes?
- Qual estado tem a menor densidade de leitos de saúde mental?

**Perfil diagnóstico**
- Quais transtornos consomem mais dias de leito?
- Quantas internações por esquizofrenia ocorreram em São Paulo?

**Prioridade de investimento**
- Quais estados estão com maior pressão assistencial e qual a classificação?

**Custo**
- Qual o custo médio por internação em cada região?
- Qual estado tem o maior custo per capita?

**Auditoria**
- (com `showsql`) Quais os dez estabelecimentos com maior taxa de ocupação?

> As três últimas não estão na lista de sugestões do painel de propósito: com o
> Oracle ligado, o modelo escreve o SQL para perguntas que ninguém antecipou.

---

## Modo local

Sem instância Oracle, um classificador de intenção mapeia a pergunta para um
template SQL executado pelo DuckDB. A diferença honesta:

| | Oracle Select AI | Modo local |
|---|---|---|
| Quem escreve o SQL | modelo de linguagem | classificador + template |
| Vocabulário | aberto | 8 intenções mapeadas |
| Execução | Autonomous Database | DuckDB sobre os Parquet |
| SQL real | sim | sim |
| Resultado real | sim | sim |

O modo local existe para que qualquer pessoa possa clonar o repositório e rodar
o pipeline inteiro. Ao apresentar, **diga qual modo está rodando.**

---

## Segurança

Para o app publicado, `sql/06_usuario_publico.sql` cria um usuário
`SYNODOS_APP` com apenas `SELECT` sobre as views. O motivo é direto: o Select AI
gera SQL a partir de texto livre do usuário, e alguém poderia induzir o modelo a
escrever um comando destrutivo.

A defesa não é filtrar a pergunta — é tirar o poder. Sem privilégio de escrita,
o banco recusa qualquer `DROP` ou `DELETE`, independentemente do que o modelo
tenha gerado.

---

## Erros comuns

| Erro | Causa |
|---|---|
| `ORA-00923: FROM keyword not found` | O cliente não reescreveu o `SELECT AI`. Use `DBMS_CLOUD_AI.GENERATE`. |
| `ORA-20404: object not found` | O `object_list` aponta para uma view que não existe. Rode `sql/04` antes. |
| `ORA-20401: authorization failed` | A política IAM não está valendo, ou ainda não propagou. |
| Credencial não aparece | Rode `ENABLE_RESOURCE_PRINCIPAL` como ADMIN. |
| Resposta sem sentido | Confirme `"comments": "true"` e que os `COMMENT ON` do `sql/01` rodaram. |

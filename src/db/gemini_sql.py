"""
Geracao de SQL em linguagem natural pelo Google Gemini, executada no Oracle.

POR QUE ESTE MODULO EXISTE

O caminho original era o Oracle Select AI: o proprio banco chama o modelo de
linguagem, recebe o SQL e executa. Elegante, e e o que esta em sql/05.

So que a instancia Always Free nao completa chamada HTTP para servico
externo - testamos com OCI Generative AI e com Google Gemini, e os dois
penduram igual. O limite e a saida de rede do banco na conta gratuita.

A observacao que destrava: **quem nao consegue sair para a internet e o
banco, nao a aplicacao.** O Streamlit roda numa maquina com internet normal.
Entao invertemos o caminho:

    antes   pergunta -> Oracle -> modelo -> SQL -> Oracle executa
    agora   pergunta -> Python -> modelo -> SQL -> Oracle executa

O que muda: onde o SQL e gerado. O que NAO muda, e que e o que importa:

  - quem escreve a consulta continua sendo um modelo de linguagem;
  - quem produz os numeros continua sendo o Oracle Autonomous Database;
  - o SQL continua visivel para auditoria.

A afirmacao central do projeto - "o modelo escreve a pergunta formal, o banco
produz a resposta" - permanece literalmente verdadeira.

O que damos ao modelo e o mesmo que o Select AI daria com
`"comments": "true"`: nomes de tabelas, colunas e os COMMENT ON do DDL. Por
isso o `sql/01` continua sendo infraestrutura, nao documentacao.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

log = logging.getLogger("gemini_sql")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Objetos que o modelo enxerga. E a mesma lista do object_list do perfil do
# Select AI (sql/05), de proposito: a superficie exposta ao modelo fica
# restrita ao que ja esta agregado nas views.
OBJETOS = [
    "VW_PANORAMA_GERAL",
    "VW_SERIE_TEMPORAL",
    "VW_TAXA_POR_UF",
    "VW_PERFIL_DIAGNOSTICO",
    "VW_OCUPACAO_REDE",
    "VW_PRESSAO_ASSISTENCIAL",
    "VW_RANKING_UNIDADES",
    "VW_PERFIL_DEMOGRAFICO",
    "FATO_INTERNACAO",
    "DIM_TERRITORIO",
    "DIM_CID10",
]

_ESQUEMA_CACHE: str | None = None


# ===========================================================================
# 1. O dicionario de dados que vai junto com a pergunta
# ===========================================================================
def descrever_esquema(cur) -> str:
    """
    Monta o texto do esquema a partir dos metadados do proprio banco.

    Le user_tab_columns e user_col_comments - ou seja, os mesmos COMMENT ON
    escritos no sql/01. Sem eles o modelo nao sabe que F20 e esquizofrenia,
    e a taxa de acerto do SQL despenca.
    """
    global _ESQUEMA_CACHE
    if _ESQUEMA_CACHE:
        return _ESQUEMA_CACHE

    lista = ", ".join(f"'{o}'" for o in OBJETOS)

    cur.execute(f"""
        SELECT c.table_name,
               c.column_name,
               c.data_type,
               cc.comments
        FROM   user_tab_columns c
        LEFT   JOIN user_col_comments cc
               ON  cc.table_name  = c.table_name
               AND cc.column_name = c.column_name
        WHERE  c.table_name IN ({lista})
        ORDER  BY c.table_name, c.column_id
    """)

    por_tabela: dict[str, list[str]] = {}
    for tabela, coluna, tipo, comentario in cur.fetchall():
        texto = f"  {coluna} ({tipo})"
        if comentario:
            com = comentario.read() if hasattr(comentario, "read") else comentario
            texto += f" -- {com}"
        por_tabela.setdefault(tabela, []).append(texto)

    # Comentario de tabela, que explica para que serve cada view
    cur.execute(f"""
        SELECT table_name, comments
        FROM   user_tab_comments
        WHERE  table_name IN ({lista})
    """)
    descricoes = {}
    for tabela, com in cur.fetchall():
        if com:
            descricoes[tabela] = (
                com.read() if hasattr(com, "read") else com
            )

    partes = []
    for tabela in OBJETOS:
        if tabela not in por_tabela:
            continue
        cabecalho = f"{tabela}"
        if tabela in descricoes:
            cabecalho += f"  -- {descricoes[tabela]}"
        partes.append(cabecalho + "\n" + "\n".join(por_tabela[tabela]))

    _ESQUEMA_CACHE = "\n\n".join(partes)
    return _ESQUEMA_CACHE


INSTRUCAO = """Voce traduz perguntas em portugues para consultas SQL Oracle.

Regras, todas obrigatorias:
1. Responda APENAS com a consulta SQL. Sem explicacao, sem markdown, sem
   ponto e virgula no final.
2. Use somente as tabelas e views listadas abaixo, e somente as colunas que
   aparecem nelas. Nunca invente nome de coluna.
3. Dialeto Oracle. Para limitar linhas use FETCH FIRST n ROWS ONLY, nunca
   LIMIT.
4. Prefira as views VW_* quando elas ja responderem a pergunta: os
   indicadores ja vem calculados.
5. Se a pergunta NAO puder ser respondida com estes dados, responda
   exatamente: FORA_DE_ESCOPO

Esquema disponivel:

{esquema}
"""


# ===========================================================================
# 2. A chamada ao modelo
# ===========================================================================
def _modelo_disponivel(chave: str) -> str:
    """
    Descobre um modelo valido, em vez de assumir um nome fixo.

    Os nomes dos modelos do Gemini mudam com o tempo, e um nome invalido
    devolve 404 no meio da demonstracao. Aqui tentamos o configurado e, se
    ele nao existir, perguntamos ao proprio servico quais existem.
    """
    import requests

    preferido = settings.GEMINI_MODEL
    if preferido:
        return preferido

    resp = requests.get(
        f"{API_BASE}/models",
        headers={"x-goog-api-key": chave},
        timeout=20,
    )
    resp.raise_for_status()
    modelos = [
        m["name"].split("/")[-1]
        for m in resp.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if not modelos:
        raise RuntimeError("nenhum modelo com generateContent disponivel")

    # Preferimos os "flash": mais rapidos e com cota gratuita maior.
    flash = [m for m in modelos if "flash" in m and "thinking" not in m]
    escolhido = (flash or modelos)[0]
    log.info("Modelo Gemini escolhido automaticamente: %s", escolhido)
    return escolhido


def gerar_sql_gemini(pergunta: str, esquema: str) -> str:
    """Manda pergunta + esquema ao Gemini e devolve o SQL, limpo."""
    import requests

    chave = settings.GEMINI_API_KEY
    if not chave:
        raise RuntimeError(
            "GEMINI_API_KEY nao definida. Pegue uma chave gratuita em "
            "https://aistudio.google.com/apikey e coloque no .env."
        )

    modelo = _modelo_disponivel(chave)
    corpo = {
        "system_instruction": {
            "parts": [{"text": INSTRUCAO.format(esquema=esquema)}]
        },
        "contents": [{"parts": [{"text": pergunta}]}],
        # temperatura zero: queremos a consulta mais provavel, nao criatividade
        "generationConfig": {"temperature": 0, "maxOutputTokens": 800},
    }

    resp = requests.post(
        f"{API_BASE}/models/{modelo}:generateContent",
        headers={
            "x-goog-api-key": chave,
            "Content-Type": "application/json",
        },
        data=json.dumps(corpo),
        timeout=settings.GEMINI_TIMEOUT_S,
    )

    if resp.status_code == 429:
        raise RuntimeError(
            "cota gratuita do Gemini esgotada por agora. Espere alguns "
            "minutos ou gere outra chave."
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Gemini devolveu {resp.status_code}: {resp.text[:300]}"
        )

    dados = resp.json()
    try:
        texto = dados["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(
            f"resposta do Gemini em formato inesperado: {str(dados)[:300]}"
        ) from exc

    return limpar(texto)


def limpar(sql: str) -> str:
    """Tira cerca de markdown e ponto e virgula, que o cursor nao aceita."""
    sql = (sql or "").strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)
        sql = re.sub(r"```\s*$", "", sql)
    return sql.strip().rstrip(";").strip()


def disponivel() -> bool:
    """Ha chave do Gemini configurada?"""
    return bool(settings.GEMINI_API_KEY)

"""
Camada de perguntas em linguagem natural.

Dois modos, com a mesma interface:

  MODO ORACLE (producao) - DBMS_CLOUD_AI.GENERATE
      A pergunta em portugues vai ao Oracle Select AI, que consulta os
      metadados do dicionario de dados, gera o SQL, executa no banco e
      devolve o resultado. E o modo descrito em sql/05_select_ai_setup.sql.

  MODO LOCAL (demonstracao) - motor de intencao + DuckDB
      Quando nao ha instancia Oracle disponivel, um classificador de
      intencao por padroes mapeia a pergunta para um template SQL
      parametrizado, que o DuckDB executa sobre os Parquet da camada
      analitica.

      ATENCAO - diferenca honesta entre os modos: no Oracle quem escreve o
      SQL e um modelo de linguagem, capaz de responder perguntas nunca
      antecipadas. No modo local o SQL vem de templates, entao o
      vocabulario reconhecido e finito. O SQL e a execucao sao reais nos
      dois casos; a generalizacao nao.

Uso:
    python -m src.db.select_ai "quais estados tem maior pressao assistencial"
    python -m src.db.select_ai --listar
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

log = logging.getLogger("select_ai")


def fmt_int(valor) -> str:
    """Formata inteiro no padrao brasileiro: 234803 -> 234.803"""
    return f"{int(valor):,}".replace(",", ".")


def fmt_moeda(valor) -> str:
    """Formata moeda no padrao brasileiro: 1234.5 -> 1.234,50"""
    return (
        f"{float(valor):,.2f}"
        .replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    )


def normalizar(texto: str) -> str:
    """Remove acentos e baixa a caixa, para casar padroes com robustez."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


# ===========================================================================
# MODO ORACLE
# ===========================================================================
def limpar_sql_gerado(sql: str) -> str:
    """
    O Select AI as vezes devolve o SQL embrulhado em cerca de markdown ou
    com ponto e virgula final. Nenhum dos dois pode ir para o cursor.
    """
    sql = (sql or "").strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)
        sql = re.sub(r"```\s*$", "", sql)
    return sql.strip().rstrip(";").strip()


def _ler_lob(valor):
    """Converte LOB do Oracle em texto."""
    return valor.read() if hasattr(valor, "read") else valor


def gerar_sql_oracle(cur, pergunta: str) -> str:
    """Pede ao Select AI apenas o SQL, sem executar."""
    cur.execute(
        """SELECT DBMS_CLOUD_AI.GENERATE(
               prompt       => :1,
               profile_name => :2,
               action       => 'showsql'
           ) FROM DUAL""",
        [pergunta, settings.SELECT_AI_PROFILE],
    )
    (sql,) = cur.fetchone()
    return limpar_sql_gerado(_ler_lob(sql))


def narrar_oracle(cur, pergunta: str) -> str:
    """Resposta em texto corrido, gerada pelo modelo a partir dos dados."""
    cur.execute(
        """SELECT DBMS_CLOUD_AI.GENERATE(
               prompt       => :1,
               profile_name => :2,
               action       => 'narrate'
           ) FROM DUAL""",
        [pergunta, settings.SELECT_AI_PROFILE],
    )
    (texto,) = cur.fetchone()
    return (_ler_lob(texto) or "").strip()


def conversar_oracle(cur, pergunta: str) -> str:
    """
    Acao 'chat': o modelo responde com o proprio conhecimento, SEM consultar
    a base. Usamos so quando a pergunta nao e sobre os dados - e a resposta
    e rotulada como tal na interface, porque aqui, sim, o numero viria do
    modelo e nao do banco.
    """
    cur.execute(
        """SELECT DBMS_CLOUD_AI.GENERATE(
               prompt       => :1,
               profile_name => :2,
               action       => 'chat'
           ) FROM DUAL""",
        [pergunta, settings.SELECT_AI_PROFILE],
    )
    (texto,) = cur.fetchone()
    return (_ler_lob(texto) or "").strip()


def perguntar_oracle(
    pergunta: str, com_narrativa: bool = True
) -> dict:
    """
    Consulta o Oracle Select AI, com liberdade total de pergunta.

    O caminho principal e em duas etapas: pedimos ao modelo apenas o SQL
    (acao 'showsql') e o proprio banco executa essa consulta. E melhor do
    que usar 'runsql' direto por dois motivos: o resultado volta como
    tabela de verdade, e nao como texto; e ficamos com o SQL em maos para
    exibir ao gestor, que e o que torna a resposta auditavel.

    Se a pergunta nao for sobre os dados - "o que e esquizofrenia", por
    exemplo - a geracao de SQL falha, e caimos na acao 'chat'. A interface
    deixa claro que essa resposta veio do conhecimento do modelo e nao da
    base, porque a distincao importa para a confianca do gestor.
    """
    from src.db.oracle_conn import cursor

    with cursor() as cur:
        try:
            sql = gerar_sql_oracle(cur, pergunta)
            if not sql.lower().lstrip().startswith(("select", "with")):
                raise RuntimeError("resposta nao e uma consulta")

            cur.execute(sql)
            colunas = [d[0].lower() for d in cur.description]
            linhas = [
                tuple(_ler_lob(v) for v in linha) for linha in cur.fetchall()
            ]
            df = pd.DataFrame(linhas, columns=colunas)

            narrativa = None
            if com_narrativa:
                try:
                    narrativa = narrar_oracle(cur, pergunta)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Narrativa indisponivel: %s", exc)

            return {
                "origem": "dados",
                "resultado": df,
                "sql": sql,
                "narrativa": narrativa,
            }

        except Exception as exc:  # noqa: BLE001
            # Nao deu para responder com os dados. Pode ser uma pergunta
            # conceitual, ou fora do escopo das views expostas ao perfil.
            log.info("Sem SQL para '%s' (%s). Tentando conversa.",
                     pergunta[:60], exc)
            texto = conversar_oracle(cur, pergunta)
            return {
                "origem": "conhecimento_do_modelo",
                "resultado": pd.DataFrame(),
                "sql": None,
                "narrativa": texto,
            }


# ===========================================================================
# MODO LOCAL - catalogo de intencoes
# ===========================================================================
PESO_FORTE = 3
PESO_FRACO = 1


@dataclass
class Intencao:
    nome: str
    descricao: str
    padroes: list[str]
    sql: str
    # Termos que identificam a intencao com pouca ambiguidade. Sem eles,
    # perguntas como "custo total por estado" cairiam em "panorama" (por
    # causa de "total") em vez de "custo".
    padroes_fortes: list[str] = field(default_factory=list)
    exemplos: list[str] = field(default_factory=list)

    def pontuar(self, pergunta: str) -> int:
        """Soma ponderada dos padroes que aparecem na pergunta."""
        forte = sum(
            PESO_FORTE for p in self.padroes_fortes if re.search(p, pergunta)
        )
        fraco = sum(
            PESO_FRACO for p in self.padroes if re.search(p, pergunta)
        )
        return forte + fraco


CATALOGO: list[Intencao] = [
    Intencao(
        nome="pressao_assistencial",
        descricao="Ranking de estados por pressao sobre a rede",
        padroes_fortes=[r"pressao", r"sobrecarreg", r"prioridade"],
        padroes=[
            r"critic", r"investi", r"atencao", r"pior situacao",
        ],
        sql="""
            SELECT ranking, nm_uf AS estado, regiao,
                   indice_pressao, classificacao,
                   internacoes_por_10k_ano, permanencia_media,
                   leitos_por_10k_hab
            FROM pressao
            ORDER BY ranking
        """,
        exemplos=[
            "Quais estados estao com maior pressao assistencial?",
            "Onde devemos priorizar investimento na rede?",
        ],
    ),
    Intencao(
        nome="taxa_por_habitante",
        descricao="Internacoes por 10 mil habitantes por estado",
        padroes_fortes=[r"10 ?mil", r"proporcional", r"per capita"],
        padroes=[
            r"por habitante", r"taxa", r"comparar estados",
            r"maior numero de internacoes",
        ],
        sql="""
            SELECT nm_uf AS estado, regiao, qt_internacoes,
                   populacao, internacoes_por_10k_ano,
                   permanencia_media, custo_per_capita
            FROM taxas
            ORDER BY internacoes_por_10k_ano DESC
        """,
        exemplos=[
            "Quais estados tem mais internacoes por 10 mil habitantes?",
        ],
    ),
    Intencao(
        nome="evolucao_temporal",
        descricao="Serie temporal de internacoes",
        padroes_fortes=[r"evolu", r"mes a mes", r"tendencia", r"serie"],
        padroes=[
            r"crescimento", r"ao longo do tempo", r"mensal", r"aumento",
        ],
        sql="""
            SELECT CAST(CAST(competencia AS BIGINT) AS VARCHAR) AS competencia,
                   qt_internacoes, media_movel_3m,
                   variacao_mensal_pct, permanencia_media
            FROM serie
            ORDER BY competencia
        """,
        exemplos=["Como evoluiram as internacoes mes a mes?"],
    ),
    Intencao(
        nome="diagnosticos",
        descricao="Transtornos que mais internam ou consomem leito",
        padroes_fortes=[
            r"diagnostic", r"transtorno", r"\bcid\b", r"doenca",
            r"esquizofrenia", r"bipolar", r"depress", r"alcool",
        ],
        padroes=[r"consomem mais", r"dias de leito"],
        sql="""
            SELECT cid_grupo AS cid, descricao, qt_internacoes,
                   pct_internacoes, permanencia_media,
                   pct_dias_leito, indice_carga_leito
            FROM diagnosticos
            ORDER BY qt_internacoes DESC
        """,
        exemplos=[
            "Quais transtornos consomem mais dias de leito?",
            "Qual o diagnostico mais frequente?",
        ],
    ),
    Intencao(
        nome="rede_leitos",
        descricao="Leitos, CAPS e taxa de ocupacao da rede",
        padroes_fortes=[
            r"leito", r"\bcaps\b", r"ocupacao", r"capacidade",
        ],
        padroes=[r"rede", r"unidade", r"estabelecimento", r"hospital"],
        sql="""
            SELECT sg_uf AS estado, qt_leitos, qt_caps, qt_estabelecimentos,
                   taxa_ocupacao_pct, leitos_por_10k_hab, caps_por_100k_hab,
                   habitantes_por_caps
            FROM ocupacao
            ORDER BY taxa_ocupacao_pct DESC
        """,
        exemplos=[
            "Qual estado tem menos leitos por habitante?",
            "Como esta a ocupacao da rede?",
        ],
    ),
    Intencao(
        nome="perfil_demografico",
        descricao="Faixa etaria e sexo dos pacientes internados",
        padroes_fortes=[
            r"faixa etaria", r"idade", r"sexo", r"genero",
        ],
        padroes=[r"perfil", r"homens", r"mulheres", r"jovens", r"idosos"],
        sql="""
            SELECT faixa_etaria, ds_sexo AS sexo, qt_internacoes,
                   pct, permanencia_media
            FROM demografia
            ORDER BY qt_internacoes DESC
        """,
        exemplos=["Qual a faixa etaria com mais internacoes?"],
    ),
    Intencao(
        nome="panorama",
        descricao="Numeros gerais consolidados",
        padroes_fortes=[r"panorama", r"visao geral", r"consolidado"],
        padroes=[
            r"total", r"geral", r"resumo", r"quantas internacoes",
        ],
        sql="""
            SELECT COUNT(*)                                AS total_internacoes,
                   COUNT(DISTINCT competencia)             AS competencias,
                   COUNT(DISTINCT sg_uf)                   AS estados,
                   ROUND(AVG(qt_dias_permanencia), 1)      AS permanencia_media,
                   ROUND(SUM(fl_obito) * 100.0 / COUNT(*), 2)
                                                           AS mortalidade_pct,
                   ROUND(SUM(vl_total_aih), 2)             AS custo_total
            FROM analitico
        """,
        exemplos=["Qual o total de internacoes no periodo?"],
    ),
    Intencao(
        nome="custo",
        descricao="Custo assistencial das internacoes",
        padroes_fortes=[r"custo", r"gast", r"orcament", r"despesa"],
        padroes=[r"valor", r"reais", r"caro"],
        sql="""
            SELECT nm_uf AS estado, qt_internacoes,
                   ROUND(custo_total, 2) AS custo_total,
                   custo_per_capita
            FROM taxas
            ORDER BY custo_total DESC
        """,
        exemplos=["Qual estado gasta mais com internacoes psiquiatricas?"],
    ),
]


class MotorLocal:
    """Classificador de intencao + execucao SQL real no DuckDB."""

    def __init__(self) -> None:
        import duckdb

        self.con = duckdb.connect(":memory:")
        p = settings.PROCESSED_DIR

        self.con.execute(
            f"CREATE VIEW analitico AS SELECT * FROM "
            f"read_parquet('{p / 'analitico_internacoes.parquet'}')"
        )
        for nome, arquivo in {
            "pressao": "ind_pressao_assistencial.csv",
            "taxas": "ind_taxa_por_uf.csv",
            "serie": "ind_serie_temporal.csv",
            "diagnosticos": "ind_perfil_diagnostico.csv",
            "ocupacao": "ind_ocupacao_rede.csv",
            "demografia": "ind_perfil_demografico.csv",
        }.items():
            self.con.execute(
                f"CREATE VIEW {nome} AS SELECT * FROM "
                f"read_csv_auto('{p / arquivo}', delim=';', header=true)"
            )

    def classificar(self, pergunta: str) -> tuple[Intencao, int]:
        alvo = normalizar(pergunta)
        pontuadas = [(i, i.pontuar(alvo)) for i in CATALOGO]
        melhor, pontos = max(pontuadas, key=lambda x: x[1])
        if pontos == 0:
            melhor = next(i for i in CATALOGO if i.nome == "panorama")
        return melhor, pontos

    def gerar_sql(self, pergunta: str) -> tuple[str, Intencao]:
        intencao, _ = self.classificar(pergunta)
        sql = " ".join(intencao.sql.split())

        # Filtro por estado, quando a pergunta cita uma UF
        alvo = normalizar(pergunta)
        ufs = {
            "sao paulo": "SP", "rio de janeiro": "RJ", "minas": "MG",
            "espirito santo": "ES", "parana": "PR", "santa catarina": "SC",
            "rio grande do sul": "RS",
        }
        for nome, sigla in ufs.items():
            if nome in alvo:
                coluna = "sg_uf" if "sg_uf" in sql or "FROM ocupacao" in sql \
                    else "estado"
                if " ORDER BY" in sql:
                    cabeca, cauda = sql.split(" ORDER BY", 1)
                    sql = (
                        f"{cabeca} WHERE {coluna} = '{sigla}' "
                        f"ORDER BY{cauda}"
                    ) if "WHERE" not in cabeca else sql
                break

        # Limite quando a pergunta pede "os N primeiros"
        m = re.search(
            r"\b(top|primeir\w+|melhor\w+|maior\w+)\s+(\d+)|\b(\d+)\s+"
            r"(estados|maiores|primeiros)", alvo,
        )
        if m:
            n = next((g for g in m.groups() if g and g.isdigit()), None)
            if n and "LIMIT" not in sql:
                sql += f" LIMIT {n}"
        elif re.search(r"\bcinco\b", alvo) and "LIMIT" not in sql:
            sql += " LIMIT 5"
        elif re.search(r"\bdez\b", alvo) and "LIMIT" not in sql:
            sql += " LIMIT 10"

        return sql, intencao

    def perguntar(self, pergunta: str) -> tuple[pd.DataFrame, str, Intencao]:
        sql, intencao = self.gerar_sql(pergunta)
        return self.con.execute(sql).fetchdf(), sql, intencao


def fmt_dec(valor, casas: int = 2) -> str:
    """Decimal no padrao brasileiro: 11.38 -> 11,38"""
    return f"{float(valor):.{casas}f}".replace(".", ",")


def narrar(df: pd.DataFrame, intencao: Intencao) -> str:
    """Transforma o resultado em uma frase de leitura rapida, em pt-BR."""
    if df.empty:
        return "Nenhum registro encontrado para essa pergunta."

    linha = df.iloc[0]

    if intencao.nome == "pressao_assistencial":
        return (
            f"O estado sob maior pressão assistencial é {linha['estado']} "
            f"({linha['regiao']}), com índice "
            f"{fmt_dec(linha['indice_pressao'], 1)} "
            f"({linha['classificacao']}): "
            f"{fmt_dec(linha['internacoes_por_10k_ano'])} internações por "
            f"10 mil habitantes por ano, permanência média de "
            f"{fmt_dec(linha['permanencia_media'], 1)} dias e apenas "
            f"{fmt_dec(linha['leitos_por_10k_hab'])} leitos por 10 mil "
            f"habitantes."
        )
    if intencao.nome == "taxa_por_habitante":
        return (
            f"{linha['estado']} lidera em internações proporcionais: "
            f"{fmt_dec(linha['internacoes_por_10k_ano'])} por 10 mil "
            f"habitantes por ano, totalizando "
            f"{fmt_int(linha['qt_internacoes'])} internações."
        )
    if intencao.nome == "diagnosticos":
        return (
            f"O diagnóstico mais frequente é {linha['descricao']} "
            f"({linha['cid']}), com "
            f"{fmt_dec(linha['pct_internacoes'], 1)}% das internações e "
            f"permanência média de "
            f"{fmt_dec(linha['permanencia_media'], 1)} dias."
        )
    if intencao.nome == "evolucao_temporal":
        ultimo = df.iloc[-1]
        pico = df.loc[df["qt_internacoes"].idxmax()]
        return (
            f"A série vai de {linha['competencia']} a "
            f"{ultimo['competencia']}. O pico ocorreu em "
            f"{pico['competencia']}, com "
            f"{fmt_int(pico['qt_internacoes'])} internações."
        )
    if intencao.nome == "rede_leitos":
        return (
            f"{linha['estado']} apresenta a maior ocupação estimada: "
            f"{fmt_dec(linha['taxa_ocupacao_pct'], 1)}%, com "
            f"{fmt_int(linha['qt_leitos'])} leitos e "
            f"{int(linha['qt_caps'])} CAPS."
        )
    if intencao.nome == "custo":
        return (
            f"{linha['estado']} tem o maior custo total: "
            f"R$ {fmt_moeda(linha['custo_total'])}, o equivalente a "
            f"R$ {fmt_dec(linha['custo_per_capita'])} por habitante."
        )
    if intencao.nome == "perfil_demografico":
        return (
            f"A faixa de {linha['faixa_etaria']} anos, sexo "
            f"{str(linha['sexo']).lower()}, concentra o maior volume: "
            f"{fmt_int(linha['qt_internacoes'])} internações "
            f"({fmt_dec(linha['pct'], 1)}% do total)."
        )
    if intencao.nome == "panorama":
        return (
            f"Foram {fmt_int(linha['total_internacoes'])} internações em "
            f"{int(linha['competencias'])} competências e "
            f"{int(linha['estados'])} estados, com permanência média de "
            f"{fmt_dec(linha['permanencia_media'], 1)} dias e custo total de "
            f"R$ {fmt_moeda(linha['custo_total'])}."
        )

    return f"{len(df)} registros retornados para: {intencao.descricao}."


def oracle_disponivel() -> bool:
    """Ha credenciais de Oracle configuradas no .env?"""
    return bool(settings.ORACLE_PASSWORD and settings.ORACLE_DSN)


def perguntar(pergunta: str, forcar_local: bool = False) -> dict:
    """
    Interface unica de perguntas em linguagem natural.

    Tenta o Oracle Select AI quando ha credenciais configuradas; se algo
    falhar (banco parado, perfil ausente, sem rede), cai para o modo local
    sem quebrar a aplicacao. O campo "modo" no retorno diz qual respondeu.
    """
    if not forcar_local and oracle_disponivel():
        try:
            r = perguntar_oracle(pergunta)
            return {
                "modo": "oracle",
                "origem": r["origem"],
                "pergunta": pergunta,
                "intencao": None,
                "sql": r["sql"],
                "resultado": r["resultado"],
                "narrativa": r["narrativa"],
                "erro_oracle": None,
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Select AI indisponivel (%s). Usando modo local.", exc)
            erro = str(exc)
    else:
        erro = None

    motor = MotorLocal()
    df, sql, intencao = motor.perguntar(pergunta)
    return {
        "modo": "local",
        "origem": "dados",
        "pergunta": pergunta,
        "intencao": intencao.nome,
        "sql": sql,
        "resultado": df,
        "narrativa": narrar(df, intencao),
        "erro_oracle": erro,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Perguntas em linguagem natural")
    ap.add_argument("pergunta", nargs="*", help="pergunta em portugues")
    ap.add_argument("--local", action="store_true", help="forcar modo local")
    ap.add_argument("--listar", action="store_true",
                    help="lista as perguntas suportadas")
    args = ap.parse_args()

    if args.listar:
        print("\nPerguntas reconhecidas pelo modo local:\n")
        for i in CATALOGO:
            print(f"  [{i.nome}] {i.descricao}")
            for ex in i.exemplos:
                print(f"      - {ex}")
        return

    if not args.pergunta:
        ap.error("informe a pergunta ou use --listar")

    r = perguntar(" ".join(args.pergunta), forcar_local=args.local)

    print(f"\nPergunta : {r['pergunta']}")
    print(f"Modo     : {r['modo']}")
    if r.get("sql"):
        print(f"SQL      : {r['sql']}")
    if r.get("narrativa"):
        print(f"\n{r['narrativa']}\n")
    print(r["resultado"].to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

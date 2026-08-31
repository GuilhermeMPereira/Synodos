"""
Carga dos dados tratados no Oracle Autonomous Database.

Le os Parquet da camada processada e popula o esquema estrela, alem da
tabela de documentos JSON do CNES. Usa executemany com array binding, que
e a forma performatica de carregar volume no python-oracledb.

Ordem de execucao:
    1. sqlplus / SQL Developer: sql/01_ddl_relacional.sql
    2. sqlplus / SQL Developer: sql/02_ddl_json.sql
    3. python -m src.db.carga_oracle
    4. sqlplus / SQL Developer: sql/04_views_analiticas.sql
    5. sqlplus / SQL Developer: sql/05_select_ai_setup.sql

Uso:
    python -m src.db.carga_oracle
    python -m src.db.carga_oracle --truncar
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402
from src.db.oracle_conn import cursor  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("carga_oracle")

LOTE = 5000


def _limpar(df: pd.DataFrame) -> pd.DataFrame:
    """Converte NaN/NaT em None, que o driver mapeia para NULL."""
    return df.astype(object).where(pd.notna(df), None)


def carregar_dim_tempo(cur) -> None:
    fato = pd.read_parquet(
        settings.PROCESSED_DIR / "analitico_internacoes.parquet",
        columns=["competencia", "dt_competencia"],
    ).drop_duplicates("competencia")

    meses_pt = [
        "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]

    linhas = []
    for i, (_, r) in enumerate(fato.sort_values("competencia").iterrows(), 1):
        comp = str(r["competencia"])
        ano, mes = int(comp[:4]), int(comp[4:])
        linhas.append(
            (i, comp, ano, mes, (mes - 1) // 3 + 1,
             meses_pt[mes - 1], r["dt_competencia"].to_pydatetime())
        )

    cur.executemany(
        """INSERT INTO dim_tempo
           (sk_tempo, competencia, ano, mes, trimestre, nm_mes, dt_competencia)
           VALUES (:1, :2, :3, :4, :5, :6, :7)""",
        linhas,
    )
    log.info("dim_tempo: %d linhas", len(linhas))


def carregar_dim_territorio(cur) -> None:
    df = pd.read_csv(
        settings.PROCESSED_DIR / "dim_territorio.csv", sep=";",
        dtype={"co_uf": str},
    )
    linhas = [
        (i, r["co_uf"], r["sg_uf"], r["nm_uf"], r["regiao"],
         int(r["populacao_2022"]), int(r["populacao_regiao"]))
        for i, (_, r) in enumerate(df.iterrows(), 1)
    ]
    cur.executemany(
        """INSERT INTO dim_territorio
           (sk_territorio, co_uf, sg_uf, nm_uf, regiao,
            populacao_2022, populacao_regiao)
           VALUES (:1, :2, :3, :4, :5, :6, :7)""",
        linhas,
    )
    log.info("dim_territorio: %d linhas", len(linhas))


def carregar_dim_cid(cur) -> None:
    df = pd.read_csv(settings.PROCESSED_DIR / "dim_cid10.csv", sep=";")
    linhas = [
        (i, r["cid10"], r["grupo_cid"], r["descricao"],
         r["gravidade_relativa"], int(r["permanencia_esperada_dias"]))
        for i, (_, r) in enumerate(df.iterrows(), 1)
    ]
    cur.executemany(
        """INSERT INTO dim_cid10
           (sk_cid, cid10, grupo_cid, descricao,
            gravidade_relativa, permanencia_esperada_dias)
           VALUES (:1, :2, :3, :4, :5, :6)""",
        linhas,
    )
    log.info("dim_cid10: %d linhas", len(linhas))


def carregar_dim_estabelecimento(cur) -> dict[str, int]:
    df = _limpar(
        pd.read_parquet(
            settings.PROCESSED_DIR / "dim_estabelecimento.parquet"
        )
    )

    mapa: dict[str, int] = {}
    linhas = []
    for i, (_, r) in enumerate(df.iterrows(), 1):
        mapa[r["co_cnes"]] = i
        linhas.append(
            (i, r["co_cnes"], r["nm_estabelecimento"], r["co_tipo_unidade"],
             r["ds_tipo_unidade"], r["co_municipio"], r["sg_uf"],
             int(r["qt_leitos_sus"]), int(r["fl_tem_leito"]),
             r.get("latitude"), r.get("longitude"))
        )

    for ini in range(0, len(linhas), LOTE):
        cur.executemany(
            """INSERT INTO dim_estabelecimento
               (sk_estabelecimento, co_cnes, nm_estabelecimento,
                co_tipo_unidade, ds_tipo_unidade, co_municipio, sg_uf,
                qt_leitos_sus, fl_tem_leito, latitude, longitude)
               VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11)""",
            linhas[ini:ini + LOTE],
        )
    log.info("dim_estabelecimento: %d linhas", len(linhas))
    return mapa


def carregar_cnes_json(cur) -> None:
    """Carrega os documentos JSON originais do CNES."""
    arquivo = settings.RAW_DIR / "cnes_estabelecimentos.json"
    documentos = json.loads(arquivo.read_text(encoding="utf-8"))

    linhas = [
        (
            str(d.get("co_cnes", "")).zfill(7),
            d.get("sg_uf"),
            json.dumps(d, ensure_ascii=False),
        )
        for d in documentos
    ]

    for ini in range(0, len(linhas), LOTE):
        cur.executemany(
            """INSERT INTO cnes_documento (co_cnes, sg_uf, documento)
               VALUES (:1, :2, :3)""",
            linhas[ini:ini + LOTE],
        )
    log.info("cnes_documento: %d documentos JSON", len(linhas))


def carregar_fato(cur, mapa_estab: dict[str, int]) -> None:
    df = pd.read_parquet(
        settings.PROCESSED_DIR / "analitico_internacoes.parquet"
    )

    tempo = {
        c: i
        for i, c in enumerate(sorted(df["competencia"].unique()), 1)
    }
    territorio = pd.read_csv(
        settings.PROCESSED_DIR / "dim_territorio.csv", sep=";"
    )
    mapa_uf = {uf: i for i, uf in enumerate(territorio["sg_uf"], 1)}
    cid = pd.read_csv(settings.PROCESSED_DIR / "dim_cid10.csv", sep=";")
    mapa_cid = {c: i for i, c in enumerate(cid["cid10"], 1)}

    df = _limpar(df)
    linhas = []
    for i, (_, r) in enumerate(df.iterrows(), 1):
        linhas.append(
            (
                i, r["nu_aih"], tempo[r["competencia"]],
                mapa_estab.get(r["co_cnes"]), mapa_uf.get(r["sg_uf"]),
                mapa_cid.get(r["cid_grupo"]),
                r["competencia"], r["sg_uf"], r["co_cnes"],
                r["cid_principal"], r["cid_grupo"],
                r["dt_internacao"], r["dt_saida"],
                int(r["qt_dias_permanencia"]), int(r["nu_idade"]),
                str(r["faixa_etaria"]), int(r["co_sexo"]), r["ds_sexo"],
                int(r["fl_obito"]), int(r["fl_permanencia_prolongada"]),
                float(r["vl_total_aih"]), r["co_carater_internacao"],
            )
        )

    for ini in range(0, len(linhas), LOTE):
        cur.executemany(
            """INSERT INTO fato_internacao
               (sk_internacao, nu_aih, sk_tempo, sk_estabelecimento,
                sk_territorio, sk_cid, competencia, sg_uf, co_cnes,
                cid_principal, cid_grupo, dt_internacao, dt_saida,
                qt_dias_permanencia, nu_idade, faixa_etaria, co_sexo,
                ds_sexo, fl_obito, fl_permanencia_prolongada,
                vl_total_aih, co_carater_internacao)
               VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14,
                       :15,:16,:17,:18,:19,:20,:21,:22)""",
            linhas[ini:ini + LOTE],
        )
        log.info("  fato_internacao: %d/%d", min(ini + LOTE, len(linhas)),
                 len(linhas))

    log.info("fato_internacao: %d linhas", len(linhas))


def truncar(cur) -> None:
    for tabela in (
        "fato_internacao", "cnes_documento", "dim_estabelecimento",
        "dim_cid10", "dim_territorio", "dim_tempo",
    ):
        try:
            cur.execute(f"DELETE FROM {tabela}")
            log.info("  limpo: %s", tabela)
        except Exception as exc:  # noqa: BLE001
            log.warning("  nao foi possivel limpar %s: %s", tabela, exc)


def executar(limpar_antes: bool = False) -> None:
    with cursor() as cur:
        if limpar_antes:
            log.info("Limpando tabelas...")
            truncar(cur)

        log.info("Carregando dimensoes...")
        carregar_dim_tempo(cur)
        carregar_dim_territorio(cur)
        carregar_dim_cid(cur)
        mapa = carregar_dim_estabelecimento(cur)

        log.info("Carregando documentos JSON...")
        carregar_cnes_json(cur)

        log.info("Carregando fato...")
        carregar_fato(cur, mapa)

    log.info("OK: carga concluida.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Carga no Oracle ADB")
    ap.add_argument("--truncar", action="store_true",
                    help="limpa as tabelas antes de carregar")
    args = ap.parse_args()
    executar(args.truncar)


if __name__ == "__main__":
    main()

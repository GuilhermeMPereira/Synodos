"""
ETL - Camada de integracao (SILVER -> GOLD).

Aqui as tres fontes de formatos diferentes se encontram, que e exatamente
o ponto central do challenge:

    fato_internacao      (relacional, SIH/SUS)
        + dim_estabelecimento  (JSON, CNES)
        + dim_territorio       (CSV, IBGE)
        + dim_cid10            (CSV, CID-10)
        = tabela analitica unica consultavel por SQL

O resultado e a base que alimenta os indicadores, o dashboard e o Select AI.

Uso:
    python -m src.etl.integracao
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("integracao")


def carregar_dimensoes() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    estabelecimento = pd.read_parquet(
        settings.PROCESSED_DIR / "dim_estabelecimento.parquet"
    )
    territorio = pd.read_csv(
        settings.PROCESSED_DIR / "dim_territorio.csv", sep=";",
        dtype={"co_uf": str},
    )
    cid = pd.read_csv(settings.PROCESSED_DIR / "dim_cid10.csv", sep=";")
    return estabelecimento, territorio, cid


def integrar() -> pd.DataFrame:
    """Executa as juncoes entre as tres fontes."""
    fato = pd.read_parquet(settings.PROCESSED_DIR / "fato_internacao.parquet")
    estab, territorio, cid = carregar_dimensoes()

    log.info(
        "Entrada | fato: %d | estabelecimentos: %d | UFs: %d | CID: %d",
        len(fato), len(estab), len(territorio), len(cid),
    )

    # --- juncao 1: fato (relacional) x CNES (JSON) -------------------------
    antes = len(fato)
    df = fato.merge(
        estab[
            [
                "co_cnes", "nm_estabelecimento", "ds_tipo_unidade",
                "co_tipo_unidade", "qt_leitos_sus", "co_municipio",
            ]
        ],
        on="co_cnes",
        how="left",
        validate="many_to_one",
    )
    sem_estab = int(df["nm_estabelecimento"].isna().sum())
    log.info(
        "Juncao SIH x CNES: %d linhas | %d sem estabelecimento (%.2f%%)",
        len(df), sem_estab, sem_estab / max(antes, 1) * 100,
    )

    # --- juncao 2: x territorio (CSV / external table) ---------------------
    df = df.merge(
        territorio[
            ["sg_uf", "nm_uf", "regiao", "populacao_2022", "populacao_regiao"]
        ],
        on="sg_uf",
        how="left",
        validate="many_to_one",
    )
    sem_territorio = int(df["nm_uf"].isna().sum())
    log.info("Juncao x territorio: %d sem UF", sem_territorio)

    # --- juncao 3: x CID-10 (CSV) -----------------------------------------
    df = df.merge(
        cid.rename(columns={"cid10": "cid_grupo"}),
        on="cid_grupo",
        how="left",
        validate="many_to_one",
    )
    df["descricao"] = df["descricao"].fillna("Outros transtornos do Capitulo V")
    df["descricao_curta"] = df["descricao_curta"].fillna("Outros")
    df["grupo_cid"] = df["grupo_cid"].fillna("Outros")

    log.info("Tabela analitica integrada: %d linhas x %d colunas",
             len(df), df.shape[1])
    return df


def executar() -> Path:
    df = integrar()
    destino = settings.PROCESSED_DIR / "analitico_internacoes.parquet"
    df.to_parquet(destino, index=False)

    # Amostra em CSV para inspecao manual e evidencia no PPT
    df.head(500).to_csv(
        settings.EXPORTS_DIR / "amostra_analitico.csv",
        sep=";", index=False, encoding="utf-8-sig",
    )

    log.info("OK: %s", destino)
    return destino


if __name__ == "__main__":
    executar()

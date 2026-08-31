"""
FONTE 3 (CSV / EXTERNAL TABLE) - Dados demograficos e territoriais.

Terceiro formato exigido pelo challenge. Os arquivos CSV de populacao por UF
(IBGE, Censo 2022) e a classificacao CID-10 do Capitulo V ficam versionados
em data/reference/ e sao lidos no Oracle como EXTERNAL TABLE, sem carga
fisica - o dado permanece no Object Storage e e consultado por SQL.

Este modulo valida os CSV de referencia, calcula os denominadores
populacionais usados nos indicadores por 10 mil habitantes e publica o
arquivo consolidado que a external table le.

Uso:
    python -m src.ingestao.ingest_csv
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
log = logging.getLogger("ingest_csv")

ARQ_POPULACAO = settings.REFERENCE_DIR / "uf_populacao.csv"
ARQ_CID = settings.REFERENCE_DIR / "cid10_saude_mental.csv"


def carregar_populacao() -> pd.DataFrame:
    """Le e valida o CSV de populacao por UF (IBGE - Censo 2022)."""
    if not ARQ_POPULACAO.exists():
        raise FileNotFoundError(f"CSV de populacao ausente: {ARQ_POPULACAO}")

    df = pd.read_csv(ARQ_POPULACAO, sep=";", dtype={"co_uf": str})

    esperadas = {"co_uf", "sg_uf", "nm_uf", "regiao", "populacao_2022"}
    if not esperadas.issubset(df.columns):
        raise ValueError(
            f"Colunas faltando em {ARQ_POPULACAO}: "
            f"{esperadas - set(df.columns)}"
        )

    if df["sg_uf"].duplicated().any():
        raise ValueError("UF duplicada no CSV de populacao.")

    if len(df) != 27:
        log.warning("Esperadas 27 UFs, encontradas %d.", len(df))

    df["populacao_2022"] = pd.to_numeric(df["populacao_2022"])
    log.info(
        "Populacao carregada: %d UFs | total %s habitantes",
        len(df), f"{df['populacao_2022'].sum():,}".replace(",", "."),
    )
    return df


def carregar_cid() -> pd.DataFrame:
    """Le a tabela de referencia CID-10 do Capitulo V."""
    if not ARQ_CID.exists():
        raise FileNotFoundError(f"CSV de CID ausente: {ARQ_CID}")

    df = pd.read_csv(ARQ_CID, sep=";")
    df["cid10"] = df["cid10"].str.upper().str.strip()

    if df["cid10"].duplicated().any():
        raise ValueError("CID duplicado na tabela de referencia.")

    log.info("CID-10 carregado: %d codigos do Capitulo V", len(df))
    return df


def executar() -> Path:
    """Consolida os CSV de referencia para leitura via external table."""
    populacao = carregar_populacao()
    cid = carregar_cid()

    # Agregado regional - denominador das analises por regiao
    regioes = (
        populacao.groupby("regiao", as_index=False)
        .agg(
            populacao_regiao=("populacao_2022", "sum"),
            qt_ufs=("sg_uf", "count"),
        )
        .sort_values("populacao_regiao", ascending=False)
    )

    destino_pop = settings.PROCESSED_DIR / "dim_territorio.csv"
    populacao.merge(regioes, on="regiao", how="left").to_csv(
        destino_pop, sep=";", index=False, encoding="utf-8"
    )

    destino_cid = settings.PROCESSED_DIR / "dim_cid10.csv"
    cid.to_csv(destino_cid, sep=";", index=False, encoding="utf-8")

    log.info("OK: %s e %s gerados.", destino_pop.name, destino_cid.name)
    return destino_pop


if __name__ == "__main__":
    executar()

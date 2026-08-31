"""
ETL - Camada de tratamento (RAW -> SILVER).

Aplica as regras de qualidade sobre os dados brutos das tres fontes:
deduplicacao, tipagem, tratamento de nulos, remocao de outliers
implausiveis e padronizacao de chaves de juncao.

Toda regra descartada e contabilizada em um relatorio de qualidade, que
alimenta o slide de "tratamento de dados" da entrega.

Uso:
    python -m src.etl.tratamento
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("tratamento")

# Limites de plausibilidade clinica
MAX_DIAS_PERMANENCIA = 365
MAX_IDADE = 110
MIN_IDADE = 0


class RelatorioQualidade:
    """Acumula as regras aplicadas para auditoria e evidencia visual."""

    def __init__(self, nome: str, total_inicial: int) -> None:
        self.nome = nome
        self.total_inicial = total_inicial
        self.regras: list[dict] = []

    def registrar(self, regra: str, removidos: int, detalhe: str = "") -> None:
        self.regras.append(
            {
                "regra": regra,
                "registros_removidos": int(removidos),
                "pct_do_total": round(
                    removidos / max(self.total_inicial, 1) * 100, 3
                ),
                "detalhe": detalhe,
            }
        )
        if removidos:
            log.info("  [%s] %s -> %d removidos", self.nome, regra, removidos)

    def finalizar(self, total_final: int) -> dict:
        return {
            "dataset": self.nome,
            "registros_entrada": self.total_inicial,
            "registros_saida": int(total_final),
            "taxa_aproveitamento_pct": round(
                total_final / max(self.total_inicial, 1) * 100, 2
            ),
            "regras": self.regras,
        }


def tratar_sih(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Limpeza das internacoes do SIH/SUS."""
    rel = RelatorioQualidade("sih_internacoes", len(df))
    log.info("Tratando SIH/SUS: %d registros de entrada", len(df))

    # 1. Deduplicacao pela chave natural (numero da AIH)
    antes = len(df)
    df = df.drop_duplicates(subset=["nu_aih"], keep="first")
    rel.registrar("deduplicacao_por_nu_aih", antes - len(df),
                  "AIH e a chave natural da internacao")

    # 2. CID principal obrigatorio e do Capitulo V
    antes = len(df)
    df = df[df["cid_principal"].notna()]
    df = df[
        df["cid_principal"].astype(str).str.upper().str.startswith("F")
    ]
    rel.registrar("cid_principal_capitulo_v", antes - len(df),
                  "escopo do projeto: transtornos mentais e comportamentais")

    # 3. Permanencia plausivel
    antes = len(df)
    df = df[
        df["qt_dias_permanencia"].between(0, MAX_DIAS_PERMANENCIA)
        | df["qt_dias_permanencia"].isna()
    ]
    rel.registrar("permanencia_fora_da_faixa", antes - len(df),
                  f"0 a {MAX_DIAS_PERMANENCIA} dias")

    # 4. Idade plausivel
    antes = len(df)
    df = df[df["nu_idade"].between(MIN_IDADE, MAX_IDADE) | df["nu_idade"].isna()]
    rel.registrar("idade_fora_da_faixa", antes - len(df),
                  f"{MIN_IDADE} a {MAX_IDADE} anos")

    # 5. Chave de estabelecimento obrigatoria (necessaria para o join CNES)
    antes = len(df)
    df = df[df["co_cnes"].notna() & (df["co_cnes"].astype(str) != "")]
    rel.registrar("cnes_ausente", antes - len(df),
                  "sem CNES nao ha juncao com a rede")

    # 6. Coerencia de datas: saida nao pode anteceder a internacao
    if {"dt_internacao", "dt_saida"}.issubset(df.columns):
        antes = len(df)
        coerente = (df["dt_saida"] >= df["dt_internacao"]) | df["dt_saida"].isna()
        df = df[coerente]
        rel.registrar("data_saida_anterior_a_internacao", antes - len(df))

    # --- padronizacao ------------------------------------------------------
    df = df.copy()
    df["co_cnes"] = df["co_cnes"].astype(str).str.zfill(7)
    df["cid_principal"] = df["cid_principal"].astype(str).str.upper().str.strip()
    df["cid_grupo"] = df["cid_principal"].str[:3]
    df["sg_uf"] = df["sg_uf"].astype(str).str.upper().str.strip()

    df["competencia"] = (
        df["ano_competencia"].astype(int).astype(str)
        + df["mes_competencia"].astype(int).astype(str).str.zfill(2)
    )
    df["dt_competencia"] = pd.to_datetime(
        df["competencia"], format="%Y%m"
    )

    df["ds_sexo"] = df["co_sexo"].map({1: "Masculino", 3: "Feminino"}).fillna(
        "Nao informado"
    )
    df["faixa_etaria"] = pd.cut(
        df["nu_idade"],
        bins=[0, 17, 29, 44, 59, 200],
        labels=["0-17", "18-29", "30-44", "45-59", "60+"],
        right=True,
    )
    df["fl_permanencia_prolongada"] = (
        df["qt_dias_permanencia"] > 30
    ).astype(int)

    log.info("SIH tratado: %d registros de saida", len(df))
    return df, rel.finalizar(len(df))


def tratar_cnes(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Limpeza do cadastro de estabelecimentos."""
    rel = RelatorioQualidade("cnes_estabelecimentos", len(df))
    log.info("Tratando CNES: %d registros de entrada", len(df))

    antes = len(df)
    df = df.drop_duplicates(subset=["co_cnes"], keep="last")
    rel.registrar("deduplicacao_por_cnes", antes - len(df),
                  "mantem o cadastro mais recente")

    antes = len(df)
    df = df[df["co_cnes"].notna() & (df["co_cnes"].astype(str) != "")]
    rel.registrar("cnes_invalido", antes - len(df))

    df = df.copy()
    df["co_cnes"] = df["co_cnes"].astype(str).str.zfill(7)
    df["sg_uf"] = df["sg_uf"].astype(str).str.upper().str.strip()
    df["qt_leitos_sus"] = (
        pd.to_numeric(df["qt_leitos_sus"], errors="coerce").fillna(0).astype(int)
    )
    df["nm_estabelecimento"] = (
        df["nm_estabelecimento"].astype(str).str.strip().str.upper()
    )
    df["fl_tem_leito"] = (df["qt_leitos_sus"] > 0).astype(int)

    nulos_leito = int(df["qt_leitos_sus"].eq(0).sum())
    rel.registrar(
        "leitos_zerados_mantidos", 0,
        f"{nulos_leito} unidades ambulatoriais sem leito - mantidas de proposito",
    )

    log.info("CNES tratado: %d registros de saida", len(df))
    return df, rel.finalizar(len(df))


def detectar_outliers_iqr(serie: pd.Series) -> dict:
    """Detecta outliers pelo metodo do intervalo interquartil (Tukey)."""
    q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
    iqr = q3 - q1
    lim_inf, lim_sup = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = serie[(serie < lim_inf) | (serie > lim_sup)]

    return {
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(iqr),
        "limite_inferior": float(lim_inf),
        "limite_superior": float(lim_sup),
        "qt_outliers": int(len(outliers)),
        "pct_outliers": round(len(outliers) / max(len(serie), 1) * 100, 2),
    }


def executar() -> tuple[Path, Path]:
    sih_bruto = pd.read_parquet(settings.RAW_DIR / "sih_internacoes.parquet")
    cnes_bruto = pd.read_parquet(
        settings.RAW_DIR / "cnes_estabelecimentos.parquet"
    )

    sih, rel_sih = tratar_sih(sih_bruto)
    cnes, rel_cnes = tratar_cnes(cnes_bruto)

    # Analise de outliers (nao remove - documenta para a EDA)
    outliers = {
        "qt_dias_permanencia": detectar_outliers_iqr(
            sih["qt_dias_permanencia"].dropna()
        ),
        "vl_total_aih": detectar_outliers_iqr(sih["vl_total_aih"].dropna()),
    }

    destino_sih = settings.PROCESSED_DIR / "fato_internacao.parquet"
    destino_cnes = settings.PROCESSED_DIR / "dim_estabelecimento.parquet"
    sih.to_parquet(destino_sih, index=False)
    cnes.to_parquet(destino_cnes, index=False)

    relatorio = {
        "datasets": [rel_sih, rel_cnes],
        "analise_outliers": outliers,
    }
    (settings.PROCESSED_DIR / "relatorio_qualidade.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info(
        "OK: aproveitamento SIH %.2f%% | CNES %.2f%%",
        rel_sih["taxa_aproveitamento_pct"],
        rel_cnes["taxa_aproveitamento_pct"],
    )
    return destino_sih, destino_cnes


if __name__ == "__main__":
    executar()

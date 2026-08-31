"""
CAMADA ANALITICA - Calculo dos indicadores de gestao.

Traduz a tabela analitica integrada nos indicadores que o gestor de saude
consome no painel. Cada funcao devolve um DataFrame agregado, e todos sao
persistidos em CSV para consumo pelo dashboard, pelo notebook e pela
carga no Oracle.

Indicadores produzidos:
    1. Panorama geral (KPIs de cabecalho)
    2. Serie temporal de internacoes
    3. Internacoes por 10 mil habitantes (por UF)
    4. Permanencia media por diagnostico
    5. Taxa de ocupacao estimada da rede
    6. Indice de Pressao Assistencial (IPA) - indicador composto proprio
    7. Ranking de regioes/UFs criticas
    8. Perfil demografico e diagnostico

Uso:
    python -m src.etl.indicadores
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
log = logging.getLogger("indicadores")


def _normalizar(serie: pd.Series) -> pd.Series:
    """Normalizacao min-max para 0-100. Constante -> 50."""
    minimo, maximo = serie.min(), serie.max()
    if pd.isna(minimo) or maximo == minimo:
        return pd.Series(50.0, index=serie.index)
    return (serie - minimo) / (maximo - minimo) * 100


# --------------------------------------------------------------- 1. KPIs
def panorama_geral(df: pd.DataFrame) -> dict:
    """KPIs de cabecalho do painel."""
    meses = df["competencia"].nunique()
    leitos = (
        df.drop_duplicates("co_cnes")["qt_leitos_sus"].sum()
        if "qt_leitos_sus" in df.columns else 0
    )
    dias_paciente = df["qt_dias_permanencia"].sum()
    dias_periodo = meses * 30.44

    return {
        "total_internacoes": int(len(df)),
        "competencias_analisadas": int(meses),
        "permanencia_media_dias": round(
            float(df["qt_dias_permanencia"].mean()), 1
        ),
        "permanencia_mediana_dias": float(
            df["qt_dias_permanencia"].median()
        ),
        "internacoes_prolongadas_pct": round(
            float(df["fl_permanencia_prolongada"].mean() * 100), 1
        ),
        "taxa_mortalidade_pct": round(float(df["fl_obito"].mean() * 100), 2),
        "custo_total_reais": round(float(df["vl_total_aih"].sum()), 2),
        "custo_medio_aih_reais": round(float(df["vl_total_aih"].mean()), 2),
        "leitos_saude_mental": int(leitos),
        "taxa_ocupacao_estimada_pct": round(
            float(dias_paciente / (leitos * dias_periodo) * 100), 1
        ) if leitos else None,
        "idade_media": round(float(df["nu_idade"].mean()), 1),
        "ufs_cobertas": int(df["sg_uf"].nunique()),
        "estabelecimentos_ativos": int(df["co_cnes"].nunique()),
    }


# ------------------------------------------------------- 2. serie temporal
def serie_temporal(df: pd.DataFrame) -> pd.DataFrame:
    """Evolucao mensal com media movel e variacao percentual."""
    serie = (
        df.groupby(["dt_competencia", "competencia"], as_index=False)
        .agg(
            qt_internacoes=("nu_aih", "count"),
            permanencia_media=("qt_dias_permanencia", "mean"),
            custo_total=("vl_total_aih", "sum"),
            obitos=("fl_obito", "sum"),
        )
        .sort_values("dt_competencia")
    )

    serie["media_movel_3m"] = (
        serie["qt_internacoes"].rolling(3, min_periods=1).mean().round(1)
    )
    serie["variacao_mensal_pct"] = (
        serie["qt_internacoes"].pct_change().mul(100).round(2)
    )
    serie["permanencia_media"] = serie["permanencia_media"].round(1)
    return serie


# ----------------------------------------------- 3. taxa por 10 mil hab
def taxa_por_habitante(df: pd.DataFrame) -> pd.DataFrame:
    """Internacoes por 10 mil habitantes - permite comparar UFs."""
    meses = df["competencia"].nunique()
    anos = meses / 12

    agg = df.groupby(["sg_uf", "nm_uf", "regiao"], as_index=False).agg(
        qt_internacoes=("nu_aih", "count"),
        populacao=("populacao_2022", "first"),
        permanencia_media=("qt_dias_permanencia", "mean"),
        custo_total=("vl_total_aih", "sum"),
        obitos=("fl_obito", "sum"),
    )

    agg["internacoes_por_10k_ano"] = (
        agg["qt_internacoes"] / agg["populacao"] * 10000 / anos
    ).round(2)
    agg["permanencia_media"] = agg["permanencia_media"].round(1)
    agg["custo_per_capita"] = (
        agg["custo_total"] / agg["populacao"]
    ).round(2)
    agg["taxa_mortalidade_pct"] = (
        agg["obitos"] / agg["qt_internacoes"] * 100
    ).round(2)

    return agg.sort_values("internacoes_por_10k_ano", ascending=False)


# ------------------------------------------------- 4. perfil diagnostico
def perfil_diagnostico(df: pd.DataFrame) -> pd.DataFrame:
    """Distribuicao e impacto por grupo diagnostico do CID-10."""
    agg = df.groupby(
        ["cid_grupo", "descricao", "descricao_curta", "grupo_cid"],
        as_index=False,
    ).agg(
        qt_internacoes=("nu_aih", "count"),
        permanencia_media=("qt_dias_permanencia", "mean"),
        permanencia_total=("qt_dias_permanencia", "sum"),
        custo_total=("vl_total_aih", "sum"),
        idade_media=("nu_idade", "mean"),
        obitos=("fl_obito", "sum"),
    )

    agg["pct_internacoes"] = (
        agg["qt_internacoes"] / agg["qt_internacoes"].sum() * 100
    ).round(2)
    agg["pct_dias_leito"] = (
        agg["permanencia_total"] / agg["permanencia_total"].sum() * 100
    ).round(2)
    # Quanto o diagnostico consome de leito acima do seu peso em volume
    agg["indice_carga_leito"] = (
        agg["pct_dias_leito"] / agg["pct_internacoes"]
    ).round(2)

    for col in ("permanencia_media", "idade_media"):
        agg[col] = agg[col].round(1)

    return agg.sort_values("qt_internacoes", ascending=False)


# ------------------------------------------- 5. ocupacao e rede por UF
def ocupacao_rede(
    df: pd.DataFrame, estab: pd.DataFrame
) -> pd.DataFrame:
    """Taxa de ocupacao estimada e densidade de leitos por UF."""
    meses = df["competencia"].nunique()
    dias_periodo = meses * 30.44

    dias_paciente = df.groupby("sg_uf", as_index=False).agg(
        dias_paciente=("qt_dias_permanencia", "sum"),
        qt_internacoes=("nu_aih", "count"),
        populacao=("populacao_2022", "first"),
    )

    rede = estab.groupby("sg_uf", as_index=False).agg(
        qt_leitos=("qt_leitos_sus", "sum"),
        qt_estabelecimentos=("co_cnes", "count"),
    )
    caps = (
        estab[estab["ds_tipo_unidade"] == "CAPS"]
        .groupby("sg_uf", as_index=False)
        .agg(qt_caps=("co_cnes", "count"))
    )

    out = dias_paciente.merge(rede, on="sg_uf", how="left").merge(
        caps, on="sg_uf", how="left"
    )
    out["qt_caps"] = out["qt_caps"].fillna(0).astype(int)

    out["taxa_ocupacao_pct"] = (
        out["dias_paciente"] / (out["qt_leitos"] * dias_periodo) * 100
    ).round(1)
    out["leitos_por_10k_hab"] = (
        out["qt_leitos"] / out["populacao"] * 10000
    ).round(2)
    out["caps_por_100k_hab"] = (
        out["qt_caps"] / out["populacao"] * 100000
    ).round(2)
    out["habitantes_por_caps"] = (
        out["populacao"] / out["qt_caps"].replace(0, np.nan)
    ).round(0)

    return out.sort_values("taxa_ocupacao_pct", ascending=False)


# ------------------------------------- 6. Indice de Pressao Assistencial
def indice_pressao_assistencial(
    taxas: pd.DataFrame, ocupacao: pd.DataFrame
) -> pd.DataFrame:
    """
    IPA - indicador composto proprio do projeto (0 a 100).

    Combina tres dimensoes normalizadas por min-max entre as UFs:
      - demanda      (internacoes por 10 mil hab/ano)   peso 0,5
      - complexidade (permanencia media)                peso 0,3
      - escassez     (inverso dos leitos por 10 mil)    peso 0,2

    Quanto maior o IPA, maior a pressao sobre a rede daquela UF -
    e maior a prioridade de investimento.
    """
    base = taxas.merge(
        ocupacao[
            ["sg_uf", "taxa_ocupacao_pct", "leitos_por_10k_hab",
             "qt_leitos", "qt_caps", "caps_por_100k_hab"]
        ],
        on="sg_uf",
        how="left",
    )

    base["n_demanda"] = _normalizar(base["internacoes_por_10k_ano"])
    base["n_complexidade"] = _normalizar(base["permanencia_media"])
    # Escassez: menos leitos por habitante => maior pressao => inverte
    base["n_escassez"] = 100 - _normalizar(base["leitos_por_10k_hab"])

    base["indice_pressao"] = (
        base["n_demanda"] * settings.PRESSAO_PESO_INTERNACAO
        + base["n_complexidade"] * settings.PRESSAO_PESO_PERMANENCIA
        + base["n_escassez"] * settings.PRESSAO_PESO_LEITOS
    ).round(1)

    base["classificacao"] = pd.cut(
        base["indice_pressao"],
        bins=[-0.1, 25, 50, 75, 100.1],
        labels=["Baixa", "Moderada", "Alta", "Critica"],
    )

    base = base.sort_values("indice_pressao", ascending=False).reset_index(
        drop=True
    )
    base["ranking"] = base.index + 1

    for col in ("n_demanda", "n_complexidade", "n_escassez"):
        base[col] = base[col].round(1)

    return base


# ------------------------------------------------- 7. perfil demografico
def perfil_demografico(df: pd.DataFrame) -> pd.DataFrame:
    agg = df.groupby(
        ["faixa_etaria", "ds_sexo"], as_index=False, observed=True
    ).agg(
        qt_internacoes=("nu_aih", "count"),
        permanencia_media=("qt_dias_permanencia", "mean"),
    )
    agg["permanencia_media"] = agg["permanencia_media"].round(1)
    agg["pct"] = (
        agg["qt_internacoes"] / agg["qt_internacoes"].sum() * 100
    ).round(2)
    return agg


# ----------------------------------------------------------- orquestracao
def executar() -> dict:
    df = pd.read_parquet(
        settings.PROCESSED_DIR / "analitico_internacoes.parquet"
    )
    estab = pd.read_parquet(
        settings.PROCESSED_DIR / "dim_estabelecimento.parquet"
    )

    log.info("Calculando indicadores sobre %d internacoes...", len(df))

    kpis = panorama_geral(df)
    serie = serie_temporal(df)
    taxas = taxa_por_habitante(df)
    diagnosticos = perfil_diagnostico(df)
    ocupacao = ocupacao_rede(df, estab)
    pressao = indice_pressao_assistencial(taxas, ocupacao)
    demografia = perfil_demografico(df)

    saidas = {
        "ind_serie_temporal.csv": serie,
        "ind_taxa_por_uf.csv": taxas,
        "ind_perfil_diagnostico.csv": diagnosticos,
        "ind_ocupacao_rede.csv": ocupacao,
        "ind_pressao_assistencial.csv": pressao,
        "ind_perfil_demografico.csv": demografia,
    }
    for nome, tabela in saidas.items():
        tabela.to_csv(
            settings.PROCESSED_DIR / nome, sep=";", index=False,
            encoding="utf-8-sig",
        )
        log.info("  gravado %s (%d linhas)", nome, len(tabela))

    (settings.PROCESSED_DIR / "ind_panorama_geral.json").write_text(
        json.dumps(kpis, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("--- PANORAMA GERAL ---")
    for chave, valor in kpis.items():
        log.info("  %-32s %s", chave, valor)

    log.info("--- TOP 3 PRESSAO ASSISTENCIAL ---")
    for _, r in pressao.head(3).iterrows():
        log.info(
            "  %d. %s (%s) IPA=%.1f | %s",
            r["ranking"], r["nm_uf"], r["sg_uf"],
            r["indice_pressao"], r["classificacao"],
        )

    return kpis


if __name__ == "__main__":
    executar()

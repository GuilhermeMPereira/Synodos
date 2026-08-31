"""
MODELOS ANALITICOS.

Tres modelos, cada um respondendo a uma pergunta de gestao:

  1. CLUSTERIZACAO (K-Means)
     "Quais estados tem perfil assistencial parecido e podem receber a mesma
     politica publica?" Agrupa UFs por demanda, complexidade e capacidade
     instalada. Numero de grupos escolhido por silhueta.

  2. PROJECAO DE DEMANDA (regressao linear com sazonalidade)
     "Quantas internacoes esperar nos proximos meses?" Regressao sobre
     tendencia + variaveis dummy de mes, com intervalo de confianca e
     validacao em janela de teste retida.

  3. DECOMPOSICAO SAZONAL (STL)
     "O crescimento e real ou e efeito de sazonalidade?" Separa a serie em
     tendencia, componente sazonal e residuo.

Graficos gerados:
    07_clusters.png     agrupamento de UFs
    08_projecao.png     serie observada e projetada
    09_decomposicao.png tendencia, sazonalidade e residuo

Uso:
    python -m src.analytics.modelos
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402
from src.analytics import estilo  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("modelos")

FONTE = ("Fonte: SIH/SUS e CNES (Ministerio da Saude); "
         "populacao Censo IBGE 2022. Elaboracao: Synodos.")


# =========================================================== 1. CLUSTERIZACAO
def clusterizar(pressao: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Agrupa UFs por perfil assistencial usando K-Means."""
    atributos = [
        "internacoes_por_10k_ano",
        "permanencia_media",
        "leitos_por_10k_hab",
        "taxa_ocupacao_pct",
        "caps_por_100k_hab",
    ]
    X = pressao[atributos].fillna(pressao[atributos].median())

    # Padronizacao: as escalas sao muito diferentes entre si
    escalador = StandardScaler()
    X_norm = escalador.fit_transform(X)

    # Escolha de k pela silhueta (limitada pelo numero de UFs)
    k_max = min(5, len(X) - 1)
    avaliacao = {}
    for k in range(2, k_max + 1):
        modelo = KMeans(n_clusters=k, random_state=settings.SEED, n_init=25)
        rotulos = modelo.fit_predict(X_norm)
        avaliacao[k] = float(silhouette_score(X_norm, rotulos))
        log.info("  k=%d -> silhueta %.3f", k, avaliacao[k])

    k_otimo = max(avaliacao, key=avaliacao.get)
    log.info("k escolhido: %d (silhueta %.3f)", k_otimo, avaliacao[k_otimo])

    modelo = KMeans(
        n_clusters=k_otimo, random_state=settings.SEED, n_init=25
    )
    out = pressao.copy()
    out["cluster"] = modelo.fit_predict(X_norm)

    # Nomeia os clusters pela pressao media - rotulo interpretavel
    ordem = (
        out.groupby("cluster")["indice_pressao"].mean()
        .sort_values(ascending=False).index.tolist()
    )
    nomes = [
        "Rede sob pressao", "Situacao intermediaria",
        "Rede equilibrada", "Grupo 4", "Grupo 5",
    ]
    mapa = {c: nomes[i] for i, c in enumerate(ordem)}
    out["perfil"] = out["cluster"].map(mapa)

    perfis = (
        out.groupby("perfil")[atributos + ["indice_pressao"]]
        .mean().round(2)
        .join(out.groupby("perfil")["sg_uf"].apply(", ".join).rename("ufs"))
    )

    diagnostico = {
        "k_escolhido": int(k_otimo),
        "silhueta_por_k": {str(k): round(v, 3) for k, v in avaliacao.items()},
        "silhueta_final": round(avaliacao[k_otimo], 3),
        "atributos": atributos,
        "inercia": round(float(modelo.inertia_), 2),
    }
    return out, {"diagnostico": diagnostico, "perfis": perfis}


def g_clusters(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(9.5, 6))

    for i, perfil in enumerate(sorted(df["perfil"].unique())):
        sub = df[df["perfil"] == perfil]
        ax.scatter(
            sub["internacoes_por_10k_ano"], sub["leitos_por_10k_hab"],
            s=sub["permanencia_media"] * 14, color=estilo.SERIES[i],
            label=perfil, edgecolor=estilo.SURFACE, linewidth=2, zorder=3,
        )

    for _, r in df.iterrows():
        ax.annotate(
            r["sg_uf"],
            (r["internacoes_por_10k_ano"], r["leitos_por_10k_hab"]),
            textcoords="offset points", xytext=(0, 15), ha="center",
            fontsize=10, fontweight="bold", color=estilo.TEXT_PRIMARY,
        )

    ax.set_xlabel("Internacoes por 10 mil habitantes/ano  (demanda)")
    ax.set_ylabel("Leitos por 10 mil habitantes  (capacidade)")
    ax.legend(loc="upper right")

    estilo.titular(
        ax, "Agrupamento de estados por perfil assistencial",
        "K-Means sobre demanda, permanencia, leitos, ocupacao e CAPS. "
        "O tamanho do ponto indica a permanencia media",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "07_clusters.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# =========================================================== 2. PROJECAO
def projetar_demanda(
    serie: pd.DataFrame, horizonte: int = 6
) -> tuple[pd.DataFrame, dict]:
    """Regressao linear com tendencia e sazonalidade mensal."""
    df = serie.copy().reset_index(drop=True)
    df["t"] = np.arange(len(df))
    df["mes"] = df["competencia"].astype(str).str.slice(4, 6).astype(int)

    # Matriz de desenho: intercepto + tendencia + dummies de mes
    def desenho(t: np.ndarray, mes: np.ndarray) -> np.ndarray:
        dummies = np.zeros((len(t), 11))
        for i, m in enumerate(mes):
            if m < 12:
                dummies[i, m - 1] = 1
        return np.column_stack([np.ones(len(t)), t, dummies])

    # Validacao: treina sem os ultimos 6 meses e mede o erro neles
    corte = len(df) - 6
    X_tr = desenho(df["t"].values[:corte], df["mes"].values[:corte])
    y_tr = df["qt_internacoes"].values[:corte]
    beta_tr, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)

    X_te = desenho(df["t"].values[corte:], df["mes"].values[corte:])
    y_te = df["qt_internacoes"].values[corte:]
    pred_te = X_te @ beta_tr
    mape = float(np.mean(np.abs((y_te - pred_te) / y_te)) * 100)
    log.info("Validacao em 6 meses retidos: MAPE %.2f%%", mape)

    # Modelo final sobre a serie completa
    X = desenho(df["t"].values, df["mes"].values)
    y = df["qt_internacoes"].values
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)

    ajustado = X @ beta
    residuos = y - ajustado
    sigma = float(residuos.std(ddof=X.shape[1]))
    ss_res = float((residuos ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot

    # Projecao futura
    ultimo = pd.Period(str(df["competencia"].iloc[-1]), freq="M")
    futuras = [ultimo + i for i in range(1, horizonte + 1)]
    t_fut = np.arange(len(df), len(df) + horizonte)
    mes_fut = np.array([p.month for p in futuras])
    pred = desenho(t_fut, mes_fut) @ beta

    projecao = pd.DataFrame(
        {
            "competencia": [p.strftime("%Y%m") for p in futuras],
            "previsto": pred.round(0),
            "limite_inferior": (pred - 1.96 * sigma).round(0),
            "limite_superior": (pred + 1.96 * sigma).round(0),
        }
    )

    # Crescimento ano contra ano: compara os meses projetados com os MESMOS
    # meses do calendario um ano antes. Comparar o ultimo mes projetado com
    # o ultimo observado misturaria tendencia com sazonalidade - junho e pico
    # e dezembro e vale, o que inflaria artificialmente o crescimento.
    # A projecao cobre os meses len(y) .. len(y)+horizonte-1. Um ano antes
    # sao os meses len(y)-12 .. len(y)-12+horizonte-1.
    if len(y) >= 12 and horizonte <= 12:
        mesmo_periodo_ano_anterior = y[len(y) - 12: len(y) - 12 + horizonte]
    else:
        mesmo_periodo_ano_anterior = None

    if mesmo_periodo_ano_anterior is not None and \
            mesmo_periodo_ano_anterior.sum() > 0:
        crescimento_yoy = float(
            pred.sum() / mesmo_periodo_ano_anterior.sum() - 1
        ) * 100
    else:
        crescimento_yoy = None

    metricas = {
        "r2": round(r2, 4),
        "mape_validacao_pct": round(mape, 2),
        "erro_padrao_residuos": round(sigma, 1),
        "tendencia_por_mes": round(float(beta[1]), 1),
        "tendencia_anualizada_pct": round(
            float(beta[1] * 12 / y.mean()) * 100, 1
        ),
        "crescimento_yoy_projetado_pct": (
            round(crescimento_yoy, 1) if crescimento_yoy is not None else None
        ),
        "horizonte_meses": horizonte,
    }
    log.info(
        "Modelo final: R2 %.3f | tendencia %+.1f internacoes/mes",
        r2, beta[1],
    )
    return projecao, {"metricas": metricas, "ajustado": ajustado}


def g_projecao(
    serie: pd.DataFrame, projecao: pd.DataFrame, ajustado: np.ndarray,
    metricas: dict,
) -> Path:
    fig, ax = plt.subplots(figsize=(11, 5))

    n = len(serie)
    x_obs = np.arange(n)
    x_fut = np.arange(n, n + len(projecao))

    ax.plot(x_obs, serie["qt_internacoes"], color=estilo.SERIES[0],
            marker="o", markersize=4, label="Observado", zorder=3)
    ax.plot(x_obs, ajustado, color=estilo.TEXT_MUTED, linewidth=1.4,
            linestyle=":", label="Ajuste do modelo", zorder=2)

    # Conecta a ultima observacao a primeira projecao
    ax.plot(
        [x_obs[-1], x_fut[0]],
        [serie["qt_internacoes"].iloc[-1], projecao["previsto"].iloc[0]],
        color=estilo.SERIES[1], linewidth=2, linestyle="--", zorder=3,
    )
    ax.plot(x_fut, projecao["previsto"], color=estilo.SERIES[1],
            marker="s", markersize=5, linestyle="--",
            label="Projetado (6 meses)", zorder=3)
    ax.fill_between(
        x_fut, projecao["limite_inferior"], projecao["limite_superior"],
        color=estilo.SERIES[1], alpha=0.16,
        label="Intervalo de confianca 95%", zorder=1,
    )

    ax.axvline(n - 0.5, color=estilo.GRID, linewidth=1.2)
    ax.text(n - 0.3, ax.get_ylim()[1] * 0.97, " projecao", fontsize=9,
            color=estilo.TEXT_SECONDARY, va="top")

    rotulos = (
        list(serie["competencia"].astype(str))
        + list(projecao["competencia"])
    )
    marcas = list(range(0, len(rotulos), 3))
    ax.set_xticks(marcas)
    ax.set_xticklabels(
        [f"{rotulos[i][4:6]}/{rotulos[i][2:4]}" for i in marcas]
    )
    ax.set_ylabel("Internacoes")
    ax.legend(loc="lower right", ncols=2)

    estilo.titular(
        ax, "Projecao da demanda por internacao",
        f"Regressao com tendencia e sazonalidade | R2 = "
        f"{metricas['r2']:.2f} | erro medio na validacao = "
        f"{metricas['mape_validacao_pct']:.1f}%",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "08_projecao.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# =========================================================== 3. DECOMPOSICAO
def g_decomposicao(serie: pd.DataFrame) -> tuple[Path, dict]:
    """Decomposicao STL: tendencia, sazonalidade e residuo."""
    from statsmodels.tsa.seasonal import STL

    s = pd.Series(
        serie["qt_internacoes"].values,
        index=pd.PeriodIndex(
            serie["competencia"].astype(str), freq="M"
        ).to_timestamp(),
    )

    resultado = STL(s, period=12, robust=True).fit()

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)

    for ax, (dados, titulo, cor) in zip(
        axes,
        [
            (resultado.trend, "Tendencia", estilo.SERIES[0]),
            (resultado.seasonal, "Componente sazonal", estilo.SERIES[2]),
            (resultado.resid, "Residuo", estilo.SERIES[1]),
        ],
    ):
        ax.plot(dados.index, dados.values, color=cor, linewidth=2)
        estilo.titular(ax, titulo)
        ax.set_ylabel("Internacoes")

    axes[1].axhline(0, color=estilo.GRID, linewidth=1)
    axes[2].axhline(0, color=estilo.GRID, linewidth=1)

    forca_sazonal = float(
        max(0, 1 - resultado.resid.var()
            / (resultado.seasonal + resultado.resid).var())
    )
    forca_tendencia = float(
        max(0, 1 - resultado.resid.var()
            / (resultado.trend + resultado.resid).var())
    )

    fig.suptitle(
        "Decomposicao da serie de internacoes",
        x=0.005, ha="left", fontsize=13.5, fontweight="bold",
        color=estilo.TEXT_PRIMARY, y=0.995,
    )
    fig.text(
        0.005, 0.968,
        f"Forca da tendencia: {forca_tendencia:.2f} | "
        f"forca da sazonalidade: {forca_sazonal:.2f} "
        f"(0 = ausente, 1 = dominante)",
        fontsize=9.5, color=estilo.TEXT_SECONDARY, ha="left",
    )
    estilo.rodape(fig, FONTE)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    destino = settings.ASSETS_DIR / "09_decomposicao.png"
    fig.savefig(destino)
    plt.close(fig)

    metricas = {
        "forca_tendencia": round(forca_tendencia, 3),
        "forca_sazonalidade": round(forca_sazonal, 3),
        "mes_pico_sazonal": int(
            resultado.seasonal.groupby(resultado.seasonal.index.month)
            .mean().idxmax()
        ),
        "mes_vale_sazonal": int(
            resultado.seasonal.groupby(resultado.seasonal.index.month)
            .mean().idxmin()
        ),
    }
    return destino, metricas


# =========================================================== orquestracao
def executar() -> None:
    estilo.aplicar_estilo()

    pressao = pd.read_csv(
        settings.PROCESSED_DIR / "ind_pressao_assistencial.csv", sep=";"
    )
    serie = pd.read_csv(
        settings.PROCESSED_DIR / "ind_serie_temporal.csv", sep=";"
    )

    log.info("=== 1. CLUSTERIZACAO (K-Means) ===")
    clusters, info_cluster = clusterizar(pressao)
    caminho_cluster = g_clusters(clusters)
    clusters.to_csv(
        settings.PROCESSED_DIR / "mod_clusters.csv", sep=";", index=False,
        encoding="utf-8-sig",
    )
    print("\n--- PERFIS IDENTIFICADOS ---")
    print(info_cluster["perfis"].to_string())

    log.info("=== 2. PROJECAO DE DEMANDA ===")
    projecao, info_proj = projetar_demanda(serie)
    caminho_proj = g_projecao(
        serie, projecao, info_proj["ajustado"], info_proj["metricas"]
    )
    projecao.to_csv(
        settings.PROCESSED_DIR / "mod_projecao.csv", sep=";", index=False,
        encoding="utf-8-sig",
    )
    print("\n--- PROJECAO PARA OS PROXIMOS 6 MESES ---")
    print(projecao.to_string(index=False))

    log.info("=== 3. DECOMPOSICAO SAZONAL (STL) ===")
    caminho_decomp, metricas_decomp = g_decomposicao(serie)

    relatorio = {
        "clusterizacao": info_cluster["diagnostico"],
        "projecao": info_proj["metricas"],
        "decomposicao": metricas_decomp,
        "graficos": [
            caminho_cluster.name, caminho_proj.name, caminho_decomp.name
        ],
    }
    (settings.PROCESSED_DIR / "mod_relatorio.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n--- RESUMO DOS MODELOS ---")
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    log.info("OK: 3 modelos e 3 graficos gerados.")


if __name__ == "__main__":
    executar()

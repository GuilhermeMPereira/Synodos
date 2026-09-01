"""
ANALISE EXPLORATORIA DE DADOS (EDA).

Produz as estatisticas descritivas e os graficos que sustentam as decisoes
analiticas do projeto. Todos os PNG vao para assets/graficos/ e sao as
evidencias visuais usadas no PowerPoint e no video pitch.

Graficos gerados:
    01_serie_temporal.png       evolucao mensal e media movel
    02_diagnosticos.png         volume x consumo de leito por CID
    03_pressao_assistencial.png ranking de UFs pelo IPA
    04_distribuicao_permanencia.png  histograma e boxplot
    05_correlacao.png           matriz de correlacao entre variaveis
    06_perfil_demografico.png   faixa etaria e sexo

Uso:
    python -m src.analytics.eda
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402
from src.analytics import estilo  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("eda")

FONTE = ("Fonte: SIH/SUS e CNES (Ministerio da Saude); "
         "populacao Censo IBGE 2022. Elaboracao: Synodos.")


def carregar() -> dict[str, pd.DataFrame]:
    p = settings.PROCESSED_DIR
    return {
        "analitico": pd.read_parquet(p / "analitico_internacoes.parquet"),
        "serie": pd.read_csv(p / "ind_serie_temporal.csv", sep=";"),
        "diagnosticos": pd.read_csv(p / "ind_perfil_diagnostico.csv", sep=";"),
        "pressao": pd.read_csv(p / "ind_pressao_assistencial.csv", sep=";"),
        "demografia": pd.read_csv(p / "ind_perfil_demografico.csv", sep=";"),
    }


# ------------------------------------------------------ estatisticas
def estatisticas_descritivas(df: pd.DataFrame) -> pd.DataFrame:
    """Estatisticas descritivas das variaveis numericas centrais."""
    colunas = ["qt_dias_permanencia", "nu_idade", "vl_total_aih"]
    desc = df[colunas].describe(
        percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]
    ).T

    desc["assimetria"] = [df[c].skew() for c in colunas]
    desc["curtose"] = [df[c].kurtosis() for c in colunas]
    desc["cv_pct"] = (desc["std"] / desc["mean"] * 100).round(1)
    return desc.round(2)


# ------------------------------------------------------ grafico 1
def g_serie_temporal(serie: pd.DataFrame) -> Path:
    serie = serie.copy()
    serie["rotulo"] = serie["competencia"].astype(str).str.slice(4, 6) + "/" \
        + serie["competencia"].astype(str).str.slice(2, 4)

    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(len(serie))

    ax.plot(
        x, serie["qt_internacoes"], color=estilo.SERIES[0],
        marker="o", markersize=4, label="Internacoes no mes", zorder=3,
    )
    ax.plot(
        x, serie["media_movel_3m"], color=estilo.SERIES[1],
        linestyle="--", linewidth=1.8, label="Media movel de 3 meses",
        zorder=2,
    )

    # Rotulos diretos apenas no primeiro, no pico e no ultimo ponto
    idx_pico = int(serie["qt_internacoes"].idxmax())
    for i in {0, idx_pico, len(serie) - 1}:
        ax.annotate(
            estilo.fmt_milhar(serie["qt_internacoes"].iloc[i]),
            (i, serie["qt_internacoes"].iloc[i]),
            textcoords="offset points", xytext=(0, 11),
            ha="center", fontsize=9, fontweight="bold",
            color=estilo.TEXT_PRIMARY,
        )

    ax.set_xticks(x[::2])
    ax.set_xticklabels(serie["rotulo"].iloc[::2], rotation=0)
    ax.set_ylabel("Internacoes")
    ax.set_ylim(0, serie["qt_internacoes"].max() * 1.18)
    ax.legend(loc="lower right", ncols=2)

    variacao = (
        serie["qt_internacoes"].iloc[-1] / serie["qt_internacoes"].iloc[0] - 1
    ) * 100
    estilo.titular(
        ax,
        "Internacoes por transtornos mentais no SUS",
        f"Crescimento de {variacao:.0f}% entre a primeira e a ultima "
        f"competencia analisada",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "01_serie_temporal.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# ------------------------------------------------------ grafico 2
def g_diagnosticos(diag: pd.DataFrame) -> Path:
    top = diag.nlargest(8, "qt_internacoes").sort_values("qt_internacoes")
    top["rotulo"] = top["cid_grupo"] + " - " + top["descricao_curta"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)

    # painel A: volume
    ax = axes[0]
    ax.barh(
        top["rotulo"], top["pct_internacoes"], color=estilo.SERIES[0],
        height=0.62,
    )
    for i, v in enumerate(top["pct_internacoes"]):
        ax.text(v + 0.35, i, f"{v:.1f}%", va="center", fontsize=9,
                color=estilo.TEXT_PRIMARY, fontweight="bold")
    ax.set_xlabel("% das internacoes")
    ax.set_xlim(0, top["pct_internacoes"].max() * 1.22)
    ax.grid(axis="y", visible=False)
    estilo.titular(ax, "Volume de internacoes", "participacao no total")

    # painel B: consumo de leito
    ax = axes[1]
    ax.barh(
        top["rotulo"], top["pct_dias_leito"], color=estilo.SERIES[1],
        height=0.62,
    )
    for i, v in enumerate(top["pct_dias_leito"]):
        ax.text(v + 0.35, i, f"{v:.1f}%", va="center", fontsize=9,
                color=estilo.TEXT_PRIMARY, fontweight="bold")
    ax.set_xlabel("% dos dias de leito ocupados")
    ax.set_xlim(0, top["pct_dias_leito"].max() * 1.22)
    ax.grid(axis="y", visible=False)
    estilo.titular(ax, "Consumo de leito", "participacao nos dias de internacao")

    fig.suptitle(
        "O diagnostico que mais interna nao e o que mais ocupa leito",
        x=0.005, ha="left", fontsize=13.5, fontweight="bold",
        color=estilo.TEXT_PRIMARY, y=1.06,
    )
    fig.text(
        0.005, 1.005,
        "Esquizofrenia (F20) responde por parcela maior dos dias de leito do "
        "que do numero de internacoes - permanencia mais longa",
        fontsize=9.5, color=estilo.TEXT_SECONDARY, ha="left",
    )
    estilo.rodape(fig, FONTE)
    fig.tight_layout()

    destino = settings.ASSETS_DIR / "02_diagnosticos.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# ------------------------------------------------------ grafico 3
def g_pressao(pressao: pd.DataFrame) -> Path:
    df = pressao.sort_values("indice_pressao")
    cores = [estilo.STATUS.get(c, estilo.SERIES[0])
             for c in df["classificacao"]]

    # A altura acompanha o numero de estados: com os 27 na tela, uma altura
    # fixa esmaga os rotulos.
    altura = max(5.0, len(df) * 0.30 + 1.6)
    fig, ax = plt.subplots(figsize=(10, altura))
    ax.barh(df["nm_uf"], df["indice_pressao"], color=cores, height=0.68)

    for i, (v, c) in enumerate(zip(df["indice_pressao"], df["classificacao"])):
        ax.text(v + 1.5, i, f"{v:.0f}  ·  {c}", va="center", fontsize=8.5,
                fontweight="bold", color=estilo.TEXT_PRIMARY)

    ax.set_xlabel("Indice de Pressao Assistencial (0 a 100)")
    ax.set_xlim(0, 118)
    ax.set_ylim(-0.8, len(df) - 0.2)
    ax.grid(axis="y", visible=False)

    # Legenda de status acima do grafico, para nao cobrir barra nenhuma.
    # STATUS_ORDEM evita a duplicata das duas grafias de "Critica".
    from matplotlib.patches import Patch
    ax.legend(
        handles=[Patch(facecolor=cor, label=nome)
                 for nome, cor in estilo.STATUS_ORDEM],
        loc="lower right", bbox_to_anchor=(1.0, 1.0), ncols=4,
        title=None, frameon=False,
    )

    estilo.titular(
        ax,
        "Onde a rede de saude mental esta sob maior pressao",
        "Indice composto: demanda (50%), complexidade (30%) e "
        "escassez de leitos (20%)",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "03_pressao_assistencial.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# ------------------------------------------------------ grafico 4
def g_distribuicao(df: pd.DataFrame) -> Path:
    perm = df["qt_dias_permanencia"].dropna()
    fig, axes = plt.subplots(
        1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [2, 1]}
    )

    ax = axes[0]
    ax.hist(
        perm[perm <= 90], bins=45, color=estilo.SERIES[0],
        edgecolor=estilo.SURFACE, linewidth=0.6,
    )
    ax.axvline(perm.mean(), color=estilo.SERIES[1], linewidth=2,
               label=f"Media: {perm.mean():.1f} dias")
    ax.axvline(perm.median(), color=estilo.SERIES[2], linewidth=2,
               linestyle="--", label=f"Mediana: {perm.median():.0f} dias")
    ax.set_xlabel("Dias de permanencia")
    ax.set_ylabel("Internacoes")
    ax.legend()
    estilo.titular(ax, "Distribuicao da permanencia",
                   "assimetria a direita: poucas internacoes muito longas")

    ax = axes[1]
    grupos = ["F10", "F20", "F31", "F32"]
    dados = [
        df.loc[df["cid_grupo"] == g, "qt_dias_permanencia"].dropna()
        for g in grupos
    ]
    bp = ax.boxplot(
        dados, patch_artist=True, showfliers=False, tick_labels=grupos,
        medianprops={"color": estilo.TEXT_PRIMARY, "linewidth": 1.8},
        widths=0.55,
    )
    for caixa, cor in zip(bp["boxes"], estilo.SERIES[:4]):
        caixa.set_facecolor(cor)
        caixa.set_edgecolor(estilo.SURFACE)
    for i, d in enumerate(dados, 1):
        ax.text(i, d.median() + 1.5, f"{d.median():.0f}", ha="center",
                fontsize=9, fontweight="bold", color=estilo.TEXT_PRIMARY)
    ax.set_ylabel("Dias")
    ax.grid(axis="x", visible=False)
    estilo.titular(ax, "Por diagnostico", "mediana de dias internados")

    estilo.rodape(fig, FONTE)
    fig.tight_layout()

    destino = settings.ASSETS_DIR / "04_distribuicao_permanencia.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# ------------------------------------------------------ grafico 5
def g_correlacao(pressao: pd.DataFrame) -> tuple[Path, pd.DataFrame]:
    colunas = {
        "internacoes_por_10k_ano": "Internacoes/10k",
        "permanencia_media": "Permanencia",
        "leitos_por_10k_hab": "Leitos/10k",
        "taxa_ocupacao_pct": "Ocupacao",
        "caps_por_100k_hab": "CAPS/100k",
        "custo_per_capita": "Custo per capita",
    }
    base = pressao[list(colunas)].rename(columns=colunas)
    corr = base.corr(method="spearman")

    fig, ax = plt.subplots(figsize=(7.2, 6))
    im = ax.imshow(corr, cmap=estilo.mapa_divergente(), vmin=-1, vmax=1)

    ax.set_xticks(range(len(corr)), corr.columns, rotation=40, ha="right")
    ax.set_yticks(range(len(corr)), corr.columns)
    ax.grid(visible=False)

    for i in range(len(corr)):
        for j in range(len(corr)):
            v = corr.iloc[i, j]
            ax.text(
                j, i, f"{v:.2f}", ha="center", va="center", fontsize=9,
                fontweight="bold",
                color="white" if abs(v) > 0.62 else estilo.TEXT_PRIMARY,
            )

    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label("Correlacao de Spearman", fontsize=9)
    cb.outline.set_visible(False)

    estilo.titular(
        ax, "Relacao entre demanda e capacidade instalada",
        "Correlacao de postos entre os indicadores por UF",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "05_correlacao.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino, corr


# ------------------------------------------------------ grafico 6
def g_demografico(demo: pd.DataFrame) -> Path:
    tabela = demo.pivot_table(
        index="faixa_etaria", columns="ds_sexo",
        values="qt_internacoes", aggfunc="sum",
    ).fillna(0)
    ordem = ["0-17", "18-29", "30-44", "45-59", "60+"]
    tabela = tabela.reindex([o for o in ordem if o in tabela.index])

    fig, ax = plt.subplots(figsize=(9.5, 5))
    x = np.arange(len(tabela))
    largura = 0.38

    for i, sexo in enumerate(tabela.columns):
        pos = x + (i - 0.5) * (largura + 0.02)
        ax.bar(pos, tabela[sexo], largura, label=sexo, color=estilo.SERIES[i])
        for px, v in zip(pos, tabela[sexo]):
            ax.text(px, v + tabela.values.max() * 0.015,
                    estilo.fmt_milhar(v), ha="center", fontsize=8.5,
                    color=estilo.TEXT_PRIMARY)

    ax.set_xticks(x, tabela.index)
    ax.set_xlabel("Faixa etaria")
    ax.set_ylabel("Internacoes")
    ax.set_ylim(0, tabela.values.max() * 1.15)
    ax.grid(axis="x", visible=False)
    ax.legend(ncols=2)

    pico = tabela.sum(axis=1).idxmax()
    estilo.titular(
        ax, "Perfil demografico das internacoes",
        f"A faixa de {pico} anos concentra o maior volume de internacoes",
    )
    estilo.rodape(fig, FONTE)

    destino = settings.ASSETS_DIR / "06_perfil_demografico.png"
    fig.savefig(destino)
    plt.close(fig)
    return destino


# ------------------------------------------------------ orquestracao
def executar() -> None:
    estilo.aplicar_estilo()
    dados = carregar()

    log.info("Calculando estatisticas descritivas...")
    desc = estatisticas_descritivas(dados["analitico"])
    desc.to_csv(
        settings.PROCESSED_DIR / "eda_estatisticas_descritivas.csv", sep=";"
    )
    print("\n=== ESTATISTICAS DESCRITIVAS ===")
    print(desc.to_string())

    log.info("Gerando graficos...")
    gerados = [
        g_serie_temporal(dados["serie"]),
        g_diagnosticos(dados["diagnosticos"]),
        g_pressao(dados["pressao"]),
        g_distribuicao(dados["analitico"]),
    ]
    caminho_corr, corr = g_correlacao(dados["pressao"])
    gerados.append(caminho_corr)
    gerados.append(g_demografico(dados["demografia"]))

    corr.to_csv(settings.PROCESSED_DIR / "eda_matriz_correlacao.csv", sep=";")

    print("\n=== CORRELACOES RELEVANTES (|rho| > 0.5) ===")
    achados = []
    for i in range(len(corr)):
        for j in range(i + 1, len(corr)):
            v = corr.iloc[i, j]
            if abs(v) > 0.5:
                achado = f"{corr.index[i]} x {corr.columns[j]}: {v:.2f}"
                achados.append(achado)
                print(f"  {achado}")
    if not achados:
        print("  nenhuma correlacao forte identificada")

    (settings.PROCESSED_DIR / "eda_achados.json").write_text(
        json.dumps(
            {"correlacoes_relevantes": achados,
             "graficos": [g.name for g in gerados]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    log.info("OK: %d graficos em %s", len(gerados), settings.ASSETS_DIR)
    for g in gerados:
        log.info("  %s", g.name)


if __name__ == "__main__":
    executar()

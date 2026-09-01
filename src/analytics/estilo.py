"""
Identidade visual dos graficos do Synodos.

Paleta categorica validada para daltonismo (deuteranopia, protanopia e
tritanopia) e para contraste sobre a superficie clara. Os quatro primeiros
tons foram checados com validador automatico: pior par adjacente com
Delta E 9,1 em CVD e 22,9 em visao normal, acima dos pisos de 8 e 15.

Como os tons aqua e amarelo ficam abaixo de 3:1 de contraste sobre fundo
claro, todo grafico que os utiliza traz rotulo direto de valor - a
identidade nunca depende so da cor.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

# ------------------------------------------------------------ superficies
SURFACE = "#ffffff"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#5c5952"
TEXT_MUTED = "#8a8580"
GRID = "#e6e4e0"

# ------------------------------------------------------- cores da marca
PRETO = "#0b0b0b"
AMBAR = "#e7c12e"
AMBAR_ESCURO = "#b8860b"
CINZA = "#8a8580"

# ------------------------------------------------ paleta categorica
# Sistema monocromatico com um acento, herdado do prototipo da Sprint 1.
# O par preto/ambar tem Delta E 66,9 em daltonismo e 68,9 em visao normal.
SERIES = [PRETO, AMBAR, CINZA, AMBAR_ESCURO]

# ------------------------------------------------------- escala de status
# Ordinal: cinza neutro para "sem alarme", escurecendo com a gravidade.
# O dicionario aceita as duas grafias de "Critica" porque os CSV gerados
# pelo pipeline usam a forma sem acento; para montar legendas, use
# STATUS_ORDEM, que nao tem duplicatas.
STATUS_ORDEM = [
    ("Baixa", CINZA),
    ("Moderada", AMBAR),
    ("Alta", AMBAR_ESCURO),
    ("Crítica", PRETO),
]
STATUS = {nome: cor for nome, cor in STATUS_ORDEM}
STATUS["Critica"] = PRETO

# ----------------------------------------------- rampa sequencial (um tom)
SEQUENCIAL = ["#fdf3cd", "#f6e08c", "#e7c12e", "#c9a013", "#9b7a0d", "#6b5308"]

# --------------------------------------------------- rampa divergente
# Correlacao e um dado divergente (negativo, zero, positivo), entao exige
# dois polos com um neutro no meio - nao da para resolver so com o ambar.
# Usamos ardosia para o polo negativo e o ambar da marca para o positivo,
# com cinza neutro no zero.
DIVERGENTE_NEGATIVO = "#2f4858"
DIVERGENTE_NEUTRO = "#ecebe7"
DIVERGENTE_POSITIVO = "#b8860b"


def mapa_divergente():
    """Colormap divergente na identidade do projeto."""
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "synodos_div",
        [DIVERGENTE_NEGATIVO, "#7b8b96", DIVERGENTE_NEUTRO,
         "#d8b968", DIVERGENTE_POSITIVO],
    )


def aplicar_estilo() -> None:
    """Configura o matplotlib com a identidade do projeto."""
    disponiveis = {f.name for f in font_manager.fontManager.ttflist}
    familia = next(
        (f for f in ("DejaVu Sans", "Liberation Sans", "Arial")
         if f in disponiveis),
        "sans-serif",
    )

    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": familia,
            "font.size": 10,
            "text.color": TEXT_PRIMARY,
            "axes.labelcolor": TEXT_SECONDARY,
            "axes.edgecolor": GRID,
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2.0,
            "lines.markersize": 8,
            "figure.dpi": 130,
            "savefig.dpi": 130,
            "savefig.bbox": "tight",
        }
    )


def titular(ax, titulo: str, subtitulo: str = "") -> None:
    """Titulo em duas linhas: o que e, e o que significa."""
    ax.set_title(
        titulo, loc="left", fontsize=13, fontweight="bold",
        color=TEXT_PRIMARY, pad=18 if subtitulo else 10,
    )
    if subtitulo:
        ax.text(
            0, 1.02, subtitulo, transform=ax.transAxes,
            fontsize=9.5, color=TEXT_SECONDARY, va="bottom",
        )


def rodape(fig, texto: str) -> None:
    """Nota de fonte no rodape da figura."""
    fig.text(
        0.005, -0.02, texto, fontsize=8, color=TEXT_MUTED,
        ha="left", va="top",
    )


def fmt_milhar(valor) -> str:
    return f"{int(valor):,}".replace(",", ".")

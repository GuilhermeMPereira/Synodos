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
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED = "#8a8880"
GRID = "#e5e4df"

# ------------------------------------------------ paleta categorica (ordem fixa)
SERIES = [
    "#2a78d6",  # 1 azul
    "#eb6834",  # 2 laranja
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 amarelo
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 verde
    "#4a3aa7",  # 7 violeta
    "#e34948",  # 8 vermelho
]

# ------------------------------------------------------- paleta de status
STATUS = {
    "Baixa": "#1baf7a",
    "Moderada": "#eda100",
    "Alta": "#eb6834",
    "Critica": "#e34948",
}

# ----------------------------------------------- rampa sequencial (um tom)
SEQUENCIAL = ["#d6e4f7", "#a9c6ee", "#7aa7e2", "#4a8bd9", "#2a78d6", "#1c5aa3"]


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

"""
SYNODOS - Painel de Acesso Hospitalar e Perfil de Atendimento em Saude Mental

Dashboard do gestor de saude publica. Quatro abas:
    Panorama    KPIs, serie temporal e perfil diagnostico
    Territorio  comparacao entre estados e pressao assistencial
    Rede        leitos, CAPS e ocupacao
    Perguntar   consultas em linguagem natural (Select AI)

Executar:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings  # noqa: E402

# ------------------------------------------------------------------ paleta
# Identidade visual do Synodos: preto e ambar, herdada do prototipo da
# Sprint 1. E um sistema monocromatico com um unico acento, entao a
# diferenciacao vem da luminosidade, nao da variedade de matizes.
PRETO = "#0b0b0b"
AMBAR = "#e7c12e"
AMBAR_ESCURO = "#b8860b"
CINZA = "#8a8580"

# Paleta categorica. Os graficos deste painel usam no maximo DUAS series
# simultaneas, e o par preto/ambar tem separacao folgada: Delta E 66,9 em
# visao com daltonismo e 68,9 em visao normal, muito acima dos pisos de 8
# e 15. Os dois ultimos tons existem para eventuais terceiras series.
SERIES = [PRETO, AMBAR, CINZA, AMBAR_ESCURO]

# Escala de status, ordinal. Comeca no cinza neutro (sem alarme) e escurece
# conforme a gravidade. O rotulo textual acompanha sempre a barra, entao a
# identidade nunca depende so da cor - o que atende a regra de alivio para
# o ambar, que fica abaixo de 3:1 de contraste sobre fundo branco.
STATUS = {
    "Baixa": CINZA,
    "Moderada": AMBAR,
    "Alta": AMBAR_ESCURO,
    "Crítica": PRETO,
}

SUPERFICIE = "#ffffff"
SUPERFICIE_CARD = "#f6f6f6"
TEXT_SECONDARY = "#5c5952"
TEXT_MUTED = "#8a8580"
GRID = "#e6e4e0"
BORDA = "#dedede"

st.set_page_config(
    page_title="Synodos | Painel de Saúde Mental",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      /* ---------------------------------------------- estrutura da pagina */
      .block-container {padding-top: 1.2rem; padding-bottom: 3rem;
                        max-width: 1560px;}
      .stApp {background: #ffffff;}

      /* ------------------------------- barra lateral preta, como no topo */
      [data-testid="stSidebar"] {background: #0b0b0b;}
      [data-testid="stSidebar"] * {color: #eceae5;}
      [data-testid="stSidebar"] h1 {color: #e7c12e !important;
                                    font-size: 1.5rem !important;
                                    letter-spacing: 0.02em;}
      [data-testid="stSidebar"] label,
      [data-testid="stSidebar"] .stMarkdown p {color: #b9b5ad !important;
                                               font-size: 0.82rem;}
      [data-testid="stSidebar"] hr {border-color: #262626;}
      /* O slider mostra a selecao atual acima da trilha e os extremos da
         escala abaixo. Com o intervalo inteiro selecionado, os dois pares
         ficam iguais e parece duplicado - escondemos os extremos. */
      [data-testid="stSidebar"] [data-testid="stSliderTickBar"],
      [data-testid="stSidebar"] [data-testid="stTickBar"],
      [data-testid="stSidebar"] [data-testid="stSliderTickBarMin"],
      [data-testid="stSidebar"] [data-testid="stSliderTickBarMax"] {
          display: none !important;}
      /* campos de filtro sobre fundo escuro */
      [data-testid="stSidebar"] [data-baseweb="select"] > div,
      [data-testid="stSidebar"] [data-baseweb="input"] > div {
          background: #1a1a1a; border-color: #333330;}
      /* chips dos multiselect em ambar */
      [data-testid="stSidebar"] [data-baseweb="tag"] {
          background: #e7c12e !important;}
      [data-testid="stSidebar"] [data-baseweb="tag"] span {
          color: #0b0b0b !important; font-weight: 600;}
      [data-testid="stSidebar"] [data-testid="stMetricValue"] {
          color: #ffffff !important;}

      /* -------------------------------------------- faixa preta do topo */
      .faixa-topo {background: #0b0b0b; color: #ffffff;
                   margin: -1.2rem -3rem 1.6rem -3rem;
                   padding: 1.1rem 3rem 1.2rem 3rem;}
      .faixa-topo .marca {color: #e7c12e; font-size: 0.72rem;
                          font-weight: 700; letter-spacing: 0.16em;
                          text-transform: uppercase;}
      .faixa-topo h1 {color: #ffffff !important; font-size: 1.7rem !important;
                      font-weight: 700; margin: 0.35rem 0 0.3rem 0 !important;}
      .faixa-topo .legenda {color: #a8a49c; font-size: 0.86rem;
                            line-height: 1.45;}

      /* ------------------------------------------------------ indicadores */
      [data-testid="stMetricValue"] {font-size: 1.95rem; font-weight: 700;
                                     color: #0b0b0b;}
      [data-testid="stMetricLabel"] {font-size: 0.78rem; color: #5c5952;}

      /* ------------------------------------------------------------ abas */
      .stTabs [data-baseweb="tab-list"] {gap: 1.9rem;
                                         border-bottom: 1px solid #e6e4e0;}
      .stTabs [data-baseweb="tab"] {padding: 0.5rem 0; font-weight: 500;}
      .stTabs [aria-selected="true"] {color: #0b0b0b !important;}
      .stTabs [data-baseweb="tab-highlight"] {background: #e7c12e;}

      /* ------------------------------------------------ cartoes e blocos */
      [data-testid="stVerticalBlockBorderWrapper"] {
          background: #fbfbfa; border-radius: 10px;}
      h3 {font-size: 1.15rem !important; color: #0b0b0b;}
      .titulo-grafico {font-size: 1.02rem; font-weight: 700; color: #0b0b0b;
                       margin: 0.1rem 0 0.15rem 0;}
      .sub-grafico {font-size: 0.82rem; color: #5c5952;
                    margin: 0 0 0.6rem 0; line-height: 1.35;}
      .rodape {color:#8a8580; font-size:0.78rem; margin-top:3rem;
               border-top:1px solid #e6e4e0; padding-top:1rem;
               line-height: 1.6;}

      /* --------------------------------------------------------- botoes */
      .stButton button {border-color: #dedede; color: #0b0b0b;}
      .stButton button:hover {border-color: #e7c12e; color: #0b0b0b;
                              background: #fffbe9;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ dados
@st.cache_resource(show_spinner="Preparando os dados pela primeira vez...")
def preparar_dados_se_necessario() -> bool:
    """
    Executa o pipeline automaticamente quando a camada analitica nao existe.

    Necessario para deploy em nuvem (Streamlit Community Cloud), onde apenas
    o repositorio e clonado - os dados derivados nao sao versionados. Roda
    uma unica vez por processo e leva cerca de 20 segundos.
    """
    alvo = settings.PROCESSED_DIR / "analitico_internacoes.parquet"
    if alvo.exists():
        return False

    from src.analytics import modelos
    from src.etl import indicadores, integracao, tratamento
    from src.ingestao import gerar_amostra, ingest_csv

    gerar_amostra.executar(
        settings.UFS_PILOTO,
        settings.COMPETENCIA_INICIO,
        settings.COMPETENCIA_FIM,
    )
    ingest_csv.executar()
    tratamento.executar()
    integracao.executar()
    indicadores.executar()

    try:
        modelos.executar()
    except Exception:  # noqa: BLE001
        # A projecao e opcional: o painel funciona sem ela.
        pass

    return True


@st.cache_data(show_spinner="Carregando dados...")
def carregar():
    preparar_dados_se_necessario()
    p = settings.PROCESSED_DIR
    dados = {
        "analitico": pd.read_parquet(p / "analitico_internacoes.parquet"),
        "serie": pd.read_csv(p / "ind_serie_temporal.csv", sep=";"),
        "taxas": pd.read_csv(p / "ind_taxa_por_uf.csv", sep=";"),
        "diagnosticos": pd.read_csv(p / "ind_perfil_diagnostico.csv", sep=";"),
        "ocupacao": pd.read_csv(p / "ind_ocupacao_rede.csv", sep=";"),
        "pressao": pd.read_csv(p / "ind_pressao_assistencial.csv", sep=";"),
        "demografia": pd.read_csv(p / "ind_perfil_demografico.csv", sep=";"),
        "kpis": json.loads(
            (p / "ind_panorama_geral.json").read_text(encoding="utf-8")
        ),
    }
    caminho_proj = p / "mod_projecao.csv"
    if caminho_proj.exists():
        dados["projecao"] = pd.read_csv(caminho_proj, sep=";")
    return dados


# Nomes tecnicos das colunas traduzidos para exibicao. As consultas devolvem
# os nomes do banco; o gestor le rotulos em portugues.
COLUNAS_LEGIVEIS = {
    "ranking": "#",
    "estado": "Estado",
    "regiao": "Região",
    "indice_pressao": "IPA",
    "classificacao": "Situação",
    "internacoes_por_10k_ano": "Internações/10 mil hab.",
    "permanencia_media": "Permanência (dias)",
    "leitos_por_10k_hab": "Leitos/10 mil hab.",
    "caps_por_100k_hab": "CAPS/100 mil hab.",
    "habitantes_por_caps": "Habitantes por CAPS",
    "taxa_ocupacao_pct": "Ocupação (%)",
    "qt_internacoes": "Internações",
    "qt_leitos": "Leitos",
    "qt_caps": "CAPS",
    "qt_estabelecimentos": "Estabelecimentos",
    "populacao": "População",
    "custo_total": "Custo total (R$)",
    "custo_per_capita": "Custo per capita (R$)",
    "competencia": "Competência",
    "media_movel_3m": "Média móvel (3 meses)",
    "variacao_mensal_pct": "Variação mensal (%)",
    "cid": "CID-10",
    "descricao": "Diagnóstico",
    "pct_internacoes": "% das internações",
    "pct_dias_leito": "% dos dias de leito",
    "indice_carga_leito": "Índice de carga de leito",
    "faixa_etaria": "Faixa etária",
    "sexo": "Sexo",
    "pct": "% do total",
    "total_internacoes": "Total de internações",
    "competencias": "Competências",
    "estados": "Estados",
    "mortalidade_pct": "Mortalidade (%)",
}


MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]


# ------------------------------------------------------------------ helpers
def fmt(valor, casas: int = 0) -> str:
    """Formata numero no padrao brasileiro: 234803 -> 234.803"""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def rotulo_competencia(competencia) -> str:
    """
    Converte a competencia do SIH para algo legivel: 202301 -> jan/2023.

    O formato AAAAMM e o padrao do DATASUS, e faz sentido para quem trabalha
    com a base. Para o gestor que abre o painel, nao significa nada.
    """
    c = str(int(float(competencia)))
    return f"{MESES_ABREV[int(c[4:6]) - 1]}/{c[:4]}"


def titulo(texto: str, subtitulo: str = "") -> None:
    """
    Titulo do grafico em HTML, fora da figura.

    Os titulos nativos do Plotly ocupam a mesma faixa vertical da legenda e
    acabam se sobrepondo. Escrevendo o titulo fora, a figura fica livre para
    posicionar a legenda sem colisao.
    """
    st.markdown(f'<div class="titulo-grafico">{texto}</div>',
                unsafe_allow_html=True)
    if subtitulo:
        st.markdown(f'<div class="sub-grafico">{subtitulo}</div>',
                    unsafe_allow_html=True)


def layout_grafico(fig, altura: int = 360, legenda: bool = False):
    """
    Aplica a identidade visual e resolve dois problemas recorrentes:
    a legenda vai para baixo do grafico (nunca colide com o titulo), e a
    margem superior fica minima porque o titulo mora fora da figura.
    """
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=24, t=12, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12, color=TEXT_SECONDARY, family="Inter, -apple-system, Segoe UI, Roboto, sans-serif"),
        # Localizacao brasileira: virgula decimal e ponto de milhar.
        # O primeiro caractere e o separador decimal, o segundo o de milhar.
        # Vale para os rotulos das barras e para os tooltips.
        separators=",.",
        showlegend=legenda,
        legend=dict(
            orientation="h", yanchor="top", y=-0.24,
            xanchor="left", x=0, title=None,
        ),
        hoverlabel=dict(font_size=12),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def altura_barras(n: int, minimo: int = 340, por_barra: int = 20) -> int:
    """
    Altura proporcional ao numero de barras.

    Com os 27 estados na tela, uma altura fixa esmaga os rotulos. Cada
    categoria ganha um espaco proprio, com um piso para os recortes de
    poucos estados.
    """
    return max(minimo, n * por_barra + 60)


def folga_rotulos(fig, valores, fator: float = 1.22, eixo: str = "x"):
    """
    Reserva espaco para os rotulos escritos fora das barras.

    Sem isso o Plotly corta o texto na borda do grafico - foi o que acontecia
    com os valores dos diagnosticos ("44.465" aparecia como "4...").
    """
    maximo = float(max(valores)) if len(valores) else 1.0
    if eixo == "x":
        fig.update_xaxes(range=[0, maximo * fator])
    else:
        fig.update_yaxes(range=[0, maximo * fator])
    return fig


try:
    D = carregar()
except FileNotFoundError:
    st.error(
        "Dados não encontrados. Execute o pipeline primeiro:\n\n"
        "```\npython -m src.ingestao.gerar_amostra\n"
        "python -m src.ingestao.ingest_csv\n"
        "python -m src.etl.tratamento\n"
        "python -m src.etl.integracao\n"
        "python -m src.etl.indicadores\n"
        "python -m src.analytics.modelos\n```"
    )
    st.stop()


# ------------------------------------------------------------------ filtros
st.sidebar.title("Synodos")
st.sidebar.caption("Painel de saúde mental no SUS")
st.sidebar.divider()

df = D["analitico"]

competencias = sorted(df["competencia"].astype(str).unique())
# O usuario ve "jan/2023"; o filtro continua operando sobre "202301".
rotulos_periodo = [rotulo_competencia(c) for c in competencias]
de_rotulo = dict(zip(rotulos_periodo, competencias))

periodo_rotulo = st.sidebar.select_slider(
    "Período",
    options=rotulos_periodo,
    value=(rotulos_periodo[0], rotulos_periodo[-1]),
    help="Mês de referência da internação. Arraste as pontas para "
         "recortar o intervalo que quer analisar.",
)
periodo = (de_rotulo[periodo_rotulo[0]], de_rotulo[periodo_rotulo[1]])

ufs = sorted(df["sg_uf"].unique())
ufs_sel = st.sidebar.multiselect(
    "Estados", ufs, default=ufs,
    help="Siglas das unidades federativas. Todos os 27 estados vêm "
         "selecionados; remova os que não quiser comparar.",
)

regioes = sorted(df["regiao"].dropna().unique())
regioes_sel = st.sidebar.multiselect(
    "Regiões", regioes, default=regioes,
    help="As 5 grandes regiões do IBGE. Use para comparar Norte com "
         "Sudeste, por exemplo.",
)

diags = sorted(df["cid_grupo"].unique())
mapa_diag = (
    df[["cid_grupo", "descricao_curta"]]
    .drop_duplicates().set_index("cid_grupo")["descricao_curta"].to_dict()
)
diags_sel = st.sidebar.multiselect(
    "Diagnósticos (CID-10)", diags, default=[],
    format_func=lambda c: f"{c} — {mapa_diag.get(c, c)}",
    help="Códigos do Capítulo V da CID-10, que reúne os transtornos "
         "mentais e comportamentais. Deixe vazio para incluir todos.",
)

mask = (
    df["competencia"].astype(str).between(periodo[0], periodo[1])
    & df["sg_uf"].isin(ufs_sel)
    & df["regiao"].isin(regioes_sel)
)
if diags_sel:
    mask &= df["cid_grupo"].isin(diags_sel)

f = df[mask]

st.sidebar.divider()
st.sidebar.metric(
    "Internações no filtro", fmt(len(f)),
    help="Quantas internações restam depois dos filtros acima.",
)
if len(f) < len(df):
    st.sidebar.caption(f"{len(f) / len(df) * 100:.1f}% da base completa")

origem = settings.RAW_DIR / "_ORIGEM_AMOSTRA.txt"
if origem.exists():
    st.sidebar.divider()
    st.sidebar.caption(
        "**Amostra de demonstração** — mesma estrutura do SIH/SUS, "
        "calibrada por taxas públicas reais. Detalhes no rodapé."
    )

if f.empty:
    st.warning("Nenhum registro para os filtros selecionados.")
    st.stop()


# ------------------------------------------------------------------ cabecalho
st.markdown(
    '<div class="faixa-topo">'
    '<div class="marca">SUS Saúde Mental · Painel Integrado</div>'
    "<h1>Painel de Acesso Hospitalar em Saúde Mental</h1>"
    '<div class="legenda">Internações do SUS por transtornos mentais e '
    "comportamentais (CID-10, Capítulo V), integradas ao cadastro da rede "
    "e à população IBGE</div>"
    "</div>",
    unsafe_allow_html=True,
)
with st.expander("Como usar este painel", expanded=False):
    st.markdown(
        """
**Comece pelos filtros**, na barra à esquerda. Você pode recortar por
período, estado, região e diagnóstico. Todos os números da tela recalculam
na hora.

**As quatro abas respondem perguntas diferentes:**

| Aba | Responde |
|---|---|
| **Panorama** | Quantas internações houve, como evoluíram e quais transtornos predominam |
| **Território** | Onde a rede está sob maior pressão e como os estados se comparam |
| **Rede instalada** | Quantos leitos e CAPS existem, e o quanto estão ocupados |
| **Perguntar aos dados** | Escreva a pergunta em português e receba a resposta com o SQL usado |

**Um cuidado ao ler os números:** estados grandes sempre lideram em números
absolutos, porque têm mais habitantes. Por isso o painel usa
**internações por 10 mil habitantes** — é o que permite comparar São Paulo
com Roraima de forma justa.

Passe o mouse sobre o ícone **?** ao lado de cada indicador para ver o que
ele significa e como é calculado.
        """
    )

st.write("")

abas = st.tabs(
    ["Panorama", "Território", "Rede instalada", "Perguntar aos dados"]
)


# ================================================================ PANORAMA
with abas[0]:
    meses = f["competencia"].nunique()
    leitos = int(
        D["ocupacao"][D["ocupacao"]["sg_uf"].isin(ufs_sel)]["qt_leitos"].sum()
    )
    ocupacao = (
        f["qt_dias_permanencia"].sum() / (leitos * meses * 30.44) * 100
        if leitos else 0
    )

    with st.container(border=True):
        c = st.columns(5)
        c[0].metric(
            "Internações", fmt(len(f)),
            help="Número de internações hospitalares por transtornos "
                 "mentais no período e nos estados filtrados. Cada "
                 "internação corresponde a uma AIH (Autorização de "
                 "Internação Hospitalar) registrada no SIH/SUS.",
        )
        c[1].metric(
            "Permanência média",
            f"{fmt(f['qt_dias_permanencia'].mean(), 1)} dias",
            help="Quantos dias, em média, o paciente ficou internado. "
                 "Quanto maior, mais complexos são os casos e mais tempo "
                 "cada leito fica ocupado.",
        )
        c[2].metric(
            "Ocupação estimada", f"{ocupacao:.0f}%",
            help="Percentual da capacidade de leitos que esteve ocupada. "
                 "Calculado dividindo o total de dias-paciente pelos "
                 "leitos disponíveis multiplicados pelos dias do período. "
                 "Acima de 85% indica rede próxima da saturação.",
        )
        c[3].metric(
            "Taxa de mortalidade",
            f"{fmt(f['fl_obito'].mean() * 100, 2)}%",
            help="Percentual de internações que terminaram em óbito "
                 "durante a permanência hospitalar.",
        )
        c[4].metric(
            "Custo total",
            f"R$ {fmt(f['vl_total_aih'].sum() / 1e6, 1)} mi",
            help="Soma dos valores pagos pelo SUS por essas internações, "
                 "em milhões de reais.",
        )

    st.write("")
    esq, dir_ = st.columns([3, 2], gap="large")

    with esq:
        with st.container(border=True):
            serie = (
                f.groupby("competencia", as_index=False)
                .agg(internacoes=("nu_aih", "count"))
                .sort_values("competencia")
            )
            serie["media_movel"] = (
                serie["internacoes"].rolling(3, min_periods=1).mean()
            )
            serie["rotulo"] = serie["competencia"].map(rotulo_competencia)

            variacao = (
                serie["internacoes"].iloc[-1] / serie["internacoes"].iloc[0] - 1
            ) * 100 if len(serie) > 1 else 0

            titulo(
                "Evolução mensal das internações",
                f"Variação de {variacao:+.0f}% entre a primeira e a última "
                f"competência do período filtrado",
            )

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=serie["rotulo"], y=serie["internacoes"],
                name="Internações no mês", mode="lines+markers",
                line=dict(color=SERIES[0], width=2.5), marker=dict(size=6),
                hovertemplate="%{x}<br>%{y:,.0f} internações<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=serie["rotulo"], y=serie["media_movel"],
                name="Média móvel de 3 meses", mode="lines",
                line=dict(color=SERIES[1], width=2, dash="dash"),
                hovertemplate="%{x}<br>média %{y:,.0f}<extra></extra>",
            ))
            fig.update_yaxes(title_text="Internações")
            # Com 24 competencias os rotulos ficam verticais e colidem com a
            # legenda. Mostrar um a cada tres mantem tudo na horizontal.
            passo = max(1, len(serie) // 8)
            fig.update_xaxes(
                tickmode="array",
                tickvals=serie["rotulo"].iloc[::passo].tolist(),
                tickangle=0,
            )
            st.plotly_chart(
                layout_grafico(fig, 380, legenda=True), width="stretch"
            )

    with dir_:
        with st.container(border=True):
            diag = (
                f.groupby("descricao_curta", as_index=False)
                .agg(internacoes=("nu_aih", "count"))
                .nlargest(8, "internacoes")
                .sort_values("internacoes")
            )
            titulo(
                "Principais diagnósticos",
                "Internações no período, por transtorno",
            )

            fig = px.bar(
                diag, x="internacoes", y="descricao_curta",
                orientation="h", text="internacoes",
            )
            fig.update_traces(
                marker_color=SERIES[0], texttemplate="%{text:,}",
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}<br>%{x:,.0f} internações<extra></extra>",
            )
            fig.update_xaxes(title_text="", showticklabels=False,
                             showgrid=False)
            fig.update_yaxes(title_text="", showgrid=False)
            folga_rotulos(fig, diag["internacoes"])
            st.plotly_chart(layout_grafico(fig, 380), width="stretch")

    st.write("")
    esq2, dir2 = st.columns(2, gap="large")

    with esq2:
        with st.container(border=True):
            demo = (
                f.groupby(["faixa_etaria", "ds_sexo"], as_index=False,
                          observed=True)
                .agg(internacoes=("nu_aih", "count"))
            )
            pico = (
                demo.groupby("faixa_etaria", observed=True)["internacoes"]
                .sum().idxmax()
            )
            titulo(
                "Perfil demográfico",
                f"A faixa de {pico} anos concentra o maior volume",
            )

            fig = px.bar(
                demo, x="faixa_etaria", y="internacoes", color="ds_sexo",
                barmode="group", color_discrete_sequence=SERIES,
            )
            fig.update_traces(
                hovertemplate="%{x}<br>%{y:,.0f} internações<extra></extra>"
            )
            fig.update_xaxes(title_text="Faixa etária", showgrid=False)
            fig.update_yaxes(title_text="Internações")
            st.plotly_chart(
                layout_grafico(fig, 340, legenda=True), width="stretch"
            )

    with dir2:
        with st.container(border=True):
            if "projecao" in D and len(ufs_sel) == len(ufs):
                proj = D["projecao"].copy()
                proj["rotulo"] = proj["competencia"].map(rotulo_competencia)
                titulo(
                    "Projeção para os próximos 6 meses",
                    "Regressão com tendência e sazonalidade mensal. "
                    "Considera a base completa, sem os filtros da barra "
                    "lateral.",
                )

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=proj["rotulo"], y=proj["limite_superior"],
                    mode="lines", line=dict(width=0), showlegend=False,
                    hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=proj["rotulo"], y=proj["limite_inferior"],
                    mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(231,193,46,0.28)",
                    name="Intervalo de confiança 95%", hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=proj["rotulo"], y=proj["previsto"],
                    mode="lines+markers", name="Projetado",
                    line=dict(color=SERIES[1], width=2.5),
                    marker=dict(size=8, symbol="square"),
                    hovertemplate="%{x}<br>%{y:,.0f} previstas<extra></extra>",
                ))
                fig.update_yaxes(title_text="Internações")
                fig.update_xaxes(tickangle=0)
                st.plotly_chart(
                    layout_grafico(fig, 340, legenda=True), width="stretch"
                )
            else:
                perm = (
                    f.groupby("descricao_curta", as_index=False)
                    .agg(permanencia=("qt_dias_permanencia", "mean"))
                    .nlargest(8, "permanencia").sort_values("permanencia")
                )
                titulo(
                    "Permanência média por diagnóstico",
                    "Dias de internação, no recorte filtrado",
                )
                fig = px.bar(
                    perm, x="permanencia", y="descricao_curta",
                    orientation="h", text="permanencia",
                )
                fig.update_traces(
                    marker_color=SERIES[1], texttemplate="%{text:.0f} dias",
                    textposition="outside", cliponaxis=False,
                )
                fig.update_xaxes(title_text="", showticklabels=False,
                                 showgrid=False)
                fig.update_yaxes(title_text="", showgrid=False)
                folga_rotulos(fig, perm["permanencia"], 1.28)
                st.plotly_chart(layout_grafico(fig, 340), width="stretch")


# ================================================================ TERRITORIO
with abas[1]:
    st.subheader("Comparação entre estados")
    st.caption(
        "Números absolutos favorecem estados populosos. A taxa por 10 mil "
        "habitantes permite comparação justa entre unidades federativas."
    )
    st.write("")

    pressao = D["pressao"][D["pressao"]["sg_uf"].isin(ufs_sel)]

    esq, dir_ = st.columns(2, gap="large")

    with esq:
        with st.container(border=True):
            taxa = (
                f.groupby(["sg_uf", "nm_uf"], as_index=False)
                .agg(internacoes=("nu_aih", "count"),
                     populacao=("populacao_2022", "first"))
            )
            anos = max(f["competencia"].nunique() / 12, 1 / 12)
            taxa["por_10k"] = (
                taxa["internacoes"] / taxa["populacao"] * 10000 / anos
            ).round(2)
            taxa = taxa.sort_values("por_10k")

            titulo(
                "Internações por 10 mil habitantes",
                "Taxa anualizada, comparável entre estados",
            )
            fig = px.bar(
                taxa, x="por_10k", y="nm_uf", orientation="h", text="por_10k",
            )
            fig.update_traces(
                marker_color=SERIES[0], texttemplate="%{text:.1f}",
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}<br>%{x:.2f} por 10 mil hab./ano"
                              "<extra></extra>",
            )
            fig.update_xaxes(title_text="", showticklabels=False,
                             showgrid=False)
            fig.update_yaxes(title_text="", showgrid=False)
            folga_rotulos(fig, taxa["por_10k"], 1.18)
            st.plotly_chart(
                layout_grafico(fig, altura_barras(len(taxa))), width="stretch"
            )

    with dir_:
        with st.container(border=True):
            p = pressao.sort_values("indice_pressao")
            titulo(
                "Índice de Pressão Assistencial",
                "Demanda (50%) + complexidade (30%) + escassez de "
                "leitos (20%), normalizados de 0 a 100",
            )
            fig = go.Figure(go.Bar(
                x=p["indice_pressao"], y=p["nm_uf"], orientation="h",
                marker_color=[STATUS.get(c, SERIES[0])
                              for c in p["classificacao"]],
                text=[f"{v:.0f}  ·  {c}" for v, c
                      in zip(p["indice_pressao"], p["classificacao"])],
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}<br>IPA %{x:.0f}<extra></extra>",
            ))
            fig.update_xaxes(title_text="", showticklabels=False,
                             showgrid=False, range=[0, 132])
            fig.update_yaxes(title_text="", showgrid=False)
            st.plotly_chart(
                layout_grafico(fig, altura_barras(len(p))), width="stretch"
            )

    st.write("")
    with st.container(border=True):
        titulo("Ranking detalhado", "Todos os indicadores por estado")
        st.dataframe(
            pressao[[
                "ranking", "nm_uf", "regiao", "indice_pressao",
                "classificacao", "internacoes_por_10k_ano",
                "permanencia_media", "leitos_por_10k_hab",
                "taxa_ocupacao_pct",
            ]].rename(columns={
                "ranking": "#", "nm_uf": "Estado", "regiao": "Região",
                "indice_pressao": "IPA", "classificacao": "Situação",
                "internacoes_por_10k_ano": "Internações/10 mil hab.",
                "permanencia_media": "Permanência (dias)",
                "leitos_por_10k_hab": "Leitos/10 mil hab.",
                "taxa_ocupacao_pct": "Ocupação (%)",
            }),
            hide_index=True, width="stretch",
        )


# ================================================================ REDE
with abas[2]:
    st.subheader("Capacidade instalada da rede")
    st.caption(
        "Estabelecimentos, leitos e CAPS que compõem a Rede de Atenção "
        "Psicossocial nos estados selecionados."
    )
    st.write("")

    ocup = D["ocupacao"][D["ocupacao"]["sg_uf"].isin(ufs_sel)]

    with st.container(border=True):
        c = st.columns(4)
        c[0].metric("Leitos de saúde mental", fmt(ocup["qt_leitos"].sum()))
        c[1].metric("CAPS", fmt(ocup["qt_caps"].sum()))
        c[2].metric("Estabelecimentos",
                    fmt(ocup["qt_estabelecimentos"].sum()))
        c[3].metric("Ocupação média",
                    f"{ocup['taxa_ocupacao_pct'].mean():.0f}%")

    st.write("")
    esq, dir_ = st.columns(2, gap="large")

    with esq:
        with st.container(border=True):
            o = ocup.sort_values("taxa_ocupacao_pct")
            titulo(
                "Taxa de ocupação estimada dos leitos",
                "Dias-paciente sobre a capacidade instalada no período",
            )
            fig = px.bar(
                o, x="taxa_ocupacao_pct", y="sg_uf", orientation="h",
                text="taxa_ocupacao_pct",
            )
            fig.update_traces(
                marker_color=SERIES[2], texttemplate="%{text:.0f}%",
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}<br>%{x:.1f}% de ocupação<extra></extra>",
            )
            fig.update_xaxes(title_text="", showticklabels=False,
                             showgrid=False)
            fig.update_yaxes(title_text="", showgrid=False)
            folga_rotulos(fig, o["taxa_ocupacao_pct"], 1.18)
            st.plotly_chart(
                layout_grafico(fig, altura_barras(len(o))), width="stretch"
            )

    with dir_:
        with st.container(border=True):
            o = ocup.sort_values("leitos_por_10k_hab")
            titulo(
                "Leitos por 10 mil habitantes",
                "Densidade da capacidade instalada",
            )
            fig = px.bar(
                o, x="leitos_por_10k_hab", y="sg_uf", orientation="h",
                text="leitos_por_10k_hab",
            )
            fig.update_traces(
                marker_color=SERIES[3], texttemplate="%{text:.2f}",
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}<br>%{x:.2f} leitos por 10 mil hab."
                              "<extra></extra>",
            )
            fig.update_xaxes(title_text="", showticklabels=False,
                             showgrid=False)
            fig.update_yaxes(title_text="", showgrid=False)
            folga_rotulos(fig, o["leitos_por_10k_hab"], 1.22)
            st.plotly_chart(
                layout_grafico(fig, altura_barras(len(o))), width="stretch"
            )

    st.write("")
    with st.container(border=True):
        titulo(
            "Unidades com maior volume de internações",
            "15 estabelecimentos com mais internações no recorte filtrado",
        )
        unidades = (
            f.groupby(
                ["nm_estabelecimento", "ds_tipo_unidade", "sg_uf"],
                as_index=False,
            )
            .agg(
                internacoes=("nu_aih", "count"),
                permanencia=("qt_dias_permanencia", "mean"),
                leitos=("qt_leitos_sus", "first"),
            )
            .nlargest(15, "internacoes")
        )
        unidades["permanencia"] = unidades["permanencia"].round(1)
        st.dataframe(
            unidades.rename(columns={
                "nm_estabelecimento": "Estabelecimento",
                "ds_tipo_unidade": "Tipo", "sg_uf": "UF",
                "internacoes": "Internações",
                "permanencia": "Permanência (dias)", "leitos": "Leitos",
            }),
            hide_index=True, width="stretch",
        )


# ================================================================ PERGUNTAR
with abas[3]:
    st.subheader("Pergunte aos dados em português")
    st.caption(
        "O sistema interpreta a pergunta, gera a consulta SQL e a executa "
        "sobre os dados. Em produção, o Oracle Select AI cumpre esse papel "
        "usando os metadados do dicionário de dados. Os números não vêm do "
        "modelo de linguagem: vêm do banco."
    )
    st.write("")

    sugestoes = [
        "Quais estados estão com maior pressão assistencial?",
        "Quais transtornos consomem mais dias de leito?",
        "Como evoluíram as internações mês a mês?",
        "Qual estado tem menos leitos por habitante?",
        "Qual a faixa etária com mais internações?",
        "Qual o custo total das internações por estado?",
    ]

    if "pergunta" not in st.session_state:
        st.session_state.pergunta = sugestoes[0]

    st.markdown('<div class="sub-grafico">Sugestões</div>',
                unsafe_allow_html=True)
    cols = st.columns(3)
    for i, s in enumerate(sugestoes):
        if cols[i % 3].button(s, key=f"sug{i}", width="stretch"):
            st.session_state.pergunta = s

    st.write("")
    pergunta = st.text_input(
        "Sua pergunta",
        value=st.session_state.pergunta,
        placeholder="Escreva sua pergunta em português...",
    )

    if pergunta:
        try:
            from src.db.select_ai import perguntar

            r = perguntar(pergunta, forcar_local=True)

            if r.get("narrativa"):
                st.success(r["narrativa"])

            with st.container(border=True):
                titulo("Resultado da consulta")
                st.dataframe(
                    r["resultado"].rename(columns=COLUNAS_LEGIVEIS),
                    hide_index=True, width="stretch",
                )

            with st.expander("Ver o SQL que foi gerado e executado"):
                st.code(r["sql"], language="sql")
                st.caption(
                    f"Intenção reconhecida: `{r.get('intencao')}`  |  "
                    f"modo: `{r['modo']}`  |  "
                    "o resultado acima veio da execução deste SQL, "
                    "não do modelo de linguagem."
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Não foi possível responder: {exc}")


# ------------------------------------------------------------------ rodape
st.markdown(
    '<div class="rodape">'
    "<b>Synodos</b> &nbsp;·&nbsp; Challenge FIAP + Oracle 2026 &nbsp;·&nbsp; "
    "Turma 1TSCO<br>"
    "Fontes: SIH/SUS e CNES (Ministério da Saúde), Censo IBGE 2022 e CID-10 "
    "Capítulo V &nbsp;·&nbsp; "
    "Dados públicos e agregados, sem identificação de pacientes"
    "</div>",
    unsafe_allow_html=True,
)

with st.expander("Glossário — o que cada termo significa"):
    st.markdown(
        """
| Termo | O que é |
|---|---|
| **SIH/SUS** | Sistema de Informações Hospitalares do SUS. Registra todas as internações pagas pelo SUS no país. |
| **AIH** | Autorização de Internação Hospitalar. É o documento que autoriza e registra cada internação — uma AIH equivale a uma internação. |
| **Competência** | O mês de referência do registro no SIH, no formato ano-mês. Aqui exibimos como *jan/2023*. |
| **CNES** | Cadastro Nacional de Estabelecimentos de Saúde. Lista todos os hospitais, postos e unidades do país. |
| **CID-10, Capítulo V** | O trecho da Classificação Internacional de Doenças que reúne os transtornos mentais e comportamentais. Todos os códigos começam com a letra F. |
| **CAPS** | Centro de Atenção Psicossocial. É a unidade de referência da rede de saúde mental do SUS para atendimento diário, sem internação. |
| **RAPS** | Rede de Atenção Psicossocial. O conjunto de serviços de saúde mental do SUS: CAPS, leitos em hospital geral, ambulatórios e prontos-socorros. |
| **Permanência** | Quantos dias o paciente ficou internado. |
| **Taxa por 10 mil habitantes** | Quantas internações ocorreram para cada 10 mil pessoas que moram no estado. Permite comparar estados de tamanhos diferentes. |
| **Taxa de ocupação** | O quanto da capacidade de leitos foi usada. Acima de 85% indica rede saturada. |
| **IPA** | Índice de Pressão Assistencial. Indicador criado neste projeto: combina demanda (50%), complexidade dos casos (30%) e escassez de leitos (20%) em uma nota de 0 a 100. Quanto maior, maior a prioridade de investimento. |
        """
    )

if origem.exists():
    with st.expander("Sobre os dados exibidos nesta demonstração"):
        st.markdown(
            """
Este painel está rodando com uma **amostra de demonstração**, gerada com a
mesma estrutura de colunas dos extratores oficiais.

**O que é real:** a população por UF (Censo IBGE 2022), os códigos e
descrições do CID-10 Capítulo V, a divisão territorial oficial, e a
calibragem das taxas — internações por 10 mil habitantes, densidade de
leitos, permanência média e ocupação estão todas dentro das faixas
publicadas para o SUS.

**O que é sintético:** os registros individuais de AIH. Nenhum dado de
paciente é utilizado — o SIH/SUS é público e já anonimizado na origem.

**Por que existe:** o FTP do DATASUS é instável, e sem esse modo qualquer
pessoa que clonasse o repositório ficaria travada. Para carregar os dados
oficiais, basta rodar `python -m src.ingestao.ingest_sih`, que baixa as
competências reais do DATASUS — o restante do pipeline é idêntico.
            """
        )

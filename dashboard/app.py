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
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
STATUS = {"Baixa": "#1baf7a", "Moderada": "#eda100",
          "Alta": "#eb6834", "Critica": "#e34948"}
TEXT_SECONDARY = "#52514e"
GRID = "#e5e4df"

st.set_page_config(
    page_title="Synodos | Painel de Saude Mental",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; max-width: 1400px;}
      [data-testid="stMetricValue"] {font-size: 1.75rem;}
      [data-testid="stMetricLabel"] {font-size: 0.82rem;}
      h1 {font-size: 1.9rem !important;}
      .rodape {color:#8a8880; font-size:0.78rem; margin-top:2.5rem;
               border-top:1px solid #e5e4df; padding-top:0.9rem;}
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


def fmt(valor, casas: int = 0) -> str:
    """Formata numero no padrao brasileiro."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def layout_grafico(fig, altura: int = 380):
    fig.update_layout(
        height=altura,
        margin=dict(l=10, r=10, t=45, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


try:
    D = carregar()
except FileNotFoundError:
    st.error(
        "Dados nao encontrados. Execute o pipeline primeiro:\n\n"
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
st.sidebar.caption("Painel de saude mental no SUS")
st.sidebar.divider()

df = D["analitico"]

competencias = sorted(df["competencia"].astype(str).unique())
periodo = st.sidebar.select_slider(
    "Periodo (competencia)",
    options=competencias,
    value=(competencias[0], competencias[-1]),
)

ufs = sorted(df["sg_uf"].unique())
ufs_sel = st.sidebar.multiselect("Estados", ufs, default=ufs)

regioes = sorted(df["regiao"].dropna().unique())
regioes_sel = st.sidebar.multiselect("Regioes", regioes, default=regioes)

diags = sorted(df["cid_grupo"].unique())
diags_sel = st.sidebar.multiselect(
    "Diagnosticos (CID-10)", diags, default=[],
    help="Vazio = todos os diagnosticos",
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
st.sidebar.metric("Internacoes no filtro", fmt(len(f)))
if len(f) < len(df):
    st.sidebar.caption(f"{len(f) / len(df) * 100:.1f}% da base completa")

origem = settings.RAW_DIR / "_ORIGEM_AMOSTRA.txt"
if origem.exists():
    st.sidebar.divider()
    st.sidebar.warning(
        "**Modo amostra**\n\nOs dados exibidos foram gerados com estrutura "
        "identica a do SIH/SUS e calibrados por taxas publicas reais, mas "
        "os registros individuais sao sinteticos. Para dados oficiais, rode "
        "`python -m src.ingestao.ingest_sih`.",
        icon="⚠️",
    )

if f.empty:
    st.warning("Nenhum registro para os filtros selecionados.")
    st.stop()


# ------------------------------------------------------------------ cabecalho
st.title("Painel de Acesso Hospitalar em Saude Mental")
st.caption(
    "Internacoes do SUS por transtornos mentais e comportamentais "
    "(CID-10, Capitulo V) integradas ao cadastro da rede e a populacao IBGE"
)

abas = st.tabs(
    ["Panorama", "Territorio", "Rede instalada", "Perguntar aos dados"]
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

    c = st.columns(5)
    c[0].metric("Internacoes", fmt(len(f)))
    c[1].metric("Permanencia media", f"{f['qt_dias_permanencia'].mean():.1f} dias")
    c[2].metric("Ocupacao estimada", f"{ocupacao:.0f}%")
    c[3].metric("Taxa de mortalidade", f"{f['fl_obito'].mean() * 100:.2f}%")
    c[4].metric("Custo total", f"R$ {fmt(f['vl_total_aih'].sum() / 1e6, 1)} mi")

    st.divider()

    esq, dir_ = st.columns([3, 2])

    with esq:
        serie = (
            f.groupby("competencia", as_index=False)
            .agg(internacoes=("nu_aih", "count"))
            .sort_values("competencia")
        )
        serie["media_movel"] = (
            serie["internacoes"].rolling(3, min_periods=1).mean()
        )
        serie["rotulo"] = (
            serie["competencia"].astype(str).str[4:6] + "/"
            + serie["competencia"].astype(str).str[2:4]
        )

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=serie["rotulo"], y=serie["internacoes"], name="Internacoes",
            mode="lines+markers", line=dict(color=SERIES[0], width=2.5),
            marker=dict(size=7),
        ))
        fig.add_trace(go.Scatter(
            x=serie["rotulo"], y=serie["media_movel"],
            name="Media movel 3 meses", mode="lines",
            line=dict(color=SERIES[1], width=2, dash="dash"),
        ))
        fig.update_layout(title="Evolucao mensal das internacoes")
        st.plotly_chart(layout_grafico(fig), width="stretch")

    with dir_:
        diag = (
            f.groupby("descricao_curta", as_index=False)
            .agg(internacoes=("nu_aih", "count"))
            .nlargest(8, "internacoes")
            .sort_values("internacoes")
        )
        fig = px.bar(
            diag, x="internacoes", y="descricao_curta", orientation="h",
            text="internacoes",
        )
        fig.update_traces(
            marker_color=SERIES[0], texttemplate="%{text:,}",
            textposition="outside",
        )
        fig.update_layout(
            title="Principais diagnosticos", xaxis_title="", yaxis_title="",
            showlegend=False,
        )
        st.plotly_chart(layout_grafico(fig), width="stretch")

    esq2, dir2 = st.columns(2)

    with esq2:
        demo = (
            f.groupby(["faixa_etaria", "ds_sexo"], as_index=False,
                      observed=True)
            .agg(internacoes=("nu_aih", "count"))
        )
        fig = px.bar(
            demo, x="faixa_etaria", y="internacoes", color="ds_sexo",
            barmode="group", color_discrete_sequence=SERIES,
        )
        fig.update_layout(
            title="Perfil demografico", xaxis_title="Faixa etaria",
            yaxis_title="Internacoes", legend_title="",
        )
        st.plotly_chart(layout_grafico(fig, 340), width="stretch")

    with dir2:
        if "projecao" in D and len(ufs_sel) == len(ufs):
            proj = D["projecao"].copy()
            proj["rotulo"] = (
                proj["competencia"].astype(str).str[4:6] + "/"
                + proj["competencia"].astype(str).str[2:4]
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
                fillcolor="rgba(235,104,52,0.18)",
                name="Intervalo 95%", hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=proj["rotulo"], y=proj["previsto"], mode="lines+markers",
                name="Projetado", line=dict(color=SERIES[1], width=2.5),
                marker=dict(size=8, symbol="square"),
            ))
            fig.update_layout(
                title="Projecao para os proximos 6 meses",
                yaxis_title="Internacoes",
            )
            st.plotly_chart(layout_grafico(fig, 340), width="stretch")
            st.caption(
                "Regressao com tendencia e sazonalidade mensal. "
                "A projecao considera a base completa, sem os filtros."
            )
        else:
            perm = (
                f.groupby("descricao_curta", as_index=False)
                .agg(permanencia=("qt_dias_permanencia", "mean"))
                .nlargest(8, "permanencia").sort_values("permanencia")
            )
            fig = px.bar(
                perm, x="permanencia", y="descricao_curta", orientation="h",
                text="permanencia",
            )
            fig.update_traces(
                marker_color=SERIES[1], texttemplate="%{text:.0f}d",
                textposition="outside",
            )
            fig.update_layout(
                title="Permanencia media por diagnostico",
                xaxis_title="Dias", yaxis_title="", showlegend=False,
            )
            st.plotly_chart(layout_grafico(fig, 340), width="stretch")


# ================================================================ TERRITORIO
with abas[1]:
    st.subheader("Comparacao entre estados")
    st.caption(
        "Numeros absolutos favorecem estados populosos. A taxa por 10 mil "
        "habitantes permite comparacao justa entre unidades federativas."
    )

    pressao = D["pressao"][D["pressao"]["sg_uf"].isin(ufs_sel)]

    esq, dir_ = st.columns(2)

    with esq:
        taxa = (
            f.groupby(["sg_uf", "nm_uf"], as_index=False)
            .agg(internacoes=("nu_aih", "count"),
                 populacao=("populacao_2022", "first"))
        )
        anos = f["competencia"].nunique() / 12
        taxa["por_10k"] = (
            taxa["internacoes"] / taxa["populacao"] * 10000 / anos
        ).round(2)
        taxa = taxa.sort_values("por_10k")

        fig = px.bar(
            taxa, x="por_10k", y="nm_uf", orientation="h", text="por_10k",
        )
        fig.update_traces(
            marker_color=SERIES[0], texttemplate="%{text:.1f}",
            textposition="outside",
        )
        fig.update_layout(
            title="Internacoes por 10 mil habitantes/ano",
            xaxis_title="", yaxis_title="", showlegend=False,
        )
        st.plotly_chart(layout_grafico(fig), width="stretch")

    with dir_:
        p = pressao.sort_values("indice_pressao")
        fig = go.Figure(go.Bar(
            x=p["indice_pressao"], y=p["nm_uf"], orientation="h",
            marker_color=[STATUS.get(c, SERIES[0])
                          for c in p["classificacao"]],
            text=[f"{v:.0f} ({c})" for v, c
                  in zip(p["indice_pressao"], p["classificacao"])],
            textposition="outside",
        ))
        fig.update_layout(
            title="Indice de Pressao Assistencial",
            xaxis_title="0 a 100", xaxis_range=[0, 115],
        )
        st.plotly_chart(layout_grafico(fig), width="stretch")
        st.caption(
            "Demanda (50%) + complexidade (30%) + escassez de leitos (20%)"
        )

    st.divider()
    st.markdown("**Ranking detalhado**")
    st.dataframe(
        pressao[[
            "ranking", "nm_uf", "regiao", "indice_pressao", "classificacao",
            "internacoes_por_10k_ano", "permanencia_media",
            "leitos_por_10k_hab", "taxa_ocupacao_pct",
        ]].rename(columns={
            "ranking": "#", "nm_uf": "Estado", "regiao": "Regiao",
            "indice_pressao": "IPA", "classificacao": "Situacao",
            "internacoes_por_10k_ano": "Internacoes/10k",
            "permanencia_media": "Permanencia (dias)",
            "leitos_por_10k_hab": "Leitos/10k",
            "taxa_ocupacao_pct": "Ocupacao (%)",
        }),
        hide_index=True, width="stretch",
    )


# ================================================================ REDE
with abas[2]:
    st.subheader("Capacidade instalada da rede")

    ocup = D["ocupacao"][D["ocupacao"]["sg_uf"].isin(ufs_sel)]

    c = st.columns(4)
    c[0].metric("Leitos de saude mental", fmt(ocup["qt_leitos"].sum()))
    c[1].metric("CAPS", fmt(ocup["qt_caps"].sum()))
    c[2].metric("Estabelecimentos", fmt(ocup["qt_estabelecimentos"].sum()))
    c[3].metric(
        "Ocupacao media", f"{ocup['taxa_ocupacao_pct'].mean():.0f}%"
    )

    st.divider()
    esq, dir_ = st.columns(2)

    with esq:
        o = ocup.sort_values("taxa_ocupacao_pct")
        fig = px.bar(
            o, x="taxa_ocupacao_pct", y="sg_uf", orientation="h",
            text="taxa_ocupacao_pct",
        )
        fig.update_traces(
            marker_color=SERIES[2], texttemplate="%{text:.0f}%",
            textposition="outside",
        )
        fig.update_layout(
            title="Taxa de ocupacao estimada dos leitos",
            xaxis_title="", yaxis_title="", showlegend=False,
        )
        st.plotly_chart(layout_grafico(fig), width="stretch")

    with dir_:
        o = ocup.sort_values("leitos_por_10k_hab")
        fig = px.bar(
            o, x="leitos_por_10k_hab", y="sg_uf", orientation="h",
            text="leitos_por_10k_hab",
        )
        fig.update_traces(
            marker_color=SERIES[3], texttemplate="%{text:.2f}",
            textposition="outside",
        )
        fig.update_layout(
            title="Leitos por 10 mil habitantes",
            xaxis_title="", yaxis_title="", showlegend=False,
        )
        st.plotly_chart(layout_grafico(fig), width="stretch")

    st.markdown("**Unidades com maior volume de internacoes**")
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
            "internacoes": "Internacoes",
            "permanencia": "Permanencia (dias)", "leitos": "Leitos",
        }),
        hide_index=True, width="stretch",
    )


# ================================================================ PERGUNTAR
with abas[3]:
    st.subheader("Pergunte aos dados em portugues")
    st.caption(
        "O sistema interpreta a pergunta, gera a consulta SQL e a executa "
        "sobre os dados. Em producao, o Oracle Select AI cumpre esse papel "
        "usando os metadados do dicionario de dados."
    )

    sugestoes = [
        "Quais estados estao com maior pressao assistencial?",
        "Quais os cinco transtornos que mais consomem dias de leito?",
        "Como evoluiram as internacoes mes a mes?",
        "Qual estado tem menos leitos por habitante?",
        "Qual a faixa etaria com mais internacoes?",
        "Qual o custo total das internacoes por estado?",
    ]

    if "pergunta" not in st.session_state:
        st.session_state.pergunta = sugestoes[0]

    st.markdown("**Sugestoes**")
    cols = st.columns(3)
    for i, s in enumerate(sugestoes):
        if cols[i % 3].button(s, key=f"sug{i}", width="stretch"):
            st.session_state.pergunta = s

    pergunta = st.text_input(
        "Sua pergunta", value=st.session_state.pergunta,
        label_visibility="collapsed",
    )

    if st.button("Consultar", type="primary") or pergunta:
        try:
            from src.db.select_ai import perguntar

            r = perguntar(pergunta, forcar_local=True)

            if r.get("narrativa"):
                st.success(r["narrativa"])

            st.dataframe(
                r["resultado"], hide_index=True, width="stretch"
            )

            with st.expander("SQL gerado e executado"):
                st.code(r["sql"], language="sql")
                st.caption(
                    f"Intencao reconhecida: `{r.get('intencao')}` | "
                    f"modo: `{r['modo']}`"
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Nao foi possivel responder: {exc}")


# ------------------------------------------------------------------ rodape
st.markdown(
    '<div class="rodape">'
    "<b>Synodos</b> &nbsp;|&nbsp; FIAP + Oracle Challenge 2026 &nbsp;|&nbsp; "
    "Fontes: SIH/SUS e CNES (Ministerio da Saude), Censo IBGE 2022 "
    "&nbsp;|&nbsp; Dados publicos e agregados, sem identificacao de pacientes"
    "</div>",
    unsafe_allow_html=True,
)

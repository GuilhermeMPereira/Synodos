"""
Validacao ponta a ponta do pipeline.

Executa cada etapa em ordem, a partir de um estado limpo, e verifica as
invariantes que precisam valer no final. Serve como teste de regressao e como
prova, para o avaliador, de que o projeto roda do zero em uma maquina nova.

Uso:
    python scripts/validar_pipeline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd  # noqa: E402

from config import settings  # noqa: E402

ETAPAS = [
    ("Gerar amostra calibrada", "src.ingestao.gerar_amostra"),
    ("Validar CSV de referencia", "src.ingestao.ingest_csv"),
    ("Tratamento e qualidade", "src.etl.tratamento"),
    ("Integracao das 3 fontes", "src.etl.integracao"),
    ("Indicadores de gestao", "src.etl.indicadores"),
    ("Analise exploratoria", "src.analytics.eda"),
    ("Modelos analiticos", "src.analytics.modelos"),
]

ARQUIVOS_ESPERADOS = [
    "data/raw/sih_internacoes.parquet",
    "data/raw/cnes_estabelecimentos.json",
    "data/processed/analitico_internacoes.parquet",
    "data/processed/relatorio_qualidade.json",
    "data/processed/ind_panorama_geral.json",
    "data/processed/ind_pressao_assistencial.csv",
    "data/processed/mod_projecao.csv",
    "data/processed/mod_relatorio.json",
] + [
    f"assets/graficos/0{i}_{nome}.png"
    for i, nome in enumerate(
        ["serie_temporal", "diagnosticos", "pressao_assistencial",
         "distribuicao_permanencia", "correlacao", "perfil_demografico",
         "clusters", "projecao", "decomposicao"],
        start=1,
    )
]


class Falha(Exception):
    pass


def executar_etapas() -> None:
    print("=" * 72)
    print("EXECUCAO DO PIPELINE")
    print("=" * 72)

    for i, (titulo, modulo) in enumerate(ETAPAS, 1):
        print(f"\n[{i}/{len(ETAPAS)}] {titulo}")
        r = subprocess.run(
            [sys.executable, "-m", modulo],
            cwd=BASE, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stdout[-2500:])
            print(r.stderr[-2500:])
            raise Falha(f"Etapa falhou: {modulo}")
        print("      ok")


def verificar_arquivos() -> None:
    print("\n" + "=" * 72)
    print("ARQUIVOS GERADOS")
    print("=" * 72)

    faltando = []
    for caminho in ARQUIVOS_ESPERADOS:
        alvo = BASE / caminho
        if alvo.exists():
            print(f"  ok    {caminho:56s} {alvo.stat().st_size / 1024:>8.0f} KB")
        else:
            print(f"  FALTA {caminho}")
            faltando.append(caminho)

    if faltando:
        raise Falha(f"{len(faltando)} arquivo(s) nao gerado(s)")


def verificar_invariantes() -> None:
    print("\n" + "=" * 72)
    print("INVARIANTES DOS DADOS")
    print("=" * 72)

    df = pd.read_parquet(
        settings.PROCESSED_DIR / "analitico_internacoes.parquet"
    )
    kpis = json.loads(
        (settings.PROCESSED_DIR / "ind_panorama_geral.json")
        .read_text(encoding="utf-8")
    )
    pressao = pd.read_csv(
        settings.PROCESSED_DIR / "ind_pressao_assistencial.csv", sep=";"
    )
    modelos = json.loads(
        (settings.PROCESSED_DIR / "mod_relatorio.json")
        .read_text(encoding="utf-8")
    )

    checagens = [
        ("base nao vazia", len(df) > 1000, f"{len(df)} linhas"),
        ("nu_aih unico",
         df["nu_aih"].is_unique, "sem duplicatas"),
        ("todos os CID sao do Capitulo V",
         df["cid_principal"].str.startswith("F").all(), "prefixo F"),
        ("permanencia dentro da faixa",
         df["qt_dias_permanencia"].between(0, 365).all(), "0 a 365 dias"),
        ("idade dentro da faixa",
         df["nu_idade"].between(0, 110).all(), "0 a 110 anos"),
        ("juncao com CNES completa",
         df["nm_estabelecimento"].notna().all(), "sem orfaos"),
        ("juncao com territorio completa",
         df["nm_uf"].notna().all(), "sem orfaos"),
        ("populacao positiva",
         (df["populacao_2022"] > 0).all(), "denominador valido"),
        ("obito e binario",
         df["fl_obito"].isin([0, 1]).all(), "0 ou 1"),
        ("IPA entre 0 e 100",
         pressao["indice_pressao"].between(0, 100).all(), "escala correta"),
        ("ranking sem lacunas",
         sorted(pressao["ranking"]) == list(range(1, len(pressao) + 1)),
         f"1 a {len(pressao)}"),
    ]

    # Faixas de plausibilidade epidemiologica
    taxa = pressao["internacoes_por_10k_ano"]
    leitos = pressao["leitos_por_10k_hab"]
    checagens += [
        ("taxa de internacao plausivel",
         taxa.between(3, 25).all(),
         f"{taxa.min():.1f} a {taxa.max():.1f} por 10 mil hab/ano"),
        ("densidade de leitos plausivel",
         leitos.between(0.2, 3.0).all(),
         f"{leitos.min():.2f} a {leitos.max():.2f} por 10 mil hab"),
        ("permanencia media plausivel",
         8 <= kpis["permanencia_media_dias"] <= 40,
         f"{kpis['permanencia_media_dias']} dias"),
        ("ocupacao plausivel",
         20 <= kpis["taxa_ocupacao_estimada_pct"] <= 100,
         f"{kpis['taxa_ocupacao_estimada_pct']}%"),
        ("mortalidade plausivel",
         0 < kpis["taxa_mortalidade_pct"] < 5,
         f"{kpis['taxa_mortalidade_pct']}%"),
    ]

    # Coerencia dos modelos
    proj = modelos["projecao"]
    checagens += [
        ("modelo recupera a tendencia embutida",
         abs(proj["tendencia_anualizada_pct"] - 6.0) < 2.0,
         f"{proj['tendencia_anualizada_pct']}% ao ano (esperado ~6%)"),
        ("crescimento YoY coerente com a tendencia",
         abs(proj["crescimento_yoy_projetado_pct"]
             - proj["tendencia_anualizada_pct"]) < 3.0,
         f"YoY {proj['crescimento_yoy_projetado_pct']}% vs tendencia "
         f"{proj['tendencia_anualizada_pct']}%"),
        ("silhueta positiva",
         modelos["clusterizacao"]["silhueta_final"] > 0,
         f"{modelos['clusterizacao']['silhueta_final']}"),
    ]

    falhas = 0
    for nome, condicao, detalhe in checagens:
        marca = "ok   " if condicao else "FALHA"
        print(f"  {marca} {nome:44s} {detalhe}")
        if not condicao:
            falhas += 1

    if falhas:
        raise Falha(f"{falhas} invariante(s) violada(s)")


def verificar_linguagem_natural() -> None:
    print("\n" + "=" * 72)
    print("PERGUNTAS EM LINGUAGEM NATURAL")
    print("=" * 72)

    from src.db.select_ai import perguntar

    perguntas = [
        "Quais estados estao com maior pressao assistencial?",
        "Quais transtornos consomem mais dias de leito?",
        "Como evoluiram as internacoes mes a mes?",
        "Qual estado tem menos leitos por habitante?",
        "Qual a faixa etaria com mais internacoes?",
        "Qual o custo total das internacoes por estado?",
        "Qual o total de internacoes no periodo?",
    ]

    falhas = 0
    for p in perguntas:
        try:
            r = perguntar(p, forcar_local=True)
            if r["resultado"].empty:
                raise ValueError("resultado vazio")
            print(f"  ok    {p[:52]:54s} -> {len(r['resultado']):>3} linhas "
                  f"[{r['intencao']}]")
        except Exception as exc:  # noqa: BLE001
            print(f"  FALHA {p[:52]:54s} -> {exc}")
            falhas += 1

    if falhas:
        raise Falha(f"{falhas} pergunta(s) sem resposta")


def verificar_dashboard() -> None:
    print("\n" + "=" * 72)
    print("DASHBOARD")
    print("=" * 72)

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  aviso: streamlit nao instalado, verificacao pulada")
        return

    at = AppTest.from_file(
        str(BASE / "dashboard" / "app.py"), default_timeout=240
    ).run()

    if at.exception:
        for e in at.exception:
            print(f"  FALHA {e.value}")
        raise Falha("dashboard levantou excecao")

    print(f"  ok    abas renderizadas                        {len(at.tabs)}")
    print(f"  ok    indicadores exibidos                     {len(at.metric)}")
    print(f"  ok    tabelas exibidas                         {len(at.dataframe)}")

    if len(at.tabs) != 4:
        raise Falha(f"esperadas 4 abas, encontradas {len(at.tabs)}")


def main() -> int:
    print("\nSYNODOS - VALIDACAO DO PIPELINE\n")

    try:
        executar_etapas()
        verificar_arquivos()
        verificar_invariantes()
        verificar_linguagem_natural()
        verificar_dashboard()
    except Falha as exc:
        print(f"\n{'=' * 72}\nRESULTADO: FALHOU - {exc}\n{'=' * 72}")
        return 1

    print("\n" + "=" * 72)
    print("RESULTADO: PIPELINE VALIDADO COM SUCESSO")
    print("=" * 72 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

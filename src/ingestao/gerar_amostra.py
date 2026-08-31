"""
GERADOR DE AMOSTRA REPRESENTATIVA - modo offline do pipeline.

Por que existe: o FTP do DATASUS e a API do CNES nem sempre estao acessiveis
(instabilidade do servico, rede corporativa, ambiente de CI). Para que o
pipeline, os indicadores, o notebook e o dashboard possam ser executados e
validados por qualquer avaliador sem depender dessas fontes, este modulo
gera uma amostra com a MESMA estrutura de colunas dos extratores reais.

O que e real nesta amostra:
  - populacao por UF (IBGE, Censo 2022) - data/reference/uf_populacao.csv
  - codigos e descricoes CID-10 do Capitulo V - data/reference/
  - codigos IBGE de UF e a divisao regional oficial
  - taxa nacional de internacao psiquiatrica calibrada em ~9,6 por 10 mil
    habitantes/ano, ordem de grandeza publicada pelo SIH/SUS
  - distribuicao proporcional dos grupos diagnosticos e tempos medios de
    permanencia por CID, coerentes com a literatura do SIH

O que e sintetico: os registros individuais de AIH. Nenhum dado de paciente
real e utilizado - o SIH/SUS e publico e anonimizado, e a amostra aqui e
gerada estatisticamente.

IMPORTANTE: os numeros exibidos no dashboard em modo amostra sao
representativos, nao oficiais. Para dados oficiais rode ingest_sih.py.

Uso:
    python -m src.ingestao.gerar_amostra
    python -m src.ingestao.gerar_amostra --ufs SP,RJ --inicio 202301 --fim 202412
"""
from __future__ import annotations

import argparse
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
log = logging.getLogger("gerar_amostra")

# Taxa nacional de internacao psiquiatrica por 10 mil habitantes/ano
TAXA_BASE_10K_ANO = 9.6

# Distribuicao proporcional dos diagnosticos principais.
#
# Cobre os 10 blocos do Capitulo V do CID-10, com pesos por bloco proximos
# aos publicados para internacoes psiquiatricas no SUS:
#   F10-F19 substancias psicoativas .... 33%
#   F20-F29 esquizofrenia e psicoses ... 30%
#   F30-F39 transtornos do humor ....... 24%
#   F40-F48 neuroticos e estresse ......  5%
#   F00-F09 organicos ..................  3%
#   F60-F69 personalidade ..............  2,2%
#   F70-F79 retardo mental .............  1%
#   F90-F98 infancia e adolescencia ....  0,8%
#   F50-F59 sindromes comportamentais ..  0,6%
#   F80-F89 desenvolvimento ............  0,4%
DISTRIBUICAO_CID = {
    # F00-F09 - organicos
    "F00": 0.009, "F01": 0.007, "F03": 0.006,
    "F05": 0.005, "F06": 0.002, "F09": 0.001,
    # F10-F19 - substancias psicoativas
    "F10": 0.180, "F19": 0.070, "F14": 0.036, "F12": 0.014,
    "F13": 0.009, "F11": 0.008, "F15": 0.007, "F17": 0.003,
    "F16": 0.002, "F18": 0.001,
    # F20-F29 - esquizofrenia e outras psicoses
    "F20": 0.190, "F29": 0.038, "F23": 0.030, "F25": 0.026,
    "F22": 0.008, "F28": 0.005, "F21": 0.003,
    # F30-F39 - transtornos do humor
    "F31": 0.105, "F32": 0.070, "F33": 0.045,
    "F30": 0.014, "F34": 0.004, "F39": 0.002,
    # F40-F48 - neuroticos, estresse e somatoformes
    "F41": 0.020, "F43": 0.016, "F42": 0.006,
    "F40": 0.004, "F44": 0.002, "F45": 0.002,
    # F50-F59 - sindromes comportamentais
    "F50": 0.005, "F51": 0.001,
    # F60-F69 - personalidade
    "F60": 0.015, "F61": 0.004, "F63": 0.003,
    # F70-F79 - retardo mental
    "F70": 0.005, "F71": 0.003, "F72": 0.0015, "F79": 0.0005,
    # F80-F89 - desenvolvimento
    "F84": 0.004,
    # F90-F98 - infancia e adolescencia
    "F90": 0.004, "F91": 0.003, "F92": 0.001,
}

# Perfil da Rede de Atencao Psicossocial (RAPS).
# (codigo CNES, descricao, habitantes por unidade, prob. de ter leito,
#  faixa de leitos psiquiatricos SUS)
#
# Calibragem: a densidade nacional de leitos psiquiatricos SUS gira em torno
# de 0,7 leito por 10 mil habitantes, e o Brasil mantem aproximadamente um
# CAPS a cada 75 mil habitantes. Os parametros abaixo reproduzem essa ordem
# de grandeza - leitos gerais NAO entram, apenas os da rede de saude mental.
PERFIL_UNIDADES = [
    ("70", "CAPS", 75_000, 0.20, (3, 5)),
    ("02", "CENTRO DE SAUDE/UNIDADE BASICA", 40_000, 0.00, (0, 0)),
    ("05", "HOSPITAL GERAL", 500_000, 1.00, (6, 24)),
    ("07", "HOSPITAL ESPECIALIZADO", 5_000_000, 1.00, (60, 180)),
    ("20", "PRONTO SOCORRO GERAL", 400_000, 0.85, (2, 6)),
    ("21", "PRONTO SOCORRO ESPECIALIZADO", 1_200_000, 0.90, (4, 12)),
    ("36", "CLINICA/AMBULATORIO ESPECIALIZADO", 200_000, 0.00, (0, 0)),
]


def _competencias(inicio: str, fim: str) -> pd.PeriodIndex:
    return pd.period_range(
        pd.Period(f"{inicio[:4]}-{inicio[4:]}", freq="M"),
        pd.Period(f"{fim[:4]}-{fim[4:]}", freq="M"),
        freq="M",
    )


def _fator_sazonal(mes: int) -> float:
    """Sazonalidade leve: pico no inverno/inicio da primavera."""
    return 1.0 + 0.11 * np.sin((mes - 3) / 12 * 2 * np.pi)


def gerar_estabelecimentos(
    territorio: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """Gera a rede CNES por UF, proporcional a populacao."""
    linhas = []
    codigos = iter(range(2000001, 9999999))

    for _, uf in territorio.iterrows():
        pop = uf["populacao_2022"]

        for tipo, descricao, hab_por_unidade, prob_leito, faixa in (
            PERFIL_UNIDADES
        ):
            # Quantidade de unidades proporcional a populacao da UF.
            #
            # O arredondamento e probabilistico de proposito. Forcar um
            # minimo de uma unidade por tipo distorceria as UFs pequenas:
            # Roraima tem 637 mil habitantes, e um hospital psiquiatrico
            # especializado (1 a cada 5 milhoes de habitantes) sozinho ja
            # colocaria a densidade de leitos acima de 1,5 por 10 mil - o
            # dobro da media nacional. Aqui, uma UF com 0,13 do criterio
            # tem 13% de chance de receber a unidade.
            esperado = pop / hab_por_unidade
            total = int(esperado)
            if rng.random() < (esperado - total):
                total += 1

            # Todo estado brasileiro tem pelo menos um CAPS e uma UBS.
            if tipo in ("70", "02"):
                total = max(1, total)

            lo, hi = faixa

            # O porte da unidade acompanha o porte do estado. Um hospital
            # psiquiatrico em Roraima nao tem o mesmo numero de leitos que
            # um em Sao Paulo; sem essa escala, uma unica unidade grande
            # sorteada para uma UF pequena inflava a densidade de leitos
            # para varias vezes a media nacional. Aplicado so as unidades
            # de grande porte (40 leitos ou mais).
            if hi >= 40:
                escala = min(1.0, max(0.30, pop / hab_por_unidade))
                lo, hi = max(6, int(lo * escala)), max(10, int(hi * escala))

            for _ in range(total):
                tem_leito = hi > 0 and rng.random() < prob_leito
                leitos = int(rng.integers(lo, hi + 1)) if tem_leito else 0

                linhas.append(
                    {
                        "co_cnes": str(next(codigos)).zfill(7),
                        "nm_estabelecimento": (
                            f"{descricao.title()} {uf['sg_uf']} "
                            f"{rng.integers(1, 999):03d}"
                        ),
                        "co_municipio": (
                            f"{uf['co_uf']}{rng.integers(1000, 9999):04d}"
                        ),
                        "sg_uf": uf["sg_uf"],
                        "co_tipo_unidade": tipo,
                        "ds_tipo_unidade": descricao,
                        "qt_leitos_sus": leitos,
                        "fl_atende_sus": True,
                        "latitude": None,
                        "longitude": None,
                    }
                )

    df = pd.DataFrame(linhas)
    log.info(
        "Rede CNES gerada: %d estabelecimentos | %s leitos SUS",
        len(df), f"{int(df['qt_leitos_sus'].sum()):,}".replace(",", "."),
    )
    return df


def gerar_internacoes(
    territorio: pd.DataFrame,
    cnes: pd.DataFrame,
    cid_ref: pd.DataFrame,
    competencias: pd.PeriodIndex,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Gera as AIH do Capitulo V com a estrutura do SIH/SUS."""
    permanencia = dict(
        zip(cid_ref["cid10"], cid_ref["permanencia_esperada_dias"])
    )
    cids = list(DISTRIBUICAO_CID.keys())
    probs = np.array(list(DISTRIBUICAO_CID.values()))
    probs /= probs.sum()

    # Unidades com leito sao as que efetivamente internam
    internadores = cnes[cnes["qt_leitos_sus"] > 0]

    partes: list[pd.DataFrame] = []
    n_meses = len(competencias)

    for _, uf in territorio.iterrows():
        pool = internadores[internadores["sg_uf"] == uf["sg_uf"]]
        if pool.empty:
            continue

        # Cada UF tem um nivel proprio de acesso a rede (+-25%)
        fator_uf = float(rng.normal(1.0, 0.16))
        fator_uf = float(np.clip(fator_uf, 0.62, 1.42))

        for i, comp in enumerate(competencias):
            # Tendencia de crescimento de ~6% ao ano na demanda
            tendencia = 1.0 + 0.06 * (i / 12)
            esperado = (
                uf["populacao_2022"] / 10000
                * TAXA_BASE_10K_ANO / 12
                * fator_uf
                * tendencia
                * _fator_sazonal(comp.month)
            )
            n = int(rng.poisson(max(esperado, 0)))
            if n == 0:
                continue

            escolhidos = pool.sample(n=n, replace=True, random_state=int(
                rng.integers(0, 2**31 - 1)
            ))
            cid_sorteado = rng.choice(cids, size=n, p=probs)

            base_perm = np.array(
                [permanencia.get(c, 12) for c in cid_sorteado], dtype=float
            )
            dias = np.maximum(
                1, rng.gamma(shape=3.0, scale=base_perm / 3.0)
            ).round().astype(int)

            dia_inicio = rng.integers(1, comp.days_in_month + 1, size=n)
            dt_inter = pd.to_datetime(
                {
                    "year": comp.year,
                    "month": comp.month,
                    "day": dia_inicio,
                }
            )

            idade = np.clip(rng.normal(39, 14, size=n), 12, 92).astype(int)
            sexo = rng.choice([1, 3], size=n, p=[0.57, 0.43])
            obito = rng.binomial(1, 0.011, size=n)
            valor = np.round(
                rng.gamma(shape=2.2, scale=dias * 78 / 2.2), 2
            )

            partes.append(
                pd.DataFrame(
                    {
                        "nu_aih": [
                            f"{comp.year}{comp.month:02d}"
                            f"{rng.integers(10**8, 10**9)}"
                            for _ in range(n)
                        ],
                        "ano_competencia": comp.year,
                        "mes_competencia": comp.month,
                        "co_uf_gestor": uf["co_uf"],
                        "sg_uf": uf["sg_uf"],
                        "co_municipio_residencia": (
                            escolhidos["co_municipio"].values
                        ),
                        "co_municipio_internacao": (
                            escolhidos["co_municipio"].values
                        ),
                        "co_cnes": escolhidos["co_cnes"].values,
                        "cid_principal": cid_sorteado,
                        "cid_grupo": cid_sorteado,
                        "dt_internacao": dt_inter.values,
                        "dt_saida": (
                            dt_inter + pd.to_timedelta(dias, unit="D")
                        ).values,
                        "qt_dias_permanencia": dias,
                        "nu_idade": idade,
                        "co_unidade_idade": 3,
                        "co_sexo": sexo,
                        "fl_obito": obito,
                        "vl_total_aih": valor,
                        "co_carater_internacao": rng.choice(
                            ["01", "02"], size=n, p=[0.18, 0.82]
                        ),
                    }
                )
            )

        log.info("  %s: competencias geradas (%d meses)", uf["sg_uf"], n_meses)

    df = pd.concat(partes, ignore_index=True)
    log.info(
        "Internacoes geradas: %s AIH",
        f"{len(df):,}".replace(",", "."),
    )
    return df


def executar(ufs: list[str], inicio: str, fim: str) -> None:
    rng = np.random.default_rng(settings.SEED)

    territorio = pd.read_csv(
        settings.REFERENCE_DIR / "uf_populacao.csv", sep=";",
        dtype={"co_uf": str},
    )
    alvo = [u.strip().upper() for u in ufs]
    if alvo != ["TODAS"]:
        territorio = territorio[territorio["sg_uf"].isin(alvo)]
    if territorio.empty:
        raise ValueError(f"Nenhuma UF valida em {ufs}")

    cid_ref = pd.read_csv(
        settings.REFERENCE_DIR / "cid10_saude_mental.csv", sep=";"
    )
    competencias = _competencias(inicio, fim)

    log.info(
        "Gerando amostra | %d UFs | %d competencias (%s a %s)",
        len(territorio), len(competencias), inicio, fim,
    )

    cnes = gerar_estabelecimentos(territorio, rng)
    sih = gerar_internacoes(territorio, cnes, cid_ref, competencias, rng)

    sih.to_parquet(settings.RAW_DIR / "sih_internacoes.parquet", index=False)
    cnes.to_parquet(
        settings.RAW_DIR / "cnes_estabelecimentos.parquet", index=False
    )
    (settings.RAW_DIR / "cnes_estabelecimentos.json").write_text(
        json.dumps(
            cnes.to_dict(orient="records"), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    (settings.RAW_DIR / "_ORIGEM_AMOSTRA.txt").write_text(
        "Dados gerados por src/ingestao/gerar_amostra.py (modo offline).\n"
        "Estrutura identica a dos extratores reais SIH/SUS e CNES.\n"
        "Populacao, CID-10 e divisao territorial sao dados reais (IBGE/MS).\n"
        "Para dados oficiais: python -m src.ingestao.ingest_sih\n",
        encoding="utf-8",
    )

    log.info("OK: amostra gravada em %s", settings.RAW_DIR)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gerador de amostra offline")
    ap.add_argument("--ufs", default=",".join(settings.UFS_PILOTO))
    ap.add_argument("--inicio", default=settings.COMPETENCIA_INICIO)
    ap.add_argument("--fim", default=settings.COMPETENCIA_FIM)
    args = ap.parse_args()
    executar(args.ufs.split(","), args.inicio, args.fim)


if __name__ == "__main__":
    main()

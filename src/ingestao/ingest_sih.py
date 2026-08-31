"""
FONTE 1 (RELACIONAL) - Internacoes hospitalares do SIH/SUS.

O Sistema de Informacoes Hospitalares do SUS (SIH/SUS) publica as AIH
(Autorizacoes de Internacao Hospitalar) em arquivos .dbc no FTP do DATASUS,
particionados por UF e competencia (AAAAMM).

Este modulo extrai as internacoes do Capitulo V do CID-10 (transtornos
mentais e comportamentais, prefixo "F") e grava uma tabela relacional
normalizada em Parquet, pronta para carga no Oracle Autonomous Database.

Uso:
    python -m src.ingestao.ingest_sih
    python -m src.ingestao.ingest_sih --ufs SP,RJ --inicio 202401 --fim 202412

Requer conexao com o FTP do DATASUS (ftp.datasus.gov.br).
Se o PySUS nao estiver instalado ou o FTP estiver inacessivel, o script
avisa e sugere `python -m src.ingestao.gerar_amostra`.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("ingest_sih")

# Colunas da AIH que interessam ao projeto (nomes originais do SIH/SUS)
COLUNAS_SIH = [
    "N_AIH",       # numero da AIH (chave da internacao)
    "ANO_CMPT",    # ano da competencia
    "MES_CMPT",    # mes da competencia
    "UF_ZI",       # UF do gestor
    "MUNIC_RES",   # municipio de residencia do paciente (IBGE 6 digitos)
    "MUNIC_MOV",   # municipio do estabelecimento
    "CNES",        # estabelecimento executante
    "DIAG_PRINC",  # CID-10 principal
    "DIAG_SECUN",  # CID-10 secundario
    "DT_INTER",    # data de internacao (AAAAMMDD)
    "DT_SAIDA",    # data de saida (AAAAMMDD)
    "DIAS_PERM",   # dias de permanencia
    "IDADE",       # idade
    "COD_IDADE",   # unidade da idade (3 = anos)
    "SEXO",        # 1 masculino, 3 feminino
    "MORTE",       # 1 = obito
    "VAL_TOT",     # valor total da AIH
    "CAR_INT",     # carater da internacao (01 eletivo, 02 urgencia)
]

RENOMEIO = {
    "N_AIH": "nu_aih",
    "ANO_CMPT": "ano_competencia",
    "MES_CMPT": "mes_competencia",
    "UF_ZI": "co_uf_gestor",
    "MUNIC_RES": "co_municipio_residencia",
    "MUNIC_MOV": "co_municipio_internacao",
    "CNES": "co_cnes",
    "DIAG_PRINC": "cid_principal",
    "DIAG_SECUN": "cid_secundario",
    "DT_INTER": "dt_internacao",
    "DT_SAIDA": "dt_saida",
    "DIAS_PERM": "qt_dias_permanencia",
    "IDADE": "nu_idade",
    "COD_IDADE": "co_unidade_idade",
    "SEXO": "co_sexo",
    "MORTE": "fl_obito",
    "VAL_TOT": "vl_total_aih",
    "CAR_INT": "co_carater_internacao",
}


def _competencias(inicio: str, fim: str) -> list[tuple[int, int]]:
    """Expande o intervalo AAAAMM em pares (ano, mes)."""
    ini = pd.Period(f"{inicio[:4]}-{inicio[4:]}", freq="M")
    end = pd.Period(f"{fim[:4]}-{fim[4:]}", freq="M")
    if end < ini:
        raise ValueError("Competencia final anterior a inicial.")
    return [(p.year, p.month) for p in pd.period_range(ini, end, freq="M")]


def baixar_competencia(uf: str, ano: int, mes: int) -> pd.DataFrame:
    """Baixa uma competencia do SIH/SUS (RD = AIH reduzida) via PySUS."""
    try:
        from pysus.online_data.SIH import download
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PySUS nao instalado. Rode: pip install pysus"
        ) from exc

    log.info("Baixando SIH/SUS %s %04d-%02d ...", uf, ano, mes)
    arquivos = download(uf, ano, mes)

    # PySUS retorna ParquetSet, caminho ou DataFrame dependendo da versao
    if hasattr(arquivos, "to_dataframe"):
        df = arquivos.to_dataframe()
    elif isinstance(arquivos, pd.DataFrame):
        df = arquivos
    elif isinstance(arquivos, (list, tuple)) and arquivos:
        df = pd.concat(
            [pd.read_parquet(a) for a in arquivos], ignore_index=True
        )
    else:
        df = pd.read_parquet(arquivos)

    return df


def filtrar_saude_mental(df: pd.DataFrame) -> pd.DataFrame:
    """Mantem apenas internacoes do Capitulo V do CID-10 (prefixo F)."""
    if "DIAG_PRINC" not in df.columns:
        return df.iloc[0:0]
    mask = (
        df["DIAG_PRINC"]
        .astype(str)
        .str.upper()
        .str.startswith(settings.PREFIXO_CID_SAUDE_MENTAL)
    )
    return df.loc[mask].copy()


def padronizar(df: pd.DataFrame) -> pd.DataFrame:
    """Seleciona colunas de interesse e aplica nomes de negocio."""
    existentes = [c for c in COLUNAS_SIH if c in df.columns]
    faltantes = set(COLUNAS_SIH) - set(existentes)
    if faltantes:
        log.warning("Colunas ausentes na competencia: %s", sorted(faltantes))

    out = df[existentes].rename(columns=RENOMEIO)

    # O CID vem com 4 posicoes (ex.: F200). O agrupamento do projeto usa 3.
    if "cid_principal" in out.columns:
        out["cid_principal"] = (
            out["cid_principal"].astype(str).str.upper().str.strip()
        )
        out["cid_grupo"] = out["cid_principal"].str[:3]

    for col in ("qt_dias_permanencia", "nu_idade", "vl_total_aih", "fl_obito"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in ("dt_internacao", "dt_saida"):
        if col in out.columns:
            out[col] = pd.to_datetime(
                out[col], format="%Y%m%d", errors="coerce"
            )

    return out


def executar(ufs: list[str], inicio: str, fim: str) -> Path:
    """Executa a ingestao completa e grava o Parquet consolidado."""
    partes: list[pd.DataFrame] = []

    for uf in ufs:
        for ano, mes in _competencias(inicio, fim):
            try:
                bruto = baixar_competencia(uf.strip(), ano, mes)
            except Exception as exc:  # noqa: BLE001
                log.error("Falha em %s %04d-%02d: %s", uf, ano, mes, exc)
                continue

            filtrado = filtrar_saude_mental(bruto)
            log.info(
                "  %s %04d-%02d -> %d AIH totais | %d saude mental",
                uf, ano, mes, len(bruto), len(filtrado),
            )
            if filtrado.empty:
                continue

            pronto = padronizar(filtrado)
            pronto["sg_uf"] = uf.strip().upper()
            partes.append(pronto)

    if not partes:
        raise RuntimeError(
            "Nenhum dado obtido do SIH/SUS. Verifique a conexao com "
            "ftp.datasus.gov.br ou use: python -m src.ingestao.gerar_amostra"
        )

    consolidado = pd.concat(partes, ignore_index=True)
    destino = settings.RAW_DIR / "sih_internacoes.parquet"
    consolidado.to_parquet(destino, index=False)

    log.info("OK: %d internacoes gravadas em %s", len(consolidado), destino)
    return destino


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestao SIH/SUS (relacional)")
    ap.add_argument("--ufs", default=",".join(settings.UFS_PILOTO))
    ap.add_argument("--inicio", default=settings.COMPETENCIA_INICIO)
    ap.add_argument("--fim", default=settings.COMPETENCIA_FIM)
    args = ap.parse_args()

    executar(args.ufs.split(","), args.inicio, args.fim)


if __name__ == "__main__":
    main()

"""
FONTE 2 (JSON / SEMIESTRUTURADO) - Cadastro de estabelecimentos do CNES.

O CNES (Cadastro Nacional de Estabelecimentos de Saude) e exposto pela API
publica do Ministerio da Saude em formato REST/JSON. Este modulo consome a
API paginada, preserva o documento JSON original (para carga em coluna
JSON nativa do Oracle) e extrai em paralelo um recorte tabular com os
campos usados nos indicadores (leitos, tipo de unidade, municipio).

O JSON e mantido intacto de proposito: o requisito do challenge pede o uso
justificado de um formato semiestruturado, e o cadastro CNES muda de schema
entre competencias - guardar o documento cru evita perda de informacao.

Uso:
    python -m src.ingestao.ingest_cnes
    python -m src.ingestao.ingest_cnes --ufs SP,RJ --limite 5000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
)
log = logging.getLogger("ingest_cnes")

TIMEOUT = 30
PAGINA = 100

# Tipos de unidade relevantes para a rede de saude mental
TIPOS_INTERESSE = {
    "70": "CAPS",
    "36": "CLINICA/AMBULATORIO ESPECIALIZADO",
    "05": "HOSPITAL GERAL",
    "07": "HOSPITAL ESPECIALIZADO",
    "02": "CENTRO DE SAUDE/UNIDADE BASICA",
    "73": "PRONTO ATENDIMENTO",
    "21": "PRONTO SOCORRO ESPECIALIZADO",
    "20": "PRONTO SOCORRO GERAL",
}


def consultar_pagina(uf: str, offset: int, limite: int = PAGINA) -> list[dict]:
    """Consulta uma pagina da API CNES."""
    url = f"{settings.CNES_API_BASE}/estabelecimentos"
    params = {"uf": uf, "limit": limite, "offset": offset}

    resp = requests.get(
        url, params=params, timeout=TIMEOUT,
        headers={"accept": "application/json"},
    )
    resp.raise_for_status()
    payload = resp.json()

    if isinstance(payload, dict):
        for chave in ("estabelecimentos", "content", "data", "items"):
            if chave in payload:
                return payload[chave]
        return []
    return payload if isinstance(payload, list) else []


def coletar_uf(uf: str, limite_total: int = 20000) -> list[dict]:
    """Percorre a API paginada ate esgotar os registros da UF."""
    registros: list[dict] = []
    offset = 0

    while offset < limite_total:
        try:
            pagina = consultar_pagina(uf, offset)
        except Exception as exc:  # noqa: BLE001
            log.error("Erro na pagina offset=%d de %s: %s", offset, uf, exc)
            break

        if not pagina:
            break

        registros.extend(pagina)
        log.info("  %s: %d estabelecimentos acumulados", uf, len(registros))
        offset += PAGINA
        time.sleep(0.25)  # cortesia com a API publica

    return registros


def _primeiro(doc: dict, *chaves, default=None):
    """Retorna o primeiro campo presente no documento (schema varia)."""
    for c in chaves:
        if c in doc and doc[c] not in (None, ""):
            return doc[c]
    return default


def achatar(documentos: list[dict]) -> pd.DataFrame:
    """Extrai do JSON o recorte tabular usado pelos indicadores."""
    linhas = []
    for doc in documentos:
        codigo_tipo = str(
            _primeiro(doc, "codigo_tipo_unidade", "co_tipo_unidade", default="")
        ).zfill(2)

        linhas.append(
            {
                "co_cnes": str(
                    _primeiro(doc, "codigo_cnes", "co_cnes", default="")
                ).zfill(7),
                "nm_estabelecimento": _primeiro(
                    doc, "nome_fantasia", "nome_razao_social",
                    "no_fantasia", default="",
                ),
                "co_municipio": str(
                    _primeiro(doc, "codigo_municipio", "co_municipio_gestor",
                              default="")
                ),
                "sg_uf": _primeiro(doc, "uf", "sg_uf", default=""),
                "co_tipo_unidade": codigo_tipo,
                "ds_tipo_unidade": TIPOS_INTERESSE.get(codigo_tipo, "OUTROS"),
                "qt_leitos_sus": pd.to_numeric(
                    _primeiro(doc, "quantidade_leitos", "qt_leitos",
                              default=0),
                    errors="coerce",
                ),
                "fl_atende_sus": _primeiro(
                    doc, "estabelecimento_faz_atendimento_ambulatorial_sus",
                    "st_atende_sus", default=None,
                ),
                "latitude": pd.to_numeric(
                    _primeiro(doc, "latitude", default=None), errors="coerce"
                ),
                "longitude": pd.to_numeric(
                    _primeiro(doc, "longitude", default=None), errors="coerce"
                ),
            }
        )

    return pd.DataFrame(linhas)


def executar(ufs: list[str]) -> tuple[Path, Path]:
    """Coleta o CNES, grava o JSON cru e o recorte tabular."""
    todos: list[dict] = []

    for uf in ufs:
        log.info("Coletando CNES da UF %s ...", uf.strip().upper())
        todos.extend(coletar_uf(uf.strip().upper()))

    if not todos:
        raise RuntimeError(
            "Nenhum estabelecimento retornado pela API CNES. "
            "Verifique a conexao ou use: python -m src.ingestao.gerar_amostra"
        )

    # 1) documento JSON original - vai para coluna JSON nativa do Oracle
    destino_json = settings.RAW_DIR / "cnes_estabelecimentos.json"
    destino_json.write_text(
        json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) recorte tabular - usado nos joins e indicadores
    df = achatar(todos)
    destino_parquet = settings.RAW_DIR / "cnes_estabelecimentos.parquet"
    df.to_parquet(destino_parquet, index=False)

    log.info(
        "OK: %d estabelecimentos | JSON: %s | Parquet: %s",
        len(todos), destino_json, destino_parquet,
    )
    return destino_json, destino_parquet


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingestao CNES (JSON)")
    ap.add_argument("--ufs", default=",".join(settings.UFS_PILOTO))
    args = ap.parse_args()
    executar(args.ufs.split(","))


if __name__ == "__main__":
    main()

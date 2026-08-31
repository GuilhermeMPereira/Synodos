"""
Configuracoes centrais do projeto Synodos.

Le variaveis de ambiente (arquivo .env) e define os caminhos do projeto.
Nenhuma credencial fica versionada: use .env.example como modelo.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv e opcional
    pass

# ---------------------------------------------------------------- caminhos
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REFERENCE_DIR = DATA_DIR / "reference"
EXPORTS_DIR = DATA_DIR / "exports"
ASSETS_DIR = BASE_DIR / "assets" / "graficos"
SQL_DIR = BASE_DIR / "sql"

for _d in (RAW_DIR, PROCESSED_DIR, EXPORTS_DIR, ASSETS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- oracle
ORACLE_USER = os.getenv("ORACLE_USER", "SYNODOS")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
ORACLE_DSN = os.getenv("ORACLE_DSN", "synodosdb_high")
ORACLE_WALLET_DIR = os.getenv("ORACLE_WALLET_DIR", "")
ORACLE_WALLET_PASSWORD = os.getenv("ORACLE_WALLET_PASSWORD", "")

# ---------------------------------------------------------------- select ai
# Provedor padrao: "oci" (OCI Generative AI). Autentica pelo resource
# principal do proprio Autonomous Database, sem chave de API paga. Exige
# tenancy em regiao suportada - sa-saopaulo-1 (Brazil East) esta na lista.
# Alternativa: "openai", que exige OPENAI_API_KEY.
SELECT_AI_PROFILE = os.getenv("SELECT_AI_PROFILE", "SYNODOS_AI")
SELECT_AI_PROVIDER = os.getenv("SELECT_AI_PROVIDER", "oci")
SELECT_AI_REGION = os.getenv("SELECT_AI_REGION", "sa-saopaulo-1")
SELECT_AI_MODEL = os.getenv("SELECT_AI_MODEL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------- ingestao
# Competencias no formato AAAAMM. Padrao: 24 meses de 2023-2024.
COMPETENCIA_INICIO = os.getenv("COMPETENCIA_INICIO", "202301")
COMPETENCIA_FIM = os.getenv("COMPETENCIA_FIM", "202412")

# UFs priorizadas no piloto (Sudeste + Sul). Use "TODAS" para o Brasil inteiro.
UFS_PILOTO = os.getenv("UFS_PILOTO", "SP,RJ,MG,ES,PR,SC,RS").split(",")

# Capitulo V do CID-10 (transtornos mentais e comportamentais)
PREFIXO_CID_SAUDE_MENTAL = "F"

# API publica do Ministerio da Saude (CNES)
CNES_API_BASE = os.getenv(
    "CNES_API_BASE", "https://apidadosabertos.saude.gov.br/cnes"
)

# ---------------------------------------------------------------- indicadores
# Parametros dos indicadores assistenciais
PRESSAO_PESO_INTERNACAO = 0.5
PRESSAO_PESO_PERMANENCIA = 0.3
PRESSAO_PESO_LEITOS = 0.2

SEED = 42  # reprodutibilidade do gerador de amostra

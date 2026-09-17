"""
Conexao com o Oracle Autonomous Database.

Usa o driver oficial python-oracledb em modo thin: nao exige instalacao do
Oracle Instant Client, apenas a wallet baixada do console OCI.
"""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import settings  # noqa: E402

log = logging.getLogger("oracle_conn")


def conectar():
    """Abre uma conexao com o Autonomous Database."""
    try:
        import oracledb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Driver ausente. Rode: pip install oracledb"
        ) from exc

    if not settings.ORACLE_PASSWORD:
        raise RuntimeError(
            "ORACLE_PASSWORD nao definida. Copie .env.example para .env "
            "e preencha as credenciais."
        )

    parametros = {
        "user": settings.ORACLE_USER,
        "password": settings.ORACLE_PASSWORD,
        "dsn": settings.ORACLE_DSN,
    }

    # Conexao TLS mutua via wallet (padrao do Autonomous Database)
    if settings.ORACLE_WALLET_DIR:
        parametros.update(
            {
                "config_dir": settings.ORACLE_WALLET_DIR,
                "wallet_location": settings.ORACLE_WALLET_DIR,
                "wallet_password": settings.ORACLE_WALLET_PASSWORD,
            }
        )

    log.info("Conectando ao Oracle (%s)...", settings.ORACLE_DSN)
    conexao = oracledb.connect(**parametros)

    # Teto de tempo para qualquer chamada nesta conexao.
    #
    # Sem isto, uma chamada ao DBMS_CLOUD_AI.GENERATE que nunca volta -
    # porque o servico de Generative AI nao respondeu, ou a conta nao tem
    # direito a ele - deixa a aplicacao pendurada para sempre, com o
    # spinner girando e nenhuma mensagem na tela. Com o teto, a chamada
    # falha, o painel cai para o modo local e diz o que aconteceu.
    conexao.call_timeout = settings.ORACLE_CALL_TIMEOUT_MS
    return conexao


@contextmanager
def cursor():
    """Context manager que garante commit e fechamento."""
    conexao = conectar()
    try:
        cur = conexao.cursor()
        yield cur
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def testar_conexao() -> bool:
    """Valida a conectividade e imprime a versao do banco."""
    try:
        with cursor() as cur:
            cur.execute(
                "SELECT banner_full FROM v$version WHERE ROWNUM = 1"
            )
            (versao,) = cur.fetchone()
            print(f"[OK] Conectado: {versao}")

            cur.execute("SELECT SYSTIMESTAMP FROM DUAL")
            print(f"[OK] Horario do servidor: {cur.fetchone()[0]}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[ERRO] Falha na conexao: {exc}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(0 if testar_conexao() else 1)

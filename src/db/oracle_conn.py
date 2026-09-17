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


def wallet_em_disco() -> str:
    """
    Caminho da wallet, materializando-a quando ela vier codificada.

    No deploy em nuvem nao existe pasta de wallet: o Streamlit Community
    Cloud so clona o repositorio, e a wallet nunca pode ser versionada -
    ela da acesso ao banco. A saida e guardar o zip da wallet em base64
    como secret e reconstruir a pasta em tempo de execucao, num diretorio
    temporario que morre com o processo.

    Em maquina local nada disso acontece: ORACLE_WALLET_DIR aponta para a
    pasta baixada do console OCI e o resto e ignorado.
    """
    if settings.ORACLE_WALLET_DIR and Path(settings.ORACLE_WALLET_DIR).is_dir():
        return settings.ORACLE_WALLET_DIR

    if not settings.ORACLE_WALLET_B64:
        return ""

    import base64
    import tempfile
    import zipfile
    from io import BytesIO

    destino = Path(tempfile.gettempdir()) / "synodos_wallet"
    if not (destino / "tnsnames.ora").exists():
        destino.mkdir(parents=True, exist_ok=True)
        bruto = base64.b64decode(settings.ORACLE_WALLET_B64)
        with zipfile.ZipFile(BytesIO(bruto)) as z:
            z.extractall(destino)
        log.info("Wallet reconstruida em %s", destino)

    return str(destino)


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
    wallet = wallet_em_disco()
    if wallet:
        parametros.update(
            {
                "config_dir": wallet,
                "wallet_location": wallet,
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

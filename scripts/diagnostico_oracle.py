"""
Diagnostico da conexao com o Oracle e do Select AI, passo a passo.

Cada etapa depende da anterior. O script para na primeira que falhar e diz
o que fazer - em vez de devolver um traceback generico no meio da gravacao.

Uso:
    python scripts/diagnostico_oracle.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402

OK = "  [ok]   "
FALHA = "  [FALHA]"


def secao(n: int, titulo: str) -> None:
    print(f"\n{n}. {titulo}")
    print("   " + "-" * 66)


def parar(mensagem: str, comoresolver: str) -> None:
    print(f"{FALHA} {mensagem}")
    print(f"\n   COMO RESOLVER: {comoresolver}\n")
    sys.exit(1)


def main() -> None:
    print("\n" + "=" * 72)
    print("DIAGNOSTICO - ORACLE AUTONOMOUS DATABASE E SELECT AI")
    print("=" * 72)

    # ---------------------------------------------------------------- 1
    secao(1, "Credenciais no .env")

    faltando = [
        nome for nome in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN")
        if not getattr(settings, nome, "")
    ]
    if faltando:
        parar(
            f"faltando no .env: {', '.join(faltando)}",
            "preencha essas variaveis no arquivo .env da raiz do projeto.",
        )

    print(f"{OK} usuario  : {settings.ORACLE_USER}")
    print(f"{OK} dsn      : {settings.ORACLE_DSN}")
    print(f"{OK} senha    : definida ({len(settings.ORACLE_PASSWORD)} chars)")

    wallet = settings.ORACLE_WALLET_DIR
    if wallet:
        p = Path(wallet)
        if not p.is_dir():
            parar(
                f"ORACLE_WALLET_DIR aponta para '{wallet}', que nao existe",
                "corrija o caminho no .env, ou baixe a wallet de novo no "
                "console OCI em Database connection > Download wallet.",
            )
        if not (p / "tnsnames.ora").exists():
            parar(
                f"a pasta '{wallet}' nao tem tnsnames.ora",
                "aponte para a pasta DESCOMPACTADA da wallet, nao para o zip.",
            )
        print(f"{OK} wallet   : {wallet}")
    else:
        print("  [aviso] sem wallet configurada - so funciona se a instancia "
              "aceitar TLS simples.")

    # ---------------------------------------------------------------- 2
    secao(2, "Driver oracledb")

    try:
        import oracledb
        print(f"{OK} oracledb {oracledb.__version__} instalado")
    except ImportError:
        parar(
            "o pacote oracledb nao esta instalado",
            "rode:  pip install oracledb",
        )

    # ---------------------------------------------------------------- 3
    secao(3, "Conexao com a instancia")

    kw = dict(
        user=settings.ORACLE_USER,
        password=settings.ORACLE_PASSWORD,
        dsn=settings.ORACLE_DSN,
    )
    if wallet:
        kw.update(
            config_dir=wallet,
            wallet_location=wallet,
            wallet_password=settings.ORACLE_WALLET_PASSWORD,
        )

    try:
        con = oracledb.connect(**kw)
    except Exception as exc:                          # noqa: BLE001
        texto = str(exc)
        if "DPY-6005" in texto or "timed out" in texto.lower():
            dica = ("o banco provavelmente esta parado (Always Free hiberna "
                    "com 7 dias sem uso). Abra o console OCI e clique em "
                    "More actions > Start. Se estiver Available, veja se a "
                    "sua rede nao bloqueia a porta 1522.")
        elif "ORA-01017" in texto:
            dica = ("usuario ou senha errados. Confira ORACLE_USER e "
                    "ORACLE_PASSWORD no .env.")
        elif "DPY-4026" in texto or "tnsnames" in texto.lower():
            dica = ("a wallet nao foi encontrada. Confira ORACLE_WALLET_DIR.")
        elif "ORA-12154" in texto:
            dica = (f"o DSN '{settings.ORACLE_DSN}' nao existe no "
                    "tnsnames.ora da wallet. Abra o arquivo e use um dos "
                    "nomes listados (geralmente terminam em _high).")
        else:
            dica = "leia a mensagem acima; foi o driver que recusou."
        print(f"{FALHA} {texto.splitlines()[0]}")
        print(f"\n   COMO RESOLVER: {dica}\n")
        sys.exit(1)

    # Sem teto de tempo, o passo 6 pode ficar pendurado para sempre.
    con.call_timeout = settings.ORACLE_CALL_TIMEOUT_MS

    cur = con.cursor()
    cur.execute("SELECT banner_full FROM v$version")
    print(f"{OK} conectado: {cur.fetchone()[0].splitlines()[0]}")

    # ---------------------------------------------------------------- 4
    secao(4, "Tabelas e views carregadas")

    esperados = [
        ("fato_internacao", "tabela"),
        ("dim_estabelecimento", "tabela"),
        ("cnes_documento", "tabela"),
        ("dim_territorio", "tabela"),
        ("dim_cid10", "tabela"),
        ("vw_pressao_assistencial", "view"),
        ("vw_perfil_diagnostico", "view"),
        ("vw_taxa_por_uf", "view"),
        ("vw_ocupacao_rede", "view"),
        ("vw_integracao_tres_formatos", "view"),
    ]
    ausentes = []
    for nome, tipo in esperados:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {nome}")
            print(f"{OK} {nome:32} {cur.fetchone()[0]:>8} linhas")
        except Exception as exc:                      # noqa: BLE001
            print(f"{FALHA} {nome:32} {str(exc).splitlines()[0][:40]}")
            ausentes.append((nome, tipo))

    if ausentes:
        print(f"\n   COMO RESOLVER: rode o sql/00_setup_rapido.sql no "
              f"Database Actions como ADMIN (Ctrl+A e depois F5), e "
              f"em seguida a carga:  python -m src.db.carga_oracle\n")
        sys.exit(1)

    # ---------------------------------------------------------------- 5
    secao(5, "Perfil do Select AI")

    try:
        cur.execute("SELECT profile_name FROM user_cloud_ai_profiles")
        perfis = [r[0] for r in cur.fetchall()]
    except Exception as exc:                          # noqa: BLE001
        parar(
            f"nao consegui ler os perfis: {str(exc).splitlines()[0]}",
            "confirme que voce esta conectado como ADMIN.",
        )

    alvo = settings.SELECT_AI_PROFILE
    if alvo.upper() not in [p.upper() for p in perfis]:
        parar(
            f"o perfil '{alvo}' nao existe (existentes: {perfis or 'nenhum'})",
            "rode o sql/05_select_ai_setup.sql no Database Actions, "
            "conectado como ADMIN.",
        )
    print(f"{OK} perfil '{alvo}' existe")

    cur.execute(
        "SELECT credential_name FROM all_credentials "
        "WHERE credential_name = 'OCI$RESOURCE_PRINCIPAL'"
    )
    if not cur.fetchone():
        parar(
            "a credencial OCI$RESOURCE_PRINCIPAL nao existe",
            "rode como ADMIN:  EXEC "
            "DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL();",
        )
    print(f"{OK} credencial OCI$RESOURCE_PRINCIPAL presente")

    # ---------------------------------------------------------------- 6
    secao(6, "Gerar SQL a partir de uma pergunta em portugues")

    pergunta = "Quais estados estao com maior pressao assistencial"
    print(f"   (ate {settings.ORACLE_CALL_TIMEOUT_MS // 1000}s; esta etapa "
          f"sai do banco e vai ao OCI Generative AI)")
    try:
        cur.execute(
            """SELECT DBMS_CLOUD_AI.GENERATE(
                   prompt => :1, profile_name => :2, action => 'showsql'
               ) FROM DUAL""",
            [pergunta, alvo],
        )
        (lob,) = cur.fetchone()
        sql = (lob.read() if hasattr(lob, "read") else str(lob)).strip()
    except Exception as exc:                          # noqa: BLE001
        texto = str(exc)
        if "ORA-20401" in texto or "authoriz" in texto.lower():
            dica = ("a politica IAM nao esta valendo. No console OCI, em "
                    "Identity & Security > Policies, confirme:\n"
                    "   allow any-user to manage generative-ai-family in "
                    "tenancy where request.principal.type = "
                    "'autonomousdatabase'\n"
                    "   Depois de criar, a politica leva alguns minutos "
                    "para propagar.")
        elif "ORA-20404" in texto:
            dica = ("o object_list do perfil aponta para um objeto que nao "
                    "existe. Rode o sql/04 e recrie o perfil com o sql/05.")
        elif "DPY-4011" in texto or "timeout" in texto.lower():
            dica = (
                "a chamada saiu do banco e o OCI Generative AI nao "
                "respondeu. O banco esta bem - o que falta e do lado do "
                "servico de IA. Tres causas, nesta ordem de probabilidade:\n"
                "\n"
                "   1. Conta Free Tier. O OCI Generative AI e um servico "
                "pago e nao entra no Always Free. Se o console mostra o "
                "aviso 'You are using a Free Tier account', e provavelmente "
                "isto.\n"
                "   2. Politica IAM ainda nao propagou. Confira em "
                "Identity & Security > Policies:\n"
                "      allow any-user to manage generative-ai-family in "
                "tenancy where request.principal.type = "
                "'autonomousdatabase'\n"
                "   3. O modelo pedido nao existe na regiao do perfil "
                "(sa-saopaulo-1).\n"
                "\n"
                "   Para confirmar qual e: abra o Database Actions e rode\n"
                "      SELECT DBMS_CLOUD_AI.GENERATE(prompt => 'ola', "
                "profile_name => 'SYNODOS_AI', action => 'chat') FROM DUAL;\n"
                "   Se ali tambem pendurar, o problema e o servico, nao o "
                "codigo."
            )
        else:
            dica = "leia a mensagem acima."
        print(f"{FALHA} {texto.splitlines()[0]}")
        print(f"\n   COMO RESOLVER: {dica}\n")
        sys.exit(1)

    print(f"{OK} SQL gerado pelo modelo:")
    for linha in sql.splitlines()[:8]:
        print(f"         {linha}")

    # ---------------------------------------------------------------- 7
    secao(7, "Executar esse SQL no banco")

    try:
        cur.execute(sql)
        linhas = cur.fetchall()
        print(f"{OK} {len(linhas)} linhas devolvidas pelo banco")
        if linhas:
            colunas = [d[0].lower() for d in cur.description]
            print(f"         colunas: {', '.join(colunas[:6])}")
            print(f"         1a linha: {linhas[0][:5]}")
    except Exception as exc:                          # noqa: BLE001
        parar(
            f"o SQL gerado nao executou: {str(exc).splitlines()[0]}",
            "o modelo escreveu uma consulta invalida. Costuma melhorar "
            "confirmando que o perfil esta com \"comments\": \"true\" e que "
            "os COMMENT ON do sql/01 rodaram.",
        )

    # ---------------------------------------------------------------- 8
    secao(8, "Caminho completo, como o painel usa")

    from src.db.select_ai import perguntar  # noqa: E402

    r = perguntar(pergunta)
    print(f"{OK} modo   : {r['modo']}")
    print(f"{OK} origem : {r['origem']}")
    print(f"{OK} linhas : {len(r['resultado'])}")
    if r.get("erro_oracle"):
        print(f"  [aviso] caiu para o modo local. Motivo: "
              f"{r['erro_oracle'][:160]}")

    print("\n" + "=" * 72)
    if r["modo"] == "oracle" and r["origem"] == "dados":
        print("TUDO CERTO. O painel vai responder pelo Oracle Select AI.")
    else:
        print("ATENCAO: o painel ainda esta caindo no modo local. "
              "Veja o aviso acima.")
    print("=" * 72 + "\n")

    con.close()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:                                 # noqa: BLE001
        print("\nErro inesperado no diagnostico:\n")
        traceback.print_exc()
        sys.exit(1)

"""
Testa o banco de perguntas do Select AI contra o Oracle, antes de gravar.

Roda cada pergunta, mostra se o modelo gerou SQL valido e se o banco devolveu
linhas. Serve para voce saber quais perguntas usar na demonstracao sem
descobrir na hora da gravacao que uma delas falha.

Uso:
    python scripts/testar_perguntas.py            # o banco inteiro
    python scripts/testar_perguntas.py --rapido   # so as 6 do roteiro
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.select_ai import oracle_disponivel, perguntar  # noqa: E402

# ---------------------------------------------------------------------------
# O banco de perguntas.
#
# Nivel 1 - respondidas por uma view so. Sao as mais seguras: o modelo nao
#           precisa acertar nenhum join.
# Nivel 2 - exigem agregacao ou filtro que a view nao traz pronto. Sao as que
#           impressionam, porque mostram que o modelo escreve SQL de verdade.
# Nivel 3 - cruzam a tabela fato com as dimensoes. Mais arriscadas.
# ---------------------------------------------------------------------------

PERGUNTAS: list[tuple[int, str, bool]] = [
    # (nivel, pergunta, entra_no_roteiro)
    (1, "Qual o total de internacoes e a permanencia media?", True),
    (1, "Quais os cinco estados com mais internacoes a cada 10 mil habitantes?", True),
    (1, "Quais transtornos consomem mais dias de leito?", True),
    (1, "Quais estados estao com maior pressao assistencial?", False),
    (1, "Qual estado tem a menor densidade de leitos de saude mental?", False),
    (1, "Como as internacoes evoluiram mes a mes?", False),
    (1, "Qual a faixa etaria com mais internacoes?", False),
    (1, "Quantos CAPS tem cada estado?", False),
    (1, "Qual a taxa de mortalidade por estado?", False),
    (1, "Qual a idade media dos pacientes em cada diagnostico?", False),

    (2, "Qual o custo medio por internacao em cada regiao?", True),
    (2, "Qual estado tem o maior custo per capita?", True),
    (2, "Quantos estados estao classificados como pressao alta?", False),
    (2, "Qual a permanencia media na regiao Nordeste?", False),
    (2, "Some as internacoes por regiao e ordene da maior para a menor", False),
    (2, "Quais os dez estabelecimentos com maior taxa de ocupacao?", False),

    (3, "Quantas internacoes por esquizofrenia ocorreram em Sao Paulo?", True),
    (3, "Qual o custo total de internacoes por uso de alcool em cada estado?", False),
    (3, "Quantas internacoes tiveram permanencia acima de 30 dias?", False),
    (3, "Qual a distribuicao de internacoes por sexo em cada regiao?", False),
    (3, "Em qual competencia houve mais internacoes por transtorno bipolar?", False),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true",
                    help="testa so as perguntas marcadas para o roteiro")
    args = ap.parse_args()

    if not oracle_disponivel():
        print("\nOracle nao configurado. Preencha ORACLE_PASSWORD e ORACLE_DSN")
        print("no .env. Sem isso o teste roda no modo local e nao vale como")
        print("validacao do Select AI.\n")
        sys.exit(1)

    fila = [p for p in PERGUNTAS if not args.rapido or p[2]]

    print()
    print("=" * 78)
    print(f"TESTANDO {len(fila)} PERGUNTAS NO ORACLE SELECT AI")
    print("=" * 78)

    ok = falhou = conceitual = 0
    problemas: list[str] = []

    for nivel, pergunta, roteiro in fila:
        marca = " *" if roteiro else "  "
        print(f"\n[N{nivel}]{marca} {pergunta}")
        inicio = time.time()

        try:
            r = perguntar(pergunta)
        except Exception as exc:                     # noqa: BLE001
            print(f"      ERRO: {exc}")
            falhou += 1
            problemas.append(pergunta)
            continue

        seg = time.time() - inicio
        origem = r.get("origem", "?")
        df = r.get("resultado")
        linhas = 0 if df is None else len(df)

        if origem == "dados" and linhas:
            print(f"      ok    {linhas} linhas em {seg:.1f}s")
            sql = (r.get("sql") or "").replace("\n", " ")
            print(f"      sql   {sql[:110]}")
            ok += 1
        elif origem == "conhecimento_do_modelo":
            print(f"      AVISO caiu no chat, nao consultou a base ({seg:.1f}s)")
            conceitual += 1
            problemas.append(pergunta)
        else:
            print(f"      FALHA sem linhas ({seg:.1f}s)")
            falhou += 1
            problemas.append(pergunta)

    print()
    print("=" * 78)
    print(f"RESULTADO: {ok} responderam pela base | "
          f"{conceitual} cairam no chat | {falhou} falharam")
    print("=" * 78)

    if problemas:
        print("\nNAO use estas na gravacao:")
        for p in problemas:
            print(f"  - {p}")
    else:
        print("\nTodas responderam pela base. Pode gravar com qualquer uma.")
    print()


if __name__ == "__main__":
    main()

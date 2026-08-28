"""Cria na coleção do Qdrant os índices de payload que a busca filtrada exige.

A coleção do MCR foi criada antes de existir busca por seção, então não tem
índice de payload nenhum — e o Qdrant recusa com 400 (não com busca vazia)
qualquer filtro sobre chave não indexada. `init_collection` já garante os
índices, mas só roda quando a coleção não existe; este script é o caminho para
uma coleção que já está no ar.

Idempotente: rodar de novo não faz nada. Uso:

    python scripts/ensure_indexes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: F401,E402 — aciona load_dotenv() e logging.basicConfig
from src.rag.qdrant import (  # noqa: E402
    CAMPOS_FILTRAVEIS,
    COLLECTION_NAME,
    QDRANT_URL,
    garantir_indices,
    get_client,
)


def main() -> int:
    print(f"Coleção '{COLLECTION_NAME}' em {QDRANT_URL}")
    client = get_client()

    criados = garantir_indices(client)

    schema = client.get_collection(COLLECTION_NAME).payload_schema or {}
    for campo, tipo in CAMPOS_FILTRAVEIS.items():
        marca = "criado agora" if campo in criados else "já existia"
        estado = "OK" if campo in schema else "AUSENTE"
        print(f"  [{estado}] {campo} ({tipo.value}) — {marca}")

    faltando = [c for c in CAMPOS_FILTRAVEIS if c not in schema]
    if faltando:
        print(f"\nFalhou: índices ainda ausentes: {', '.join(faltando)}")
        return 1

    print("\nTodos os índices de payload da busca filtrada estão no lugar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Snapshot de resultados de busca — formato leve para persistir em
`messages.retrieved_chunks` (e em `Resposta.trechos`).

Movido de `frontend/app.py`, que importa esta função em vez de manter a
própria cópia.
"""

from __future__ import annotations

from typing import Any

# Texto truncado para manter a tabela enxuta.
CHUNK_TEXT_STORE_LIMIT = 1500


def snapshot(results: list) -> list[dict[str, Any]]:
    """Converte pontos do Qdrant num formato leve e JSON-serializável para
    persistir em `messages.retrieved_chunks` — texto truncado para manter a
    tabela enxuta.
    """
    itens = []
    for point in results:
        p = point.payload or {}
        itens.append({
            "id": point.id,
            "score": point.score,
            "capitulo_num": p.get("capitulo_num"),
            "capitulo_text": p.get("capitulo_text"),
            "secao_num": p.get("secao_num"),
            "secao_label": p.get("secao_label"),
            "secao_text": p.get("secao_text"),
            "chunk_index": p.get("chunk_index"),
            "total_chunks": p.get("total_chunks"),
            "text": (p.get("text") or "")[:CHUNK_TEXT_STORE_LIMIT],
        })
    return itens

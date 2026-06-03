import logging
import sqlite3
import statistics
from pathlib import Path

import voyageai
from fastembed import SparseTextEmbedding
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector

from .chunker import get_all_chunks
from .config import count_tokens, make_chunk_id
from .database import COLLECTION_NAME

logger = logging.getLogger(__name__)

BATCH_TOKEN_LIMIT = 118_000
DB_PATH           = Path("reports/ragro.db")


def _process_batch(
    client: QdrantClient,
    vo: voyageai.Client,
    bm25: SparseTextEmbedding,
    chunks: list[Document],
    texts: list[str],
    token_counts: list[int],
    batch_sizes: list[int],
    chunk_stats_rows: list[tuple],
) -> None:
    dense_result = vo.embed(texts, model="voyage-4-large", input_type="document")
    dense_vecs   = dense_result.embeddings
    sparse_vecs  = list(bm25.embed(texts))

    points: list[PointStruct] = []
    for chunk, dense, sparse, tokens in zip(chunks, dense_vecs, sparse_vecs, token_counts):
        m        = chunk.metadata
        chunk_id = make_chunk_id(m["capitulo_num"], m["secao_num"], m["chunk_index"], 0)
        points.append(PointStruct(
            id=chunk_id,
            vector={
                "dense":  dense,
                "sparse": SparseVector(
                    indices=sparse.indices.tolist(),
                    values=sparse.values.tolist(),
                ),
            },
            payload={**m, "text": chunk.page_content},
        ))
        chunk_stats_rows.append((
            chunk_id,
            tokens,
            m["capitulo_text"],
            m["secao_text"],
            m["chunk_index"],
            m["total_chunks"],
        ))

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    batch_sizes.append(len(chunks))
    logger.info("  Batch de %d chunks indexado.", len(chunks))


def _save_chunk_stats(rows: list[tuple]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chunk_stats (
            id           INTEGER PRIMARY KEY,
            tokens       INTEGER,
            capitulo     TEXT,
            secao        TEXT,
            chunk_index  INTEGER,
            total_chunks INTEGER
        )
    """)
    cur.executemany("INSERT OR REPLACE INTO chunk_stats VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    logger.info("chunk_stats persistido em '%s' (%d linhas).", DB_PATH, len(rows))


def run_indexing(client: QdrantClient) -> None:
    vo = voyageai.Client()

    # ── PASSAGEM 1: Materializar corpus completo ──────────────────────────────
    logger.info("Passagem 1 — carregando todos os chunks...")
    all_chunks = get_all_chunks()
    all_texts  = [c.page_content for c in all_chunks]
    logger.info("  %d chunks carregados.", len(all_chunks))

    # ── PASSAGEM 2: Inicializar BM25 ──────────────────────────────────────────
    logger.info("Passagem 2 — inicializando BM25...")
    bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")
    logger.info("  BM25 pronto.")

    # ── PASSAGEM 3: Batching dinâmico → embed → upsert ───────────────────────
    logger.info(
        "Passagem 3 — indexando (limite por batch: %d tokens)...",
        BATCH_TOKEN_LIMIT,
    )
    batch_chunks: list[Document] = []
    batch_texts:  list[str]      = []
    batch_tokens: list[int]      = []
    batch_token_sum               = 0
    batch_sizes:      list[int]  = []
    chunk_stats_rows: list[tuple] = []

    for chunk in all_chunks:
        tokens = count_tokens(chunk.page_content)

        if batch_token_sum + tokens > BATCH_TOKEN_LIMIT and batch_texts:
            _process_batch(
                client, vo, bm25,
                batch_chunks, batch_texts, batch_tokens,
                batch_sizes, chunk_stats_rows,
            )
            batch_chunks    = []
            batch_texts     = []
            batch_tokens    = []
            batch_token_sum = 0

        batch_chunks.append(chunk)
        batch_texts.append(chunk.page_content)
        batch_tokens.append(tokens)
        batch_token_sum += tokens

    if batch_texts:
        _process_batch(
            client, vo, bm25,
            batch_chunks, batch_texts, batch_tokens,
            batch_sizes, chunk_stats_rows,
        )

    # ── Estatísticas ──────────────────────────────────────────────────────────
    all_token_counts = [row[1] for row in chunk_stats_rows]
    modes    = statistics.multimode(batch_sizes) if batch_sizes else []
    mode_str = str(modes[0]) if len(modes) == 1 else str(modes)

    logger.info("=" * 55)
    logger.info("Batches enviados      : %d",   len(batch_sizes))
    logger.info("Seções por batch      : %s",   batch_sizes)
    logger.info("Média seções/batch    : %.1f", statistics.mean(batch_sizes) if batch_sizes else 0)
    logger.info("Moda seções/batch     : %s",   mode_str)
    logger.info("Média tokens/seção    : %.0f", statistics.mean(all_token_counts) if all_token_counts else 0)
    logger.info("=" * 55)

    _save_chunk_stats(chunk_stats_rows)

"""
Reindexar uma seção específica sem apagar o banco.

Uso:
    python scripts/reindex_section.py --cap 10 --sec 16
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import voyageai
from fastembed import SparseTextEmbedding
from qdrant_client.models import PointStruct, SparseVector

from src import config  # noqa: F401

logging.getLogger("src.chunker").setLevel(logging.WARNING)

from src.chunker import get_all_chunks
from src.config import count_tokens, make_chunk_id
from src.database import COLLECTION_NAME, get_client

logger = logging.getLogger(__name__)


def reindex_section(cap: int, sec: int) -> None:
    all_chunks = get_all_chunks()
    targets = [
        c for c in all_chunks
        if c.metadata.get("capitulo_num") == cap and c.metadata.get("secao_num") == sec
    ]

    if not targets:
        logger.error("Nenhum chunk encontrado para Cap %d Sec %d.", cap, sec)
        sys.exit(1)

    logger.info("Encontrados %d chunk(s) para Cap %d Sec %d.", len(targets), cap, sec)

    vo    = voyageai.Client()
    bm25  = SparseTextEmbedding(model_name="Qdrant/bm25")
    client = get_client()

    texts        = [c.page_content for c in targets]
    token_counts = [count_tokens(t) for t in texts]
    logger.info("Tokens: %s", token_counts)

    dense_result = vo.embed(texts, model="voyage-4-large", input_type="document")
    dense_vecs   = dense_result.embeddings
    sparse_vecs  = list(bm25.embed(texts))

    points = []
    for chunk, dense, sparse, tokens in zip(targets, dense_vecs, sparse_vecs, token_counts):
        m        = chunk.metadata
        chunk_id = make_chunk_id(
            str(m["capitulo_num"]), str(m["secao_num"]), str(m["chunk_index"]), 0
        )
        points.append(PointStruct(
            id=chunk_id,
            vector={
                "dense": dense,
                "sparse": SparseVector(
                    indices=sparse.indices.tolist(),
                    values=sparse.values.tolist(),
                ),
            },
            payload={**m, "text": chunk.page_content},
        ))

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info("Cap %d Sec %d — %d chunk(s) indexado(s).", cap, sec, len(points))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap", type=int, required=True, help="Número do capítulo")
    parser.add_argument("--sec", type=int, required=True, help="Número da seção")
    args = parser.parse_args()
    reindex_section(args.cap, args.sec)

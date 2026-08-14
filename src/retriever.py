import logging
from enum import Enum

import voyageai
from fastembed.sparse.sparse_embedding_base import SparseTextEmbeddingBase
from qdrant_client import QdrantClient
from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

from .database import COLLECTION_NAME

logger = logging.getLogger(__name__)

TOP_K = 5

# Thresholds calibrados por escala de cada modo:
#   dense  — cosseno normalizado [0, 1]
#   sparse — BM25 com IDF, escala livre e dependente do corpus; sem threshold
#   hybrid — RRF normalizado pelo Qdrant para [0, 1]
SCORE_THRESHOLD: dict[str, float | None] = {
    "dense":  0.4,
    "sparse": None,
    "hybrid": 0.4,
}


class SearchMode(str, Enum):
    HYBRID = "hybrid"
    DENSE  = "dense"
    SPARSE = "sparse"


def search(
    query_text: str,
    client: QdrantClient,
    bm25_model: SparseTextEmbeddingBase,
    mode: SearchMode = SearchMode.HYBRID,
) -> list:
    vo        = voyageai.Client()
    threshold = SCORE_THRESHOLD[mode.value]

    if mode == SearchMode.SPARSE:
        sparse_result = list(bm25_model.query_embed(query_text))
        sparse_vec    = sparse_result[0]
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=SparseVector(
                indices=sparse_vec.indices.tolist(),
                values=sparse_vec.values.tolist(),
            ),
            using="sparse",
            limit=TOP_K,
            with_payload=True,
            **({"score_threshold": threshold} if threshold is not None else {}),
        )
        return results.points

    dense_result = vo.embed([query_text], model="voyage-4-lite", input_type="query")
    dense_vec    = dense_result.embeddings[0]

    if mode == SearchMode.DENSE:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using="dense",
            limit=TOP_K,
            with_payload=True,
            **({"score_threshold": threshold} if threshold is not None else {}),
        )
        return results.points

    # HYBRID — RRF fusion
    sparse_result = list(bm25_model.query_embed(query_text))
    sparse_vec    = sparse_result[0]
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=20),
            Prefetch(
                query=SparseVector(
                    indices=sparse_vec.indices.tolist(),
                    values=sparse_vec.values.tolist(),
                ),
                using="sparse",
                limit=20,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=TOP_K,
        with_payload=True,
        **({"score_threshold": threshold} if threshold is not None else {}),
    )
    return results.points

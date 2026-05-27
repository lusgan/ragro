import logging

import voyageai
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

from .database import COLLECTION_NAME

logger = logging.getLogger(__name__)

TOP_K = 5


def search(
    query_text: str,
    client: QdrantClient,
    bm25_model: SparseTextEmbedding,
) -> list:
    vo = voyageai.Client()

    # Dense query embedding — voyage-4-lite (mesmo espaço vetorial Voyage 4, menor custo)
    dense_result = vo.embed([query_text], model="voyage-4-lite", input_type="query")
    dense_vec    = dense_result.embeddings[0]

    # Sparse BM25 query embedding
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
    )

    return results.points

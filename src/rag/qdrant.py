import logging
import os

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "mcr_knowledge_base"
QDRANT_URL      = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY")
# O httpx assume 5s quando o timeout não é passado, e isso derruba a primeira
# chamada num cluster gerenciado frio (cold start + latência entre regiões).
QDRANT_TIMEOUT  = int(os.getenv("QDRANT_TIMEOUT", "30"))


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=QDRANT_TIMEOUT)


def init_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME in existing:
        logger.info("Coleção '%s' já existe — setup pulado.", COLLECTION_NAME)
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        # modifier=IDF: o fastembed grava só o TF saturado no vetor; o componente
        # IDF do BM25 é calculado pelo Qdrant sobre as estatísticas da coleção.
        # Sem isso o score vira soma de TF e termos genéricos dominam o ranking.
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(),
                modifier=Modifier.IDF,
            )
        },
    )
    logger.info("Coleção '%s' criada com sucesso.", COLLECTION_NAME)

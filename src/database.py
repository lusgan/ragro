import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "mcr_knowledge_base"
QDRANT_PATH     = "./qdrant_db"


def get_client() -> QdrantClient:
    return QdrantClient(path=QDRANT_PATH)


def init_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME in existing:
        logger.info("Coleção '%s' já existe — setup pulado.", COLLECTION_NAME)
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams())},
    )
    logger.info("Coleção '%s' criada com sucesso.", COLLECTION_NAME)

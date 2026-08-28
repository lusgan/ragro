import logging
import os

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    PayloadSchemaType,
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

# Campos de payload que a busca sabe filtrar. Fonte única: o Qdrant não filtra
# por chave sem índice declarado — devolve 400 e derruba a consulta inteira —,
# então quem entra aqui precisa ganhar índice (`garantir_indices`) e ser aceito
# pelo filtro (`retriever._CAMPOS_FILTRO`, derivado deste dict) ao mesmo tempo.
# Manter as duas listas separadas foi exatamente o que quebrou a busca filtrada
# em produção: o filtro conhecia `capitulo_num`, a coleção não.
CAMPOS_FILTRAVEIS: dict[str, PayloadSchemaType] = {
    "capitulo_num": PayloadSchemaType.INTEGER,
    "secao_label":  PayloadSchemaType.KEYWORD,
}

# Tipo Python que o `retriever` exige do valor antes de montar a condição —
# um `secao_label` numérico não casaria com um índice keyword.
TIPO_PYTHON: dict[PayloadSchemaType, type] = {
    PayloadSchemaType.INTEGER: int,
    PayloadSchemaType.KEYWORD: str,
}


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=QDRANT_TIMEOUT)


def garantir_indices(client: QdrantClient) -> list[str]:
    """Cria os índices de payload de `CAMPOS_FILTRAVEIS` que ainda faltam.

    Idempotente e barato (uma leitura + uma escrita por índice ausente), para
    poder rodar em toda inicialização. Existe separado de `init_collection`
    porque coleções criadas antes da busca filtrada já existem sem índice
    nenhum — e nelas o caminho de criação nunca mais roda.

    Devolve os campos efetivamente criados nesta chamada.
    """
    schema = client.get_collection(COLLECTION_NAME).payload_schema or {}
    criados = []
    for campo, tipo in CAMPOS_FILTRAVEIS.items():
        if campo in schema:
            continue
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=campo,
            field_schema=tipo,
            wait=True,
        )
        criados.append(campo)
        logger.info("Índice de payload criado: %s (%s).", campo, tipo.value)
    return criados


def init_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME in existing:
        logger.info("Coleção '%s' já existe — criação pulada.", COLLECTION_NAME)
        garantir_indices(client)
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
    garantir_indices(client)

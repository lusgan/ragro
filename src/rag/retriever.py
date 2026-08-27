import logging
from enum import Enum

import voyageai
from fastembed.sparse.sparse_embedding_base import SparseTextEmbeddingBase
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)

from .qdrant import COLLECTION_NAME

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
    filtro: Filter | None = None,
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
            query_filter=filtro,
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
            query_filter=filtro,
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
            Prefetch(query=dense_vec, using="dense", limit=20, filter=filtro),
            Prefetch(
                query=SparseVector(
                    indices=sparse_vec.indices.tolist(),
                    values=sparse_vec.values.tolist(),
                ),
                using="sparse",
                limit=20,
                filter=filtro,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        query_filter=filtro,
        limit=TOP_K,
        with_payload=True,
        **({"score_threshold": threshold} if threshold is not None else {}),
    )
    return results.points


# --- filtro de metadados -----------------------------------------------------
#
# Chaves suportadas no filtro inferido pelo `rewriter`. Uma chave fora daqui é
# ignorada, não rejeita a entrada inteira — o filtro é um palpite do LLM sobre
# o assunto da pergunta, e travar a busca por causa de uma chave inesperada
# jogaria fora o resto de um palpite que ainda pode ser útil.
_CAMPOS_FILTRO: dict[str, type] = {"capitulo_num": int, "secao_label": str}


def filtro_de_secoes(secoes: list[dict]) -> Filter | None:
    """Converte seções do MCR (ex.: `[{"capitulo_num": 10}, {"capitulo_num": 7,
    "secao_label": "6"}]`) num `Filter` do Qdrant.

    Cada entrada da lista vira um `Filter` aninhado cujas chaves são AND'd
    (`must`); as entradas em si são OR'd (`should`) — a lista do exemplo lê
    como "Cap. 10 OU (Cap. 7 E Seção 6)". Lista vazia devolve `None`, e uma
    entrada sem nenhuma chave suportada é descartada silenciosamente.
    """
    should = []
    for secao in secoes:
        must = [
            FieldCondition(key=chave, match=MatchValue(value=valor))
            for chave, valor in secao.items()
            if chave in _CAMPOS_FILTRO and isinstance(valor, _CAMPOS_FILTRO[chave])
        ]
        if must:
            should.append(Filter(must=must))
    return Filter(should=should) if should else None


def buscar_com_fallback(
    query_text: str,
    client: QdrantClient,
    bm25_model: SparseTextEmbeddingBase,
    *,
    mode: SearchMode = SearchMode.HYBRID,
    secoes: list[dict],
) -> tuple[list, bool]:
    """Busca com o filtro inferido de `secoes` e, se vier vazia, busca de novo
    sem filtro nenhum. Devolve `(resultados, filtro_aplicado)`.

    Todo filtro de metadados que chega aqui é um palpite (`rewriter.reescrever`
    infere o capítulo a partir do assunto da pergunta, sem certeza). Sem este
    fallback, um palpite que erra o capítulo devolve silenciosamente "nenhum
    resultado" para uma pergunta que o corpus respondia normalmente sem filtro
    — pior do que não ter filtrado nada. Por isso: tudo que filtra passa por
    aqui, nunca por `search(..., filtro=...)` direto.
    """
    filtro = filtro_de_secoes(secoes)
    if filtro is None:
        return search(query_text, client, bm25_model, mode), False

    resultados = search(query_text, client, bm25_model, mode, filtro=filtro)
    if resultados:
        return resultados, True

    return search(query_text, client, bm25_model, mode), False

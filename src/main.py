import logging

from fastembed import SparseTextEmbedding

from . import config  # noqa: F401 — aciona load_dotenv() e logging.basicConfig
from .database import COLLECTION_NAME, get_client, init_collection
from .indexer import run_indexing
from .retriever import search

logger = logging.getLogger(__name__)


def _build_bm25() -> SparseTextEmbedding:
    logger.info("Carregando BM25 para retrieval...")
    bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")
    logger.info("  BM25 pronto.")
    return bm25


def main() -> None:
    client      = get_client()
    collections = {c.name for c in client.get_collections().collections}

    if COLLECTION_NAME not in collections:
        logger.info("Coleção não encontrada — executando pipeline completo.")
        init_collection(client)
        run_indexing(client)

    bm25_model = _build_bm25()

    print("\n=== RAG MCR — Busca Híbrida (Ctrl+C para sair) ===\n")
    while True:
        try:
            query = input("Query: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo.")
            break

        if not query:
            continue

        results = search(query, client, bm25_model)
        if not results:
            print("  Nenhum resultado encontrado.\n")
            continue

        for i, point in enumerate(results, 1):
            p = point.payload
            print(f"\n[{i}] Score: {point.score:.4f}")
            print(f"    Cap. {p.get('capitulo_num', '?')} — {p.get('capitulo_text', '?')}")
            print(f"    Sec. {p.get('secao_num', '?')} — {p.get('secao_text', '?')}")
            print(f"    Chunk {p.get('chunk_index', 0) + 1}/{p.get('total_chunks', 1)}")
            print(f"    {p.get('text', '')[:400]}...")
        print()


if __name__ == "__main__":
    main()

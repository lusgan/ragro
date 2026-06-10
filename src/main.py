import logging

from fastembed import SparseTextEmbedding

from . import config  # noqa: F401 — aciona load_dotenv() e logging.basicConfig
from .database import COLLECTION_NAME, get_client, init_collection
from .indexer import run_indexing
from .retriever import SearchMode, search

logger = logging.getLogger(__name__)

_MODE_OPTIONS = {
    "1": SearchMode.HYBRID,
    "2": SearchMode.DENSE,
    "3": SearchMode.SPARSE,
}


def _build_bm25() -> SparseTextEmbedding:
    logger.info("Carregando BM25 para retrieval...")
    bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")
    logger.info("  BM25 pronto.")
    return bm25


def _choose_mode() -> SearchMode:
    print("\nModo de busca:")
    print("  [1] Híbrida — dense + sparse (RRF)  (padrão)")
    print("  [2] Dense   — só vetor semântico")
    print("  [3] Sparse  — só BM25")
    try:
        choice = input("Escolha [1/2/3]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return SearchMode.HYBRID
    return _MODE_OPTIONS.get(choice, SearchMode.HYBRID)


def main() -> None:
    client      = get_client()
    collections = {c.name for c in client.get_collections().collections}

    if COLLECTION_NAME not in collections:
        logger.info("Coleção não encontrada — executando pipeline completo.")
        init_collection(client)
        run_indexing(client)

    bm25_model = _build_bm25()
    mode       = _choose_mode()

    print(f"\n=== RAG MCR — Modo: {mode.value.upper()} (Ctrl+C para sair) ===")
    print("  Digite :modo para alternar o modo de busca.\n")
    while True:
        try:
            query = input("Query: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo.")
            break

        if not query:
            continue

        if query == ":modo":
            mode = _choose_mode()
            print(f"  Modo alterado para: {mode.value.upper()}\n")
            continue

        results = search(query, client, bm25_model, mode=mode)
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

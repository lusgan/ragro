import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from fastembed import SparseTextEmbedding

from src import config  # noqa: F401 — aciona load_dotenv() e logging.basicConfig
from src.database import COLLECTION_NAME, get_client, init_collection
from src.generator import generate_answer
from src.indexer import run_indexing
from src.retriever import SearchMode, search

st.set_page_config(page_title="RAG MCR", page_icon="📖", layout="centered")

MODE_LABELS = {
    SearchMode.HYBRID: "Híbrida — dense + sparse (RRF)",
    SearchMode.DENSE: "Dense — só vetor semântico",
    SearchMode.SPARSE: "Sparse — só BM25",
}


@st.cache_resource(show_spinner="Conectando ao Qdrant...")
def get_qdrant_client():
    return get_client()


@st.cache_resource(show_spinner="Carregando modelo BM25...")
def get_bm25_model():
    return SparseTextEmbedding(model_name="Qdrant/bm25")


def collection_exists(client) -> bool:
    return COLLECTION_NAME in {c.name for c in client.get_collections().collections}


def render_result(i: int, point) -> None:
    p = point.payload
    with st.container(border=True):
        st.markdown(f"**[{i}] Score: {point.score:.4f}**")
        st.markdown(f"Cap. {p.get('capitulo_num', '?')} — {p.get('capitulo_text', '?')}")
        st.markdown(f"Sec. {p.get('secao_num', '?')} — {p.get('secao_text', '?')}")
        st.caption(f"Chunk {p.get('chunk_index', 0) + 1}/{p.get('total_chunks', 1)}")

        text = p.get("text", "")
        preview = text[:400]
        st.write(preview + ("..." if len(text) > len(preview) else ""))
        if len(text) > len(preview):
            with st.expander("Ver trecho completo"):
                st.write(text)


def main() -> None:
    st.title("RAG MCR — Manual de Crédito Rural")
    st.caption("Busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.")

    try:
        client = get_qdrant_client()
    except Exception as e:
        st.error(f"Não foi possível conectar ao Qdrant: {e}")
        st.info("Verifique se o servidor está rodando: `docker compose up -d`")
        st.stop()

    if not collection_exists(client):
        st.warning(
            f"Coleção '{COLLECTION_NAME}' não encontrada no Qdrant. "
            "É necessário indexar os documentos antes de consultar."
        )
        if st.button("Indexar agora"):
            with st.spinner("Indexando documentos (pode levar alguns minutos)..."):
                init_collection(client)
                run_indexing(client)
            st.success("Indexação concluída.")
            st.rerun()
        st.stop()

    bm25_model = get_bm25_model()

    with st.sidebar:
        st.header("Configurações")
        mode = st.radio(
            "Modo de busca",
            options=list(MODE_LABELS.keys()),
            format_func=lambda m: MODE_LABELS[m],
        )

    with st.form("query_form"):
        query = st.text_input("Pergunta", placeholder="Ex.: Quem se encaixa no PRONAF?")
        submitted = st.form_submit_button("Buscar")

    if submitted and query.strip():
        with st.spinner("Buscando..."):
            results = search(query.strip(), client, bm25_model, mode=mode)

        if not results:
            st.info("Nenhum resultado encontrado.")
        else:
            if not (os.environ.get("GOOGLE_CLOUD_PROJECT") and os.environ.get("GCLOUD_SA_BASE64")):
                st.warning(
                    "GOOGLE_CLOUD_PROJECT / GCLOUD_SA_BASE64 não configurados — mostrando "
                    "apenas os trechos recuperados, sem resposta gerada."
                )
            else:
                with st.spinner("Gerando resposta..."):
                    try:
                        answer = generate_answer(query.strip(), results)
                        st.markdown(answer)
                    except Exception as e:
                        st.error(f"Falha ao gerar resposta: {e}")

            with st.expander("Trechos recuperados", expanded=False):
                for i, point in enumerate(results, 1):
                    render_result(i, point)


if __name__ == "__main__":
    main()

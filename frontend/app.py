"""Entrypoint do frontend Streamlit — config da página e orquestração de alto
nível (login → conexão com Qdrant → sidebar → chat).

A lógica em si mora em `frontend/state.py` (session_state escopado por
usuário) e `frontend/views/` (auth, sidebar, chat). Ver
`docs/arquitetura-agentes.md` para o fluxo dos agentes por trás do chat.

`frontend/` mantém o nome e este arquivo continua em `frontend/app.py`: o
caminho está configurado fora do repositório (dashboard do Streamlit Cloud e
`.devcontainer/devcontainer.json`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import config  # noqa: F401 — aciona load_dotenv() e logging.basicConfig
from src.config import build_bm25
from src.rag.qdrant import COLLECTION_NAME, QDRANT_URL, get_client

from frontend.views import chat
from frontend.views.auth import require_login
from frontend.views.sidebar import render_conversation_sidebar

st.set_page_config(page_title="RAG MCR", page_icon="📖", layout="centered")


@st.cache_resource(show_spinner="Conectando ao Qdrant...")
def get_qdrant_client():
    return get_client()


@st.cache_resource(show_spinner="Carregando modelo BM25...")
def get_bm25_model():
    return build_bm25()


def collection_exists(client) -> bool:
    return COLLECTION_NAME in {c.name for c in client.get_collections().collections}


def main() -> None:
    st.title("RAG MCR — Manual de Crédito Rural")
    st.caption("Busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.")

    user = require_login()

    # QdrantClient() não abre conexão no construtor: a falha de rede só aparece
    # na primeira requisição, então a checagem da coleção precisa estar dentro
    # do try — senão o erro sobe como traceback cru em vez desta mensagem.
    try:
        client = get_qdrant_client()
        has_collection = collection_exists(client)
    except Exception as e:
        st.error(f"Não foi possível conectar ao Qdrant ({type(e).__name__}): {e}")
        st.info(
            f"URL configurada: `{QDRANT_URL}`. Local: `docker compose up -d`. "
            "Qdrant Cloud: a URL precisa incluir a porta (`:443`)."
        )
        st.stop()

    # A indexação é um passo offline: depende dos .docx do MCR, que não vão para
    # o repositório. Aqui só consultamos — se a coleção não existe, é erro de
    # configuração (QDRANT_URL apontando pro cluster errado) ou de operação.
    if not has_collection:
        st.error(
            f"Coleção '{COLLECTION_NAME}' não encontrada no Qdrant. "
            "Rode a indexação localmente (`python -m src.main`, que indexa quando "
            "a coleção não existe) apontando para este mesmo cluster."
        )
        st.stop()

    bm25_model = get_bm25_model()

    render_conversation_sidebar(user["id"])
    chat.render(user["id"], client, bm25_model)


if __name__ == "__main__":
    main()

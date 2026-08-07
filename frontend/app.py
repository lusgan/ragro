import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit_authenticator as stauth
from fastembed import SparseTextEmbedding

from src import config  # noqa: F401 — aciona load_dotenv() e logging.basicConfig
from src.auth import AuthError, create_user, list_users_for_authenticator, touch_last_login
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


def build_authenticator() -> stauth.Authenticate:
    credentials = list_users_for_authenticator()
    return stauth.Authenticate(
        credentials,
        cookie_name="ragro_auth",
        cookie_key=os.environ["AUTH_COOKIE_KEY"],
        cookie_expiry_days=7,
    )


def render_signup_form() -> None:
    with st.form("signup_form", clear_on_submit=True):
        email = st.text_input("Email")
        password = st.text_input("Senha", type="password")
        invite_code = st.text_input("Código de convite")
        submitted = st.form_submit_button("Criar conta")

    if submitted:
        try:
            create_user(email, password, invite_code)
        except AuthError as e:
            st.error(str(e))
        else:
            st.success("Conta criada. Use a aba \"Entrar\" para fazer login.")


def require_login() -> str:
    """Renderiza login/cadastro. Interrompe a execução do script se não autenticado."""
    try:
        authenticator = build_authenticator()
    except Exception as e:
        st.error(f"Não foi possível conectar ao banco de autenticação: {e}")
        st.stop()

    if st.session_state.get("authentication_status"):
        with st.sidebar:
            st.caption(f"Conectado como {st.session_state.get('username')}")
            authenticator.logout("Sair")
        if not st.session_state.get("_last_login_touched"):
            touch_last_login(st.session_state["username"])
            st.session_state["_last_login_touched"] = True
        return st.session_state["username"]

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta"])
    with tab_login:
        authenticator.login(location="main")
        if st.session_state.get("authentication_status") is False:
            st.error("Email ou senha incorretos.")
    with tab_signup:
        render_signup_form()

    st.stop()
    raise RuntimeError("unreachable")  # st.stop() interrompe a execução acima


def main() -> None:
    st.title("RAG MCR — Manual de Crédito Rural")
    st.caption("Busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.")

    require_login()

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

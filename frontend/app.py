import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit_authenticator as stauth

from src import (  # noqa: F401 — config aciona load_dotenv() e logging.basicConfig
    chat_history,
    config,
)
from src.auth import (
    AuthError,
    create_user,
    get_user_by_email,
    list_users_for_authenticator,
    touch_last_login,
)
from src.config import build_bm25
from src.database import COLLECTION_NAME, get_client
from src.generator import condense_query, generate_answer
from src.retriever import SearchMode, search

st.set_page_config(page_title="RAG MCR", page_icon="📖", layout="centered")

MODE_LABELS = {
    SearchMode.HYBRID: "Híbrida — dense + sparse (RRF)",
    SearchMode.DENSE: "Dense — só vetor semântico",
    SearchMode.SPARSE: "Sparse — só BM25",
}

CHUNK_TEXT_STORE_LIMIT = 1500
GENERATION_AVAILABLE = bool(os.environ.get("GOOGLE_CLOUD_PROJECT") and os.environ.get("GCLOUD_SA_BASE64"))


@st.cache_resource(show_spinner="Conectando ao Qdrant...")
def get_qdrant_client():
    return get_client()


@st.cache_resource(show_spinner="Carregando modelo BM25...")
def get_bm25_model():
    return build_bm25()


def collection_exists(client) -> bool:
    return COLLECTION_NAME in {c.name for c in client.get_collections().collections}


def snapshot_from_results(results: list) -> list[dict[str, Any]]:
    """Converte pontos do Qdrant num formato leve e JSON-serializável para
    persistir em `messages.retrieved_chunks` — texto truncado para manter a
    tabela enxuta.
    """
    snapshot = []
    for point in results:
        p = point.payload or {}
        snapshot.append({
            "id": point.id,
            "score": point.score,
            "capitulo_num": p.get("capitulo_num"),
            "capitulo_text": p.get("capitulo_text"),
            "secao_num": p.get("secao_num"),
            "secao_label": p.get("secao_label"),
            "secao_text": p.get("secao_text"),
            "chunk_index": p.get("chunk_index"),
            "total_chunks": p.get("total_chunks"),
            "text": (p.get("text") or "")[:CHUNK_TEXT_STORE_LIMIT],
        })
    return snapshot


def render_chunk(i: int, chunk: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(f"**[{i}] Score: {chunk.get('score', 0):.4f}**")
        st.markdown(f"Cap. {chunk.get('capitulo_num', '?')} — {chunk.get('capitulo_text', '?')}")
        secao = chunk.get('secao_label') or chunk.get('secao_num', '?')
        st.markdown(f"Sec. {secao} — {chunk.get('secao_text', '?')}")
        st.caption(f"Chunk {(chunk.get('chunk_index') or 0) + 1}/{chunk.get('total_chunks', 1)}")

        text = chunk.get("text", "")
        preview = text[:400]
        st.write(preview + ("..." if len(text) > len(preview) else ""))
        if len(text) > len(preview):
            with st.expander("Ver trecho completo"):
                st.write(text)


def render_message(m: dict[str, Any]) -> None:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        chunks = m.get("retrieved_chunks")
        if m["role"] == "assistant" and chunks:
            with st.expander("Trechos recuperados", expanded=False):
                for i, chunk in enumerate(chunks, 1):
                    render_chunk(i, chunk)


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


def require_login() -> dict[str, Any]:
    """Renderiza login/cadastro. Interrompe a execução do script se não
    autenticado. Retorna {"id": ..., "email": ...} do usuário logado.
    """
    try:
        authenticator = build_authenticator()
    except Exception as e:
        st.error(f"Não foi possível conectar ao banco de autenticação: {e}")
        st.stop()

    if st.session_state.get("authentication_status"):
        email = st.session_state["username"]
        with st.sidebar:
            st.caption(f"Conectado como {email}")
            authenticator.logout("Sair")
        if not st.session_state.get("_last_login_touched"):
            touch_last_login(email)
            st.session_state["_last_login_touched"] = True
        if "_user_id" not in st.session_state:
            user = get_user_by_email(email)
            st.session_state["_user_id"] = user["id"]
        return {"id": st.session_state["_user_id"], "email": email}

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta"])
    with tab_login:
        authenticator.login(location="main")
        if st.session_state.get("authentication_status") is False:
            st.error("Email ou senha incorretos.")
    with tab_signup:
        render_signup_form()

    st.stop()
    raise RuntimeError("unreachable")  # st.stop() interrompe a execução acima


def render_conversation_sidebar(user_id: int) -> None:
    with st.sidebar:
        st.divider()
        if st.button("+ Nova conversa", use_container_width=True):
            st.session_state["active_conversation_id"] = None
            st.rerun()

        st.caption("Conversas")
        conversations = chat_history.list_conversations(user_id)
        if not conversations:
            st.caption("Nenhuma conversa ainda.")

        active_id = st.session_state.get("active_conversation_id")
        renaming_id = st.session_state.get("renaming_conversation_id")
        for conv in conversations:
            is_active = conv["id"] == active_id

            if renaming_id == conv["id"]:
                with st.form(f"rename_form_{conv['id']}", clear_on_submit=False, border=False):
                    new_title = st.text_input(
                        "Novo título", value=conv["title"] or "", label_visibility="collapsed"
                    )
                    col_save, col_cancel = st.columns(2)
                    save = col_save.form_submit_button("Salvar", use_container_width=True)
                    cancel = col_cancel.form_submit_button("Cancelar", use_container_width=True)
                if save and new_title.strip():
                    chat_history.rename_conversation(conv["id"], user_id, new_title.strip())
                    st.session_state["renaming_conversation_id"] = None
                    st.rerun()
                if cancel:
                    st.session_state["renaming_conversation_id"] = None
                    st.rerun()
                continue

            col_select, col_rename, col_delete = st.columns([4, 1, 1])
            with col_select:
                if st.button(
                    conv["title"] or "Nova conversa",
                    key=f"conv_select_{conv['id']}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state["active_conversation_id"] = conv["id"]
                    st.rerun()
            with col_rename:
                if st.button("✏️", key=f"conv_rename_{conv['id']}"):
                    st.session_state["renaming_conversation_id"] = conv["id"]
                    st.rerun()
            with col_delete:
                if st.button("🗑", key=f"conv_delete_{conv['id']}"):
                    chat_history.delete_conversation(conv["id"], user_id)
                    if is_active:
                        st.session_state["active_conversation_id"] = None
                    st.rerun()

        st.divider()
        st.header("Configurações")
        st.session_state["search_mode"] = st.radio(
            "Modo de busca",
            options=list(MODE_LABELS.keys()),
            format_func=lambda m: MODE_LABELS[m],
        )


def handle_new_message(prompt: str, user_id: int, client, bm25_model, history_msgs: list[dict]) -> None:
    conversation_id = st.session_state.get("active_conversation_id")
    if conversation_id is None:
        conversation_id = chat_history.create_conversation(user_id)
        st.session_state["active_conversation_id"] = conversation_id

    mode = st.session_state.get("search_mode", SearchMode.HYBRID)
    llm_history = [{"role": m["role"], "content": m["content"]} for m in history_msgs]

    chat_history.add_message(conversation_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Buscando..."):
            condensed_query = condense_query(llm_history, prompt)
            results = search(condensed_query, client, bm25_model, mode=mode)

        if not results:
            st.info("Nenhum resultado encontrado.")
            chat_history.add_message(
                conversation_id, "assistant", "Nenhum resultado encontrado.", search_mode=mode.value
            )
            return

        chunks = snapshot_from_results(results)

        if GENERATION_AVAILABLE:
            with st.spinner("Gerando resposta..."):
                try:
                    answer = generate_answer(condensed_query, results, history=llm_history)
                except Exception as e:
                    answer = f"Falha ao gerar resposta: {e}"
            st.markdown(answer)
        else:
            answer = (
                "GOOGLE_CLOUD_PROJECT / GCLOUD_SA_BASE64 não configurados — mostrando "
                "apenas os trechos recuperados, sem resposta gerada."
            )
            st.warning(answer)

        with st.expander("Trechos recuperados", expanded=False):
            for i, chunk in enumerate(chunks, 1):
                render_chunk(i, chunk)

        chat_history.add_message(
            conversation_id, "assistant", answer, search_mode=mode.value, retrieved_chunks=chunks
        )


def main() -> None:
    st.title("RAG MCR — Manual de Crédito Rural")
    st.caption("Busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.")

    user = require_login()

    try:
        client = get_qdrant_client()
    except Exception as e:
        st.error(f"Não foi possível conectar ao Qdrant: {e}")
        st.info("Verifique se o servidor está rodando: `docker compose up -d`")
        st.stop()

    # A indexação é um passo offline: depende dos .docx do MCR, que não vão para
    # o repositório. Aqui só consultamos — se a coleção não existe, é erro de
    # configuração (QDRANT_URL apontando pro cluster errado) ou de operação.
    if not collection_exists(client):
        st.error(
            f"Coleção '{COLLECTION_NAME}' não encontrada no Qdrant. "
            "Rode a indexação localmente (`python -m src.main`, que indexa quando "
            "a coleção não existe) apontando para este mesmo cluster."
        )
        st.stop()

    bm25_model = get_bm25_model()

    render_conversation_sidebar(user["id"])

    active_conversation_id = st.session_state.get("active_conversation_id")
    history_msgs = (
        chat_history.get_messages(active_conversation_id, user["id"]) if active_conversation_id else []
    )
    for m in history_msgs:
        render_message(m)

    prompt = st.chat_input("Pergunta — Ex.: Quem se encaixa no PRONAF?")
    if prompt and prompt.strip():
        handle_new_message(prompt.strip(), user["id"], client, bm25_model, history_msgs)
        st.rerun()


if __name__ == "__main__":
    main()

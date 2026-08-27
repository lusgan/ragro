"""Sidebar: lista de conversas do usuário e configurações de busca."""

from __future__ import annotations

import streamlit as st

from src.rag.retriever import SearchMode
from src.storage import chat_history

MODE_LABELS = {
    SearchMode.HYBRID: "Híbrida — dense + sparse (RRF)",
    SearchMode.DENSE: "Dense — só vetor semântico",
    SearchMode.SPARSE: "Sparse — só BM25",
}


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

"""Renderização da conversa e o turno de chat: histórico e o novo turno."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.llm import client as llm_client
from src.rag.answer import condense_query, generate_answer
from src.rag.retriever import SearchMode, search
from src.rag.snapshot import snapshot
from src.storage import chat_history


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


def handle_new_message(prompt: str, user_id: int, client, bm25_model, history_msgs: list[dict]) -> None:
    conversation_id = st.session_state.get("active_conversation_id")
    if conversation_id is None:
        conversation_id = chat_history.create_conversation(user_id)
        st.session_state["active_conversation_id"] = conversation_id

    mode = st.session_state.get("search_mode", SearchMode.HYBRID)
    llm_history = [{"role": m["role"], "content": m["content"]} for m in history_msgs]

    chat_history.add_message(conversation_id, user_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Buscando..."):
            condensed_query = condense_query(llm_history, prompt)
            results = search(condensed_query, client, bm25_model, mode=mode)

        if not results:
            st.info("Nenhum resultado encontrado.")
            chat_history.add_message(
                conversation_id,
                user_id,
                "assistant",
                "Nenhum resultado encontrado.",
                search_mode=mode.value,
            )
            return

        chunks = snapshot(results)

        if llm_client.disponivel():
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
            conversation_id, user_id, "assistant", answer, search_mode=mode.value, retrieved_chunks=chunks
        )


def render(user_id: int, client, bm25_model) -> None:
    active_conversation_id = st.session_state.get("active_conversation_id")
    history_msgs = (
        chat_history.get_messages(active_conversation_id, user_id) if active_conversation_id else []
    )
    for m in history_msgs:
        render_message(m)

    prompt = st.chat_input("Pergunta — Ex.: Quem se encaixa no PRONAF?")
    if prompt and prompt.strip():
        handle_new_message(prompt.strip(), user_id, client, bm25_model, history_msgs)
        st.rerun()

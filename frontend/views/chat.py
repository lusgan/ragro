"""Renderização da conversa e o turno de chat: histórico, chips de opção do
Agente Conselheiro e o novo turno propriamente dito.

O turno roteia entre os dois agentes (`docs/arquitetura-agentes.md`) em vez
do fluxo antigo (condensar → buscar → gerar) — ver `handle_new_message`.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.agents import advisor, orchestrator, qa
from src.llm import client as llm_client
from src.programs.base import Pergunta
from src.rag.retriever import SearchMode, search
from src.rag.snapshot import snapshot
from src.storage import advisor_state, chat_history

from frontend.markdown import escapar

AGENT_LABELS = {"conselheiro": "Conselheiro", "qa": "Q&A"}


def render_chunk(i: int, chunk: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(f"**[{i}] Score: {chunk.get('score', 0):.4f}**")
        st.markdown(f"Cap. {chunk.get('capitulo_num', '?')} — {chunk.get('capitulo_text', '?')}")
        secao = chunk.get('secao_label') or chunk.get('secao_num', '?')
        st.markdown(f"Sec. {secao} — {chunk.get('secao_text', '?')}")
        st.caption(f"Chunk {(chunk.get('chunk_index') or 0) + 1}/{chunk.get('total_chunks', 1)}")

        text = chunk.get("text", "")
        preview = text[:400]
        st.markdown(escapar(preview + ("..." if len(text) > len(preview) else "")))
        if len(text) > len(preview):
            with st.expander("Ver trecho completo"):
                st.markdown(escapar(text))


def render_message(m: dict[str, Any]) -> None:
    """Renderiza uma mensagem do histórico. `agent` é `NULL` em mensagens
    anteriores à introdução dos agentes — sem badge nesse caso, para não
    inventar uma atribuição que a mensagem não guarda."""
    with st.chat_message(m["role"]):
        agent = m.get("agent")
        if agent:
            st.caption(AGENT_LABELS.get(agent, agent))
        st.markdown(escapar(m["content"]))
        chunks = m.get("retrieved_chunks")
        if m["role"] == "assistant" and chunks:
            with st.expander("Trechos recuperados", expanded=False):
                for i, chunk in enumerate(chunks, 1):
                    render_chunk(i, chunk)


def _render_option_chips(pergunta: Pergunta) -> str | None:
    """Chips com as opções da pergunta pendente do Agente Conselheiro, como
    atalho para digitar a resposta. A chave inclui `pergunta.id` para que o
    widget não carregue seleção de uma pergunta anterior quando o slot
    pendente muda de um turno para outro.
    """
    labels = [o.t for o in pergunta.opcoes]
    selecao = st.pills(
        "Ou escolha uma opção:",
        options=labels,
        selection_mode="multi" if pergunta.multipla else "single",
        format_func=escapar,
        key=f"advisor_chips_{pergunta.id}",
    )
    if not st.button("Responder", key=f"advisor_chips_responder_{pergunta.id}") or not selecao:
        return None
    return ", ".join(selecao) if isinstance(selecao, list) else selecao


def _responder_modo_degradado(
    prompt: str,
    conversation_id: int,
    user_id: int,
    client,
    bm25_model,
    mode: SearchMode,
) -> None:
    """Sem credenciais do Vertex, nenhum agente roda — orquestrador, Q&A e
    Conselheiro chamam o LLM em todo turno. Mantém o comportamento anterior à
    introdução dos agentes: busca direta (sem reescrita, que também é LLM), e
    mostra os trechos recuperados sem gerar resposta.
    """
    with st.spinner("Buscando..."):
        results = search(prompt, client, bm25_model, mode=mode)

    if not results:
        st.info("Nenhum resultado encontrado.")
        chat_history.add_message(
            conversation_id, user_id, "assistant", "Nenhum resultado encontrado.", search_mode=mode.value
        )
        return

    chunks = snapshot(results)
    aviso = (
        "GOOGLE_CLOUD_PROJECT / GCLOUD_SA_BASE64 não configurados — mostrando "
        "apenas os trechos recuperados, sem resposta gerada."
    )
    st.warning(aviso)
    with st.expander("Trechos recuperados", expanded=False):
        for i, chunk in enumerate(chunks, 1):
            render_chunk(i, chunk)

    chat_history.add_message(
        conversation_id, user_id, "assistant", aviso, search_mode=mode.value, retrieved_chunks=chunks
    )


def handle_new_message(prompt: str, user_id: int, client, bm25_model, history_msgs: list[dict]) -> None:
    conversation_id = st.session_state.get("active_conversation_id")
    if conversation_id is None:
        # O estado do conselheiro é escopado na conversa — ela precisa existir
        # antes de qualquer outra coisa neste turno.
        conversation_id = chat_history.create_conversation(user_id)
        st.session_state["active_conversation_id"] = conversation_id

    mode = st.session_state.get("search_mode", SearchMode.HYBRID)
    llm_history = [{"role": m["role"], "content": m["content"]} for m in history_msgs]

    chat_history.add_message(conversation_id, user_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(escapar(prompt))

    with st.chat_message("assistant"):
        if not llm_client.disponivel():
            _responder_modo_degradado(prompt, conversation_id, user_id, client, bm25_model, mode)
            return

        estado = advisor_state.carregar(conversation_id, user_id)
        rota = orchestrator.rotear(prompt, llm_history, estado)
        if rota.suspender_sessao and estado is not None:
            # Grava antes de responder: o usuário já saiu do questionário,
            # mesmo que o Q&A falhe neste turno.
            estado = advisor.suspender(estado)
            advisor_state.salvar(conversation_id, user_id, estado)

        with st.spinner("Pensando..."):
            try:
                if rota.agente == "conselheiro":
                    resposta = advisor.responder(prompt, llm_history, estado, client, bm25_model, mode=mode)
                else:
                    resposta = qa.responder(prompt, llm_history, client, bm25_model, mode=mode)
            except Exception as e:
                texto = f"Falha ao gerar resposta: {e}"
                st.markdown(escapar(texto))
                chat_history.add_message(
                    conversation_id, user_id, "assistant", texto, search_mode=mode.value
                )
                return

        st.caption(AGENT_LABELS.get(resposta.agente, resposta.agente))
        st.markdown(escapar(resposta.texto))
        if resposta.trechos:
            with st.expander("Trechos recuperados", expanded=False):
                for i, chunk in enumerate(resposta.trechos, 1):
                    render_chunk(i, chunk)

        chat_history.add_message(
            conversation_id,
            user_id,
            "assistant",
            resposta.texto,
            search_mode=mode.value,
            retrieved_chunks=resposta.trechos,
            agent=resposta.agente,
        )
        # O Q&A sempre devolve `estado=None` — nunca pode apagar uma sessão do
        # conselheiro em andamento. Quem suspende a sessão numa mudança de
        # assunto é o orquestrador/conselheiro, não a persistência.
        if resposta.estado is not None:
            advisor_state.salvar(conversation_id, user_id, resposta.estado)


def render(user_id: int, client, bm25_model) -> None:
    """Renderiza a conversa ativa (histórico, chips pendentes, `chat_input`)
    e despacha um novo turno quando houver.
    """
    active_conversation_id = st.session_state.get("active_conversation_id")
    history_msgs = (
        chat_history.get_messages(active_conversation_id, user_id) if active_conversation_id else []
    )
    for m in history_msgs:
        render_message(m)

    # `pergunta_pendente` recomputa a pergunta do engine a partir do estado
    # persistido — não guardamos cópia em session_state, o Postgres já é a
    # fonte da verdade (ver `advisor.pergunta_pendente`).
    estado = advisor_state.carregar(active_conversation_id, user_id) if active_conversation_id else None
    pergunta = advisor.pergunta_pendente(estado)

    prompt = _render_option_chips(pergunta) if pergunta is not None else None

    # Os chips são um atalho, nunca o único caminho: digitar continua
    # funcionando e converge para o mesmo `handle_new_message` abaixo.
    typed = st.chat_input("Pergunta — Ex.: Quem se encaixa no PRONAF?")
    if typed and typed.strip():
        prompt = typed.strip()

    if prompt:
        handle_new_message(prompt, user_id, client, bm25_model, history_msgs)
        st.rerun()

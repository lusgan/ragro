"""Estado de sessão escopado por usuário (`st.session_state`).

Isolado num módulo próprio porque é o ponto exato do bug original: o logout
do `streamlit-authenticator` limpa só as chaves dele (`authentication_status`,
`username`, `name`) e o cookie — o resto é responsabilidade da aplicação. Sem
isto, `_user_id` sobrevive a uma troca de conta na mesma aba do browser, e a
conta seguinte reaproveita o id da anterior: as queries de `chat_history`
filtram por `user_id` corretamente, mas recebem o id errado.
"""

from __future__ import annotations

import streamlit as st

# Chaves do session_state que pertencem ao usuário logado e portanto não podem
# sobreviver a uma troca de conta na mesma aba do browser. O logout do
# streamlit-authenticator só limpa as chaves dele (`authentication_status`,
# `username`, `name`) e o cookie — o resto é responsabilidade da aplicação.
USER_SCOPED_STATE_KEYS = (
    "_user_id",
    "_user_email",
    "_last_login_touched",
    "active_conversation_id",
    "renaming_conversation_id",
)


def reset_user_scoped_state() -> None:
    for key in USER_SCOPED_STATE_KEYS:
        st.session_state.pop(key, None)


def sync_user_scoped_state(email: str | None) -> None:
    """Descarta o estado do usuário anterior quando a identidade da sessão muda.

    Cobre os dois lados da troca de conta na mesma aba: o logout (`email=None`)
    e o login seguinte com outro email. Sem isso, `_user_id` sobrevive ao
    logout e a conta seguinte lê o histórico da anterior — as queries filtram
    por `user_id` corretamente, mas recebem o id errado.
    """
    if st.session_state.get("_user_email") != email:
        reset_user_scoped_state()

"""Login, cadastro e o isolamento de sessão entre contas na mesma aba.

`require_login` é o único ponto do frontend que decide se o script continua
ou para (`st.stop()`) — tudo o que vem depois dele (sidebar, chat) já pode
assumir um usuário autenticado.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit_authenticator as stauth

from frontend.state import sync_user_scoped_state
from src.storage.auth import (
    AuthError,
    create_user,
    get_user_by_email,
    list_users_for_authenticator,
    touch_last_login,
)


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

        # Antes de resolver o id: se a sessão foi herdada de outra conta, o
        # `_user_id` antigo ainda está aqui e seria reaproveitado.
        sync_user_scoped_state(email)

        with st.sidebar:
            st.caption(f"Conectado como {email}")
            authenticator.logout("Sair")
        if not st.session_state.get("_last_login_touched"):
            touch_last_login(email)
            st.session_state["_last_login_touched"] = True
        if "_user_id" not in st.session_state:
            user = get_user_by_email(email)
            st.session_state["_user_id"] = user["id"]
            st.session_state["_user_email"] = email
        return {"id": st.session_state["_user_id"], "email": email}

    # Não autenticado: se havia sessão, é logout — limpa antes que a próxima
    # conta logue nesta mesma aba.
    sync_user_scoped_state(None)

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta"])
    with tab_login:
        authenticator.login(location="main")
        if st.session_state.get("authentication_status") is False:
            st.error("Email ou senha incorretos.")
    with tab_signup:
        render_signup_form()

    st.stop()
    raise RuntimeError("unreachable")  # st.stop() interrompe a execução acima

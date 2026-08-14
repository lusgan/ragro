"""
Isolamento do `session_state` entre contas na mesma aba do browser.

Esta é a causa raiz do bug original: o `authenticator.logout()` do
streamlit-authenticator limpa só as chaves dele (`authentication_status`,
`username`, `name`) e o cookie. As chaves da aplicação — `_user_id` acima de
tudo — sobreviviam, e a conta seguinte reaproveitava o id da anterior. As
queries de `chat_history` filtravam por `user_id` corretamente; recebiam era o
id errado, então o histórico do usuário anterior aparecia para o novo.

Os testes de `test_chat_history_isolation.py` não pegam isso: lá a camada de
dados sempre esteve certa. O furo é aqui.
"""

import pytest

# `frontend/` não é pacote instalado; o pythonpath do pytest.ini põe a raiz do
# repo no sys.path, o que basta para o namespace package.
app = pytest.importorskip("frontend.app")


@pytest.fixture
def session_state(monkeypatch) -> dict:
    """Substitui o `st.session_state` por um dict.

    Fora do runtime do Streamlit não há sessão de verdade, e o proxy real
    depende de um ScriptRunContext. Um dict expõe o mesmo `.get()`/`.pop()` que
    as funções sob teste usam.
    """
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    return state


def _estado_logado_da_alice() -> dict:
    """Sessão como fica depois da alice usar o app: id resolvido, conversa
    aberta e um rename em andamento na sidebar.
    """
    return {
        "_user_id": 1,
        "_user_email": "alice@example.com",
        "_last_login_touched": True,
        "active_conversation_id": 42,
        "renaming_conversation_id": 42,
        "search_mode": "hybrid",
    }


def test_troca_de_conta_descarta_o_estado_da_anterior(session_state):
    """O cenário relatado: usuário novo loga na aba onde outro já esteve."""
    session_state.update(_estado_logado_da_alice())

    app.sync_user_scoped_state("bruno@example.com")

    assert "_user_id" not in session_state, "o id da alice seria reusado para o bruno"
    assert "active_conversation_id" not in session_state, "a conversa da alice seguiria aberta"
    assert "renaming_conversation_id" not in session_state
    assert "_last_login_touched" not in session_state


def test_logout_limpa_o_estado_antes_do_proximo_login(session_state):
    """Limpar no logout é o que impede o vazamento quando a próxima conta chega
    por um caminho que não passe pela comparação de email.
    """
    session_state.update(_estado_logado_da_alice())

    app.sync_user_scoped_state(None)

    assert not any(k in session_state for k in app.USER_SCOPED_STATE_KEYS)


def test_mesma_conta_mantem_a_conversa_aberta(session_state):
    """Rerun comum (cada clique no Streamlit): nada pode ser descartado, senão
    a conversa aberta fecharia sozinha a cada interação.
    """
    session_state.update(_estado_logado_da_alice())

    app.sync_user_scoped_state("alice@example.com")

    assert session_state["_user_id"] == 1
    assert session_state["active_conversation_id"] == 42


def test_sessao_limpa_no_primeiro_login_e_no_op(session_state):
    app.sync_user_scoped_state(None)
    assert session_state == {}

    app.sync_user_scoped_state("alice@example.com")
    assert session_state == {}


def test_preserva_estado_que_nao_e_do_usuario(session_state):
    """`search_mode` é preferência de UI, não dado de conta — descartá-la só
    faria o seletor da sidebar pular de volta para o default sem motivo.
    """
    session_state.update(_estado_logado_da_alice())

    app.sync_user_scoped_state("bruno@example.com")

    assert session_state["search_mode"] == "hybrid"


def test_toda_chave_de_usuario_esta_declarada_para_limpeza():
    """Guarda contra a reincidência mais provável: alguém adiciona uma chave de
    escopo de usuário no `session_state` e esquece de registrá-la aqui — foi
    literalmente assim que o bug surgiu.
    """
    esperadas = {
        "_user_id",
        "_user_email",
        "_last_login_touched",
        "active_conversation_id",
        "renaming_conversation_id",
    }
    assert set(app.USER_SCOPED_STATE_KEYS) == esperadas

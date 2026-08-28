"""
Isolamento entre usuários em `src/storage/advisor_state.py`.

Mesmo contrato de `tests/test_chat_history_isolation.py`: nenhuma função aqui
pode operar fora do `user_id` recebido, mesmo com o `conversation_id` certo em
mãos — a sessão do Agente Conselheiro é tão sensível quanto o histórico de
mensagens.
"""

import pytest

from src.storage import advisor_state, chat_history

# Todo teste deste módulo fala com o Postgres de teste e começa com as tabelas
# vazias (ver `clean_db` no conftest).
pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def conversa_da_alice(alice: int) -> int:
    return chat_history.create_conversation(alice)


ESTADO_EXEMPLO = {
    "fase": "coleta",
    "programa": "pronaf",
    "triagem": {"renda": "ate500k", "renda_da_atividade": "sim"},
    "respostas": {"tipo": "individual", "renda": "ate60k"},
    "slot_pendente": "finalidade",
    "esclarecimentos": {"finalidade": 1},
    "atualizado_em": "2026-08-27T19:00:00Z",
}


def test_carregar_sem_sessao_devolve_none(conversa_da_alice, alice):
    assert advisor_state.carregar(conversa_da_alice, alice) is None


def test_round_trip_de_salvar_e_carregar(conversa_da_alice, alice):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    assert advisor_state.carregar(conversa_da_alice, alice) == ESTADO_EXEMPLO


def test_salvar_substitui_estado_anterior(conversa_da_alice, alice):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    novo_estado = {**ESTADO_EXEMPLO, "fase": "concluido", "slot_pendente": None}
    advisor_state.salvar(conversa_da_alice, alice, novo_estado)

    assert advisor_state.carregar(conversa_da_alice, alice) == novo_estado


def test_bruno_nao_le_estado_da_alice(conversa_da_alice, alice, bruno):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    assert advisor_state.carregar(conversa_da_alice, bruno) is None


def test_bruno_nao_grava_na_conversa_da_alice(conversa_da_alice, alice, bruno):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    with pytest.raises(PermissionError):
        advisor_state.salvar(conversa_da_alice, bruno, {"fase": "triagem"})

    # A tentativa recusada não deixou rastro no estado da alice.
    assert advisor_state.carregar(conversa_da_alice, alice) == ESTADO_EXEMPLO


def test_salvar_em_conversa_inexistente_e_recusado(alice):
    with pytest.raises(PermissionError):
        advisor_state.salvar(999_999, alice, ESTADO_EXEMPLO)


def test_limpar_remove_o_estado(conversa_da_alice, alice):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    advisor_state.limpar(conversa_da_alice, alice)

    assert advisor_state.carregar(conversa_da_alice, alice) is None


def test_limpar_de_outro_usuario_nao_apaga(conversa_da_alice, alice, bruno):
    advisor_state.salvar(conversa_da_alice, alice, ESTADO_EXEMPLO)

    advisor_state.limpar(conversa_da_alice, bruno)

    assert advisor_state.carregar(conversa_da_alice, alice) == ESTADO_EXEMPLO

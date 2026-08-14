"""
Isolamento entre usuários em `src/chat_history.py`.

Regressão do bug em que um usuário recém-criado via o histórico de outro. A
causa estava no `session_state` do frontend, mas o efeito só foi possível
porque `add_message` aceitava qualquer `conversation_id` sem checar dono — os
testes aqui fixam o contrato da camada de dados: **nenhuma** função de conversa
opera fora do `user_id` recebido, mesmo com o `conversation_id` certo em mãos.
"""

import pytest

from src import chat_history

# Todo teste deste módulo fala com o Postgres de teste e começa com as tabelas
# vazias (ver `clean_db` no conftest).
pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def conversa_da_alice(alice: int) -> int:
    """Conversa da alice com duas mensagens, para o bruno tentar alcançar."""
    conversation_id = chat_history.create_conversation(alice)
    chat_history.add_message(conversation_id, alice, "user", "Quem se encaixa no PRONAF?")
    chat_history.add_message(
        conversation_id, alice, "assistant", "Resposta para a alice.", search_mode="hybrid"
    )
    return conversation_id


# --- Leitura -----------------------------------------------------------------


def test_list_conversations_nao_vaza_conversa_de_outro(alice, bruno, conversa_da_alice):
    """O sintoma relatado: usuário novo abre o app e vê a sidebar do outro."""
    assert chat_history.list_conversations(bruno) == []

    da_alice = chat_history.list_conversations(alice)
    assert [c["id"] for c in da_alice] == [conversa_da_alice]


def test_get_messages_com_id_de_outro_usuario_retorna_vazio(bruno, conversa_da_alice):
    """Mesmo de posse do `conversation_id` correto, o não-dono não lê nada."""
    assert chat_history.get_messages(conversa_da_alice, bruno) == []


def test_get_messages_devolve_as_mensagens_para_o_dono(alice, conversa_da_alice):
    msgs = chat_history.get_messages(conversa_da_alice, alice)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "Quem se encaixa no PRONAF?"


def test_get_messages_preserva_a_ordem_da_conversa(alice):
    conversation_id = chat_history.create_conversation(alice)
    for i in range(4):
        chat_history.add_message(conversation_id, alice, "user", f"pergunta {i}")

    msgs = chat_history.get_messages(conversation_id, alice)
    assert [m["content"] for m in msgs] == [f"pergunta {i}" for i in range(4)]


# --- Escrita -----------------------------------------------------------------


def test_add_message_em_conversa_de_outro_e_recusado(alice, bruno, conversa_da_alice):
    """Era o furo: o frontend com `active_conversation_id` obsoleto gravava a
    pergunta do usuário novo dentro da conversa do usuário anterior.
    """
    with pytest.raises(PermissionError):
        chat_history.add_message(conversa_da_alice, bruno, "user", "mensagem intrusa")

    # E a recusa não deixa rastro: a transação inteira sofre rollback.
    msgs = chat_history.get_messages(conversa_da_alice, alice)
    assert [m["content"] for m in msgs] == ["Quem se encaixa no PRONAF?", "Resposta para a alice."]


def test_add_message_recusado_nao_altera_titulo_da_conversa_alheia(alice, bruno):
    """`add_message` também escreve em `conversations` (title/updated_at) — a
    checagem de dono precisa cobrir esses UPDATEs, não só o INSERT.
    """
    conversation_id = chat_history.create_conversation(alice)

    with pytest.raises(PermissionError):
        chat_history.add_message(conversation_id, bruno, "user", "título sequestrado")

    # title continua NULL: nenhuma das duas escritas vazou.
    assert chat_history.list_conversations(alice)[0]["title"] is None


def test_add_message_do_dono_grava_e_deriva_titulo(alice):
    conversation_id = chat_history.create_conversation(alice)
    row = chat_history.add_message(conversation_id, alice, "user", "Quem se encaixa no PRONAF?")

    assert row["role"] == "user"
    assert row["content"] == "Quem se encaixa no PRONAF?"
    assert chat_history.list_conversations(alice)[0]["title"] == "Quem se encaixa no PRONAF?"


def test_add_message_em_conversa_inexistente_e_recusado(alice):
    with pytest.raises(PermissionError):
        chat_history.add_message(999_999, alice, "user", "conversa que não existe")


def test_add_message_persiste_retrieved_chunks_como_jsonb(alice):
    """O snapshot dos chunks passa por `CAST(... AS jsonb)` — se a serialização
    quebrar, o histórico volta sem os trechos recuperados.
    """
    conversation_id = chat_history.create_conversation(alice)
    chunks = [{"id": 1, "score": 0.42, "text": "trecho", "secao_label": "2-A"}]
    chat_history.add_message(
        conversation_id, alice, "assistant", "resposta", search_mode="hybrid", retrieved_chunks=chunks
    )

    msg = chat_history.get_messages(conversation_id, alice)[0]
    assert msg["retrieved_chunks"] == chunks
    assert msg["search_mode"] == "hybrid"


# --- Rename / delete ---------------------------------------------------------


def test_rename_conversation_de_outro_usuario_nao_altera(alice, bruno, conversa_da_alice):
    chat_history.rename_conversation(conversa_da_alice, bruno, "renomeada pelo bruno")

    assert chat_history.list_conversations(alice)[0]["title"] == "Quem se encaixa no PRONAF?"


def test_delete_conversation_de_outro_usuario_nao_apaga(alice, bruno, conversa_da_alice):
    chat_history.delete_conversation(conversa_da_alice, bruno)

    assert [c["id"] for c in chat_history.list_conversations(alice)] == [conversa_da_alice]
    assert len(chat_history.get_messages(conversa_da_alice, alice)) == 2


def test_delete_conversation_do_dono_apaga_conversa_e_mensagens(alice, conversa_da_alice, engine):
    """Confirma o ON DELETE CASCADE de `messages.conversation_id`: sem ele as
    mensagens ficariam órfãs no banco depois da conversa sumir da sidebar.
    """
    from sqlalchemy import text

    chat_history.delete_conversation(conversa_da_alice, alice)

    assert chat_history.list_conversations(alice) == []
    with engine.connect() as conn:
        restantes = conn.execute(
            text("SELECT count(*) FROM messages WHERE conversation_id = :id"),
            {"id": conversa_da_alice},
        ).scalar()
    assert restantes == 0


# --- Sanidade ----------------------------------------------------------------


def test_create_conversation_pertence_a_quem_criou(alice, bruno):
    conversation_id = chat_history.create_conversation(bruno)

    assert [c["id"] for c in chat_history.list_conversations(bruno)] == [conversation_id]
    assert chat_history.list_conversations(alice) == []


def test_add_message_rejeita_role_invalida(alice):
    conversation_id = chat_history.create_conversation(alice)
    with pytest.raises(ValueError):
        chat_history.add_message(conversation_id, alice, "system", "role fora do CHECK")

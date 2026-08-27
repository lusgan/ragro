"""
advisor_state.py
-----------------
Persistência da sessão do Agente Conselheiro (docs/arquitetura-agentes.md),
uma por conversa, em `conversations.advisor_state`. O formato do dict (fase,
programa, respostas, slot_pendente etc.) é decidido por `src/agents/advisor.py`
— aqui só entra e sai um JSONB opaco.

Escopado por `user_id` via WHERE, do mesmo jeito e pelo mesmo motivo de
`chat_history.py`: um `conversation_id` obsoleto ou adivinhado precisa falhar,
nunca ler ou escrever a sessão de outro usuário.
"""

import json
from typing import Any

from sqlalchemy import text

from .db import get_engine


def carregar(conversation_id: int, user_id: int) -> dict[str, Any] | None:
    """Devolve o estado salvo, ou `None` se a conversa não tem sessão de
    conselheiro aberta (ou não pertence ao usuário)."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT advisor_state FROM conversations "
                "WHERE id = :conversation_id AND user_id = :user_id"
            ),
            {"conversation_id": conversation_id, "user_id": user_id},
        ).mappings().first()
        if row is None:
            return None
        return row["advisor_state"]


def salvar(conversation_id: int, user_id: int, estado: dict[str, Any] | None) -> None:
    """Substitui o estado da conversa.

    Levanta `PermissionError` quando nenhuma linha corresponde — a conversa
    não existe ou não é do `user_id` — espelhando `chat_history.add_message`,
    para que um estado nunca seja escrito na sessão de outro usuário.
    """
    estado_json = json.dumps(estado) if estado is not None else None

    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "UPDATE conversations SET advisor_state = CAST(:estado AS jsonb) "
                "WHERE id = :conversation_id AND user_id = :user_id"
            ),
            {"conversation_id": conversation_id, "user_id": user_id, "estado": estado_json},
        )
        if result.rowcount == 0:
            raise PermissionError(
                f"conversa {conversation_id} não pertence ao usuário {user_id}"
            )


def limpar(conversation_id: int, user_id: int) -> None:
    """Remove o estado da sessão (`NULL`), sem levantar se a conversa não
    pertencer ao usuário — mesmo comportamento silencioso de
    `chat_history.delete_conversation` para operações de limpeza."""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE conversations SET advisor_state = NULL "
                "WHERE id = :conversation_id AND user_id = :user_id"
            ),
            {"conversation_id": conversation_id, "user_id": user_id},
        )

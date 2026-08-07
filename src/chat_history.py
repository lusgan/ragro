"""
chat_history.py
----------------
Persistência de conversas e mensagens (histórico estilo chat) no Postgres
(Supabase). Toda leitura/escrita de mensagens é escopada por `user_id` via
JOIN/WHERE, para que um usuário nunca acesse a conversa de outro mesmo
adivinhando o `conversation_id`.
"""

import json
from typing import Any

from sqlalchemy import text

from .db import get_engine

TITLE_MAX_LEN = 40


def _derive_title(content: str) -> str:
    """Título curto derivado da primeira mensagem do usuário na conversa."""
    collapsed = " ".join(content.split())
    if len(collapsed) <= TITLE_MAX_LEN:
        return collapsed
    return collapsed[:TITLE_MAX_LEN].rstrip() + "…"


def create_conversation(user_id: int) -> int:
    with get_engine().begin() as conn:
        row = conn.execute(
            text("INSERT INTO conversations (user_id) VALUES (:user_id) RETURNING id"),
            {"user_id": user_id},
        ).mappings().first()
        return row["id"]


def list_conversations(user_id: int) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, title, updated_at FROM conversations "
                "WHERE user_id = :user_id ORDER BY updated_at DESC"
            ),
            {"user_id": user_id},
        ).mappings().all()
        return [dict(r) for r in rows]


def get_messages(conversation_id: int, user_id: int) -> list[dict[str, Any]]:
    """Mensagens da conversa, na ordem em que foram trocadas.

    Filtra por `user_id` via JOIN em vez de confiar apenas no
    `conversation_id` — evita que um usuário leia a conversa de outro.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT m.id, m.role, m.content, m.search_mode, m.retrieved_chunks, m.created_at "
                "FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.conversation_id = :conversation_id AND c.user_id = :user_id "
                "ORDER BY m.created_at"
            ),
            {"conversation_id": conversation_id, "user_id": user_id},
        ).mappings().all()
        return [dict(r) for r in rows]


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    search_mode: str | None = None,
    retrieved_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grava uma mensagem, atualiza `updated_at` da conversa e, se for a
    primeira mensagem do usuário, deriva o título da conversa.
    """
    if role not in ("user", "assistant"):
        raise ValueError(f"role inválida: {role!r}")

    retrieved_chunks_json = json.dumps(retrieved_chunks) if retrieved_chunks is not None else None

    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, search_mode, retrieved_chunks) "
                "VALUES (:conversation_id, :role, :content, :search_mode, "
                "CAST(:retrieved_chunks AS jsonb)) "
                "RETURNING id, role, content, search_mode, retrieved_chunks, created_at"
            ),
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "search_mode": search_mode,
                "retrieved_chunks": retrieved_chunks_json,
            },
        ).mappings().first()

        conn.execute(
            text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )

        if role == "user":
            conn.execute(
                text(
                    "UPDATE conversations SET title = :title "
                    "WHERE id = :id AND title IS NULL"
                ),
                {"id": conversation_id, "title": _derive_title(content)},
            )

        return dict(row)


def rename_conversation(conversation_id: int, user_id: int, title: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE conversations SET title = :title "
                "WHERE id = :id AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id, "title": title},
        )


def delete_conversation(conversation_id: int, user_id: int) -> None:
    """Apaga a conversa (e suas mensagens, via ON DELETE CASCADE) se pertencer ao usuário."""
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM conversations WHERE id = :id AND user_id = :user_id"),
            {"id": conversation_id, "user_id": user_id},
        )

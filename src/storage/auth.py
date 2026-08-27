"""
auth.py
-------
Login simples (email + senha) com cadastro protegido por código de convite.

Não usa o Supabase Auth de propósito: as credenciais vivem em uma tabela
`users` própria, hasheadas com bcrypt, para não acoplar a aplicação a um
provedor de auth específico.
"""

from typing import Any

import bcrypt
from sqlalchemy import text

from .db import get_engine


class AuthError(Exception):
    """Erro de validação/autenticação voltado para exibição ao usuário."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, email, password_hash, is_admin, is_active "
                "FROM users WHERE email = :email"
            ),
            {"email": email.strip().lower()},
        ).mappings().first()
        return dict(row) if row else None


def list_users_for_authenticator() -> dict[str, Any]:
    """Monta o dict de credenciais no formato esperado pelo streamlit-authenticator."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT email, password_hash FROM users WHERE is_active = true")
        ).mappings().all()

    return {
        "usernames": {
            row["email"]: {
                "email": row["email"],
                "name": row["email"].split("@")[0],
                "password": row["password_hash"],
            }
            for row in rows
        }
    }


def touch_last_login(email: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE users SET last_login_at = now() WHERE email = :email"),
            {"email": email.strip().lower()},
        )


def create_user(email: str, password: str, invite_code: str) -> dict[str, Any]:
    """Cria um usuário resgatando um código de convite, tudo em uma transação.

    O código só é considerado válido se ainda não tiver sido usado (e não
    estiver expirado). A checagem e o resgate acontecem via UPDATE ... RETURNING
    dentro da mesma transação do INSERT do usuário, para evitar que dois
    cadastros concorrentes resgatem o mesmo código.
    """
    email = email.strip().lower()
    invite_code = invite_code.strip()

    if not email or "@" not in email:
        raise AuthError("Email inválido.")
    if len(password) < 8:
        raise AuthError("A senha deve ter ao menos 8 caracteres.")
    if not invite_code:
        raise AuthError("Código de convite obrigatório.")

    password_hash = hash_password(password)

    with get_engine().begin() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM users WHERE email = :email"), {"email": email}
        ).first()
        if existing:
            raise AuthError("Já existe uma conta com esse email.")

        user_row = conn.execute(
            text(
                "INSERT INTO users (email, password_hash) "
                "VALUES (:email, :password_hash) "
                "RETURNING id, email"
            ),
            {"email": email, "password_hash": password_hash},
        ).mappings().first()

        claimed = conn.execute(
            text(
                "UPDATE invite_codes "
                "SET used_by = :user_id, used_at = now() "
                "WHERE code = :code "
                "  AND used_by IS NULL "
                "  AND (expires_at IS NULL OR expires_at > now()) "
                "RETURNING code"
            ),
            {"user_id": user_row["id"], "code": invite_code},
        ).first()

        if claimed is None:
            raise AuthError("Código de convite inválido, expirado ou já utilizado.")

        return dict(user_row)

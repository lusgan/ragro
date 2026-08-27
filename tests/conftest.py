"""
conftest.py
-----------
Infra dos testes: um Postgres descartável, as migrações de `src/storage/migrations/`
aplicadas nele e o engine do `src.storage.db` redirecionado para lá.

Por que Postgres de verdade e não SQLite: o isolamento entre usuários que estes
testes verificam mora inteiramente no SQL de `src/storage/chat_history.py` — `INSERT ...
SELECT ... WHERE user_id`, `CAST(... AS jsonb)`, `RETURNING`, `ON DELETE
CASCADE`. SQLite não suporta parte disso e trataria o resto de outro jeito, ou
seja, o teste passaria validando um SQL diferente do que roda em produção.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.storage import db

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "storage" / "migrations"

SKIP_REASON = (
    "TEST_DATABASE_URL não definida. Suba um Postgres descartável com "
    "`docker compose up -d postgres-test` e rode: "
    "TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/ragro_test pytest"
)


@pytest.fixture(scope="session")
def engine():
    """Engine para o banco de teste, com as migrações já aplicadas.

    Pula a suíte inteira (em vez de falhar) quando não há banco configurado:
    o resto do projeto não depende de Postgres para rodar, e quebrar `pytest`
    numa máquina sem Docker seria ruído.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(SKIP_REASON, allow_module_level=True)

    # Guarda-costas: estes testes truncam tabelas. Apontar TEST_DATABASE_URL
    # para o Supabase apagaria as conversas reais.
    if "supabase" in url or url == os.environ.get("DATABASE_URL"):
        pytest.fail(
            "TEST_DATABASE_URL aponta para o banco de produção. Estes testes "
            "truncam as tabelas — use um Postgres descartável."
        )

    eng = create_engine(url, pool_pre_ping=True)
    try:
        with eng.begin() as conn:
            # Recomeça do zero e reaplica as migrações em ordem de nome — as
            # mesmas que valem para produção (ver src/storage/migrations/README.md),
            # para que o schema de teste nunca divirja do real.
            conn.exec_driver_sql(
                "DROP TABLE IF EXISTS messages, conversations, invite_codes, users CASCADE"
            )
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                conn.exec_driver_sql(migration.read_text(encoding="utf-8"))
    except SQLAlchemyError as e:
        eng.dispose()
        pytest.skip(f"Postgres de teste inacessível em {url}: {e}")

    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(engine, monkeypatch):
    """Redireciona `src.storage.db.get_engine()` para o banco de teste e devolve as
    tabelas vazias a cada teste, para que um teste não enxergue linhas de outro.

    Não é `autouse`: os testes de `session_state` não tocam o banco e devem
    rodar mesmo sem Postgres. Quem precisa declara via `pytest.mark.usefixtures`.
    """
    monkeypatch.setattr(db, "_engine", engine)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE messages, conversations, invite_codes, users RESTART IDENTITY CASCADE")
        )
    yield


def _create_user(engine, email: str) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO users (email, password_hash) "
                "VALUES (:email, 'hash-irrelevante-para-estes-testes') RETURNING id"
            ),
            {"email": email},
        ).mappings().first()
        return row["id"]


@pytest.fixture
def alice(engine) -> int:
    """Dono das conversas nos testes de isolamento."""
    return _create_user(engine, "alice@example.com")


@pytest.fixture
def bruno(engine) -> int:
    """O 'usuário novo' do bug original: não pode ver nada da alice."""
    return _create_user(engine, "bruno@example.com")

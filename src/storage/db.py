"""
db.py
-----
Conexão com o Postgres (Supabase) via SQLAlchemy Core.

Usa DATABASE_URL diretamente (connection string Postgres padrão), sem
depender do SDK do Supabase, para não acoplar o código à camada
REST/PostgREST — se o projeto migrar de provedor no futuro, só a env var muda.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .. import config  # noqa: F401 — aciona load_dotenv()

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        database_url = os.environ["DATABASE_URL"]
        _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine

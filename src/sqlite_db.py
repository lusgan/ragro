"""
sqlite_db.py
------------
Banco SQLite local para registrar estatísticas dos chunks gerados pelo word_chunker.

Tabelas:
    chunks_docx   — uma linha por seção processada, com contagem e stats de tokens
    run_log       — histórico de execuções do chunker (opcional, para comparação)

Uso:
    from src.sqlite_db import init_db, upsert_chunks_stats, get_run_summary
    con = init_db()                         # cria/abre ragro.db
    upsert_chunks_stats(con, docs)          # persiste stats dos chunks
    print(get_run_summary(con))             # dict com totais
"""

import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from .config import count_tokens

DB_PATH = Path("reports/ragro.db")


# ── Criação do esquema ────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at          TEXT    NOT NULL,   -- ISO-8601
    total_sections  INTEGER NOT NULL,
    total_chunks    INTEGER NOT NULL,
    sections_split  INTEGER NOT NULL,   -- seções com > 1 sub-chunk
    -- distribuição de tokens_total por seção nesta run
    tokens_min      INTEGER NOT NULL,
    tokens_max      INTEGER NOT NULL,
    tokens_mean     REAL    NOT NULL,
    tokens_median   REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks_docx (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES run_log(id),
    capitulo_num    INTEGER NOT NULL,
    capitulo_text   TEXT    NOT NULL,
    secao_num       INTEGER NOT NULL,
    secao_text      TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    total_chunks    INTEGER NOT NULL,
    tokens_total    INTEGER NOT NULL,
    UNIQUE (run_id, capitulo_num, secao_num)
);
"""


def init_db(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Abre (ou cria) o banco SQLite e garante que o esquema existe."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.commit()
    return con


# ── Inserção ──────────────────────────────────────────────────────────────────


def upsert_chunks_stats(
    con: sqlite3.Connection,
    docs: list[Document],
    db_path: str | Path = DB_PATH,
) -> int:
    """
    Persiste estatísticas de uma lista de Documents no banco.

    Agrupa por (capitulo_num, secao_num), calcula stats de tokens por sub-chunk
    e insere um registro na run_log + N registros em chunks_docx.

    Retorna o run_id gerado.
    """
    # Agrupar por seção
    sections: dict[tuple, list[Document]] = {}
    for d in docs:
        m = d.metadata
        key = (m["capitulo_num"], m["secao_num"])
        sections.setdefault(key, []).append(d)

    # Stats por seção (tokens_total de cada seção)
    section_token_totals = [
        sum(count_tokens(d.page_content) for d in sec_docs)
        for sec_docs in sections.values()
    ]
    section_stats = _stats(section_token_totals)

    # Inserir run_log
    cur = con.execute(
        """
        INSERT INTO run_log
            (ran_at, total_sections, total_chunks,
             sections_split,
             tokens_min, tokens_max, tokens_mean, tokens_median)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            len(sections),
            len(docs),
            sum(1 for s in sections.values() if len(s) > 1),
            section_stats["min"],
            section_stats["max"],
            section_stats["mean"],
            section_stats["median"],
        ),
    )
    run_id = cur.lastrowid

    # Inserir chunks_docx
    rows = []
    for (cap_num, sec_num), sec_docs in sorted(sections.items()):
        m0 = sec_docs[0].metadata
        tokens_total = sum(count_tokens(d.page_content) for d in sec_docs)
        rows.append((
            run_id,
            cap_num,
            m0["capitulo_text"],
            sec_num,
            m0["secao_text"],
            m0["source"],
            len(sec_docs),
            tokens_total,
        ))

    con.executemany(
        """
        INSERT OR REPLACE INTO chunks_docx
            (run_id, capitulo_num, capitulo_text, secao_num, secao_text,
             source, total_chunks, tokens_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    return run_id


# ── Consultas ─────────────────────────────────────────────────────────────────


def get_run_summary(con: sqlite3.Connection, run_id: int | None = None) -> dict[str, Any]:
    """Retorna o resumo da run mais recente (ou de run_id específico)."""
    if run_id is None:
        row = con.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
    else:
        row = con.execute("SELECT * FROM run_log WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else {}


def get_sections_table(
    con: sqlite3.Connection,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Retorna todas as linhas de chunks_docx para uma run (default = última)."""
    if run_id is None:
        run_row = con.execute("SELECT id FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
        if not run_row:
            return []
        run_id = run_row["id"]
    rows = con.execute(
        "SELECT * FROM chunks_docx WHERE run_id = ? ORDER BY capitulo_num, secao_num",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _stats(values: list[int]) -> dict[str, float]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0.0, "median": 0.0}
    return {
        "min":    min(values),
        "max":    max(values),
        "mean":   statistics.mean(values),
        "median": statistics.median(values),
    }

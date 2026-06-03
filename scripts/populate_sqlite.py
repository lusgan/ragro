"""Popula o SQLite com estatísticas dos chunks e exibe um resumo."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.disable(logging.CRITICAL)

from src.word_chunker import get_all_chunks_from_docx
from src.sqlite_db import init_db, upsert_chunks_stats, get_run_summary, get_sections_table

docs = get_all_chunks_from_docx("data/MCR - docx")

con = init_db()
run_id = upsert_chunks_stats(con, docs)

# ── Resumo da run ──────────────────────────────────────────────────────────
summary = get_run_summary(con, run_id)
print(f"Run #{run_id}  —  {summary['ran_at']}")
print(f"  Seções:           {summary['total_sections']}")
print(f"  Chunks totais:    {summary['total_chunks']}")
print(f"  Seções divididas: {summary['sections_split']}")
print(f"  Tokens por seção (distribuição):")
print(f"    min    = {summary['tokens_min']}")
print(f"    max    = {summary['tokens_max']}")
print(f"    mean   = {summary['tokens_mean']:.0f}")
print(f"    median = {summary['tokens_median']:.0f}")

# ── Tabela de seções ───────────────────────────────────────────────────────
print(f"\n{'Cap':>3} {'Sec':>3}  {'Chunks':>6}  {'Total tok':>9}  Seção")
print("-" * 70)
for r in get_sections_table(con, run_id):
    flag = " ◄ SPLIT" if r["total_chunks"] > 1 else ""
    print(
        f"{r['capitulo_num']:>3} {r['secao_num']:>3}  "
        f"{r['total_chunks']:>6}  "
        f"{r['tokens_total']:>9}  "
        f"{r['secao_text'][:45]}"
        f"{flag}"
    )

print(f"\nBanco salvo em: reports/ragro.db")

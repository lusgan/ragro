"""Exporta todos os chunks para um arquivo de texto para inspeção manual."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.disable(logging.CRITICAL)

from src.word_chunker import get_all_chunks_from_docx

OUTPUT = Path("reports/chunks_dump.txt")
OUTPUT.parent.mkdir(exist_ok=True)

docs = get_all_chunks_from_docx("data/MCR - docx")

with OUTPUT.open("w", encoding="utf-8") as f:
    f.write("DUMP DE CHUNKS — MCR\n")
    f.write(f"Total: {len(docs)} chunks\n")
    f.write("=" * 80 + "\n\n")

    for i, d in enumerate(docs, 1):
        m = d.metadata
        f.write(f"{'=' * 80}\n")
        f.write(f"CHUNK {i}/{len(docs)}\n")
        f.write(f"Capítulo {m['capitulo_num']}: {m['capitulo_text']}\n")
        f.write(f"Seção    {m.get('secao_label') or m['secao_num']}: {m['secao_text']}\n")
        f.write(f"Source:  {m['source']}\n")
        f.write(f"Sub-chunk: {m['chunk_index'] + 1}/{m['total_chunks']}  ({len(d.page_content)} chars)\n")
        f.write(f"{'-' * 80}\n")
        f.write(d.page_content)
        f.write("\n\n")

print(f"Exportado para: {OUTPUT}  ({OUTPUT.stat().st_size // 1024} KB)")

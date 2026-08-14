import logging
import math
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

MCR_PDF_PATH   = "data/MCR.pdf"
MCR_MD_PATH    = "data/MCR.md"
PAGES_PER_BATCH = 9  # páginas por lote — reduza se ainda ocorrer bad_alloc


def _get_page_count(pdf_path: str) -> int:
    from pypdf import PdfReader
    return len(PdfReader(pdf_path).pages)


def extract(
    pdf_path: str = MCR_PDF_PATH,
    md_path: str = MCR_MD_PATH,
    use_hybrid: bool = False,
) -> str:
    """Converte MCR.pdf em MCR.md processando em lotes de PAGES_PER_BATCH páginas.

    Cada lote spawna um processo JVM independente, liberando RAM entre iterações.
    Se use_hybrid=True, ativa OCR docling-fast para páginas com fontes CID sem
    mapeamento Unicode. Requer:
      1. pip install "opendataloader-pdf[hybrid]"
      2. Servidor rodando: opendataloader-pdf-hybrid --port 5002
    """
    out = Path(md_path)
    if out.exists():
        logger.info("MCR.md já existe em '%s' — extração pulada.", md_path)
        return md_path

    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

    try:
        from opendataloader_pdf import convert
    except ImportError as exc:
        raise RuntimeError(
            "opendataloader-pdf não instalado. Execute: pip install \"opendataloader-pdf[hybrid]\"\n"
            "Requer Java 11+ instalado na máquina."
        ) from exc

    hybrid_mode   = "docling-fast" if use_hybrid else None
    total_pages   = _get_page_count(pdf_path)
    num_batches   = math.ceil(total_pages / PAGES_PER_BATCH)

    logger.info(
        "Convertendo '%s' em %d lotes de %d páginas (hybrid=%s, total=%d págs)...",
        pdf_path, num_batches, PAGES_PER_BATCH, hybrid_mode or "off", total_pages,
    )

    parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i in range(num_batches):
            start      = i * PAGES_PER_BATCH + 1
            end        = min(start + PAGES_PER_BATCH - 1, total_pages)
            pages_spec = f"{start}-{end}"
            logger.info("  Lote %d/%d — páginas %s...", i + 1, num_batches, pages_spec)

            convert(
                input_path=[pdf_path],
                output_dir=tmp + "/",
                format="markdown",
                hybrid=hybrid_mode,
                hybrid_fallback=True,
                pages=pages_spec,
            )

            batch_file = tmp_path / "MCR.md"
            if not batch_file.exists():
                raise RuntimeError(
                    f"Lote {i + 1} falhou: arquivo não gerado para páginas {pages_spec}."
                )
            parts.append(batch_file.read_text(encoding="utf-8"))
            batch_file.unlink()

    out.write_text("\n".join(parts), encoding="utf-8")
    logger.info("Conversão concluída em %d lotes: '%s'", num_batches, md_path)
    return md_path

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MCR_PDF_PATH = "data/MCR.pdf"
MCR_MD_PATH  = "data/MCR.md"


def extract(
    pdf_path: str = MCR_PDF_PATH,
    md_path: str = MCR_MD_PATH,
    use_hybrid: bool = False,
) -> str:
    """Converte MCR.pdf em MCR.md.

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

    hybrid_mode = "docling-fast" if use_hybrid else None
    logger.info(
        "Convertendo '%s' para Markdown via OpenDataLoader (hybrid=%s)...",
        pdf_path,
        hybrid_mode or "off",
    )
    try:
        from opendataloader_pdf import convert
        convert(
            input_path=[pdf_path],
            output_dir=str(out.parent) + "/",
            format="markdown",
            hybrid=hybrid_mode,
            hybrid_fallback=True,   # fallback para Java se o backend falhar (evita fail-fast)
        )
    except ImportError as exc:
        raise RuntimeError(
            "opendataloader-pdf não instalado. Execute: pip install \"opendataloader-pdf[hybrid]\"\n"
            "Requer Java 11+ instalado na máquina."
        ) from exc

    if not out.exists():
        raise RuntimeError(
            f"Conversão falhou: '{md_path}' não foi gerado. "
            "Verifique se Java 11+ está instalado e se o PDF não está corrompido."
        )

    logger.info("Conversão concluída: '%s'", md_path)
    return md_path

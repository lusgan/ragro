"""Script de teste: extração de MCR.pdf via Azure Document Intelligence.

O Azure DI aceita no máximo ~4MB por request ao enviar bytes diretamente.
O MCR.pdf tem 8MB, então o PDF é dividido em lotes de PAGES_PER_BATCH páginas,
cada lote é enviado como arquivo temporário separado e os Markdowns são concatenados.

Gera data/MCR_azure_test.md para comparação com o output do opendataloader.

Uso:
    python scripts/test_azure_di.py
"""

import io
import math
import os
import time
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

load_dotenv()

PDF_PATH        = Path("data/MCR.pdf")
OUT_PATH        = Path("data/MCR_azure_test.md")
PAGES_PER_BATCH = 50  # ~1MB por lote — reduz se necessário


def _extract_batch(client: DocumentIntelligenceClient, pdf_bytes: bytes) -> str:
    """Envia um trecho do PDF ao Azure DI e retorna o Markdown resultante."""
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=pdf_bytes,
        output_content_format="markdown",
    )
    return poller.result().content


def main() -> None:
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    key      = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")

    if not endpoint or not key:
        raise RuntimeError(
            "Variáveis AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT e "
            "AZURE_DOCUMENT_INTELLIGENCE_KEY não encontradas no .env."
        )

    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF não encontrado: {PDF_PATH}")

    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )

    reader      = PdfReader(PDF_PATH)
    total_pages = len(reader.pages)
    num_batches = math.ceil(total_pages / PAGES_PER_BATCH)

    print(
        f"MCR.pdf: {total_pages} páginas → {num_batches} lotes de {PAGES_PER_BATCH} págs."
    )

    parts: list[str] = []
    t0 = time.perf_counter()

    for i in range(num_batches):
        start = i * PAGES_PER_BATCH
        end   = min(start + PAGES_PER_BATCH, total_pages)
        print(f"  Lote {i + 1}/{num_batches} — páginas {start + 1}-{end}...", end=" ", flush=True)

        writer = PdfWriter()
        for page_idx in range(start, end):
            writer.add_page(reader.pages[page_idx])

        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        t_batch = time.perf_counter()
        parts.append(_extract_batch(client, pdf_bytes))
        print(f"{time.perf_counter() - t_batch:.1f}s ({len(pdf_bytes) / 1024:.0f} KB)")

    OUT_PATH.write_text("\n".join(parts), encoding="utf-8")
    elapsed = time.perf_counter() - t0

    print(f"\nConcluído em {elapsed:.1f}s — '{OUT_PATH}'")
    print(
        "\nPróximo passo: verificar se o output preserva as linhas estruturais:\n"
        "  Select-String -Path data\\MCR_azure_test.md -Pattern 'SEÇÃO|SECAO'"
    )


if __name__ == "__main__":
    main()

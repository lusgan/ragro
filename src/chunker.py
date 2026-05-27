import re
import logging
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from .config import count_tokens

logger = logging.getLogger(__name__)

TOKEN_LIMIT = 28_000

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=TOKEN_LIMIT,
    chunk_overlap=200,
    length_function=count_tokens,
)

# ── Padrões reais confirmados na inspeção do MCR.md ─────────────────────────────
#
# Linhas estruturais têm o formato (uma ou mais partes na mesma linha):
#   TÍTULO  : CRÉDITO RURAL [N]  CAPÍTULO : texto - N  SEÇÃO : texto - N [(*)] ____
#
# Observações:
#   • SEÇÃO sempre presente nas linhas estruturais (63 ocorrências, 50 únicas)
#   • CAPÍTULO e TÍTULO aparecem combinados na mesma linha da SEÇÃO
#   • Número de TÍTULO é opcional (ex.: "TÍTULO : CRÉDITO RURAL CAPÍTULO :")
#   • Typo em L2961: "TTÍTULO" (duplo T)
#   • CAPÍTULO sem espaço antes de ":" em L5611: "CAPÍTULO:"
#   • Linhas terminam com "____" (underscores), não com o número da seção
#   • Linhas repetidas = rodapés de página da mesma SEÇÃO (deduplicação necessária)

# SEÇÃO : texto - N  [(*)]  ____...
_RE_SECAO = re.compile(
    r"SE[ÇC][ÃA]O\s*:\s*(.+?)\s*-\s*(\d+)\s*(?:\(\*\))?\s*_*",
    re.IGNORECASE,
)

# CAPÍTULO : texto - N  (para antes de SEÇÃO, underscores ou fim de linha)
_RE_CAPITULO = re.compile(
    r"CAP[ÍI]TULO\s*:?\s*(.+?)\s*-\s*(\d+)(?=\s+SE[ÇC][ÃA]O|\s*_|\s*$)",
    re.IGNORECASE,
)

# TT?ÍTULO : texto [N]  (número opcional; para antes de CAPÍTULO)
_RE_TITULO = re.compile(
    r"TT?[ÍI]TULO\s*:\s*(.+?)(?:\s+(\d+))?\s+CAP[ÍI]TULO",
    re.IGNORECASE,
)

_ORPHAN_META: dict = {
    "titulo_num":    "?",
    "titulo_text":   "ORPHAN",
    "capitulo_num":  "?",
    "capitulo_text": "ORPHAN",
    "secao_num":     "?",
    "secao_text":    "ORPHAN",
    "source":        "MCR.pdf",
}


def _build_docs(content: str, meta: dict) -> list[Document]:
    tokens = count_tokens(content)
    if tokens <= TOKEN_LIMIT:
        return [Document(page_content=content, metadata={**meta, "chunk_index": 0, "total_chunks": 1})]

    sub_texts = _splitter.split_text(content)
    n = len(sub_texts)
    logger.info(
        "Seção %s/%s/%s dividida em %d sub-chunks (%d tokens).",
        meta["titulo_num"], meta["capitulo_num"], meta["secao_num"], n, tokens,
    )
    return [
        Document(page_content=sub, metadata={**meta, "chunk_index": i, "total_chunks": n})
        for i, sub in enumerate(sub_texts)
    ]


def get_all_chunks(md_path: str = "data/MCR.md") -> list[Document]:
    path = Path(md_path)
    if not path.exists():
        raise FileNotFoundError(
            f"MCR.md não encontrado em '{md_path}'. Execute o extractor primeiro."
        )

    lines = path.read_text(encoding="utf-8").splitlines()
    documents: list[Document] = []

    # Estado global de metadados (atualizado ao encontrar linhas estruturais)
    titulo_num    = "?"
    titulo_text   = "CRÉDITO RURAL"
    capitulo_num  = "?"
    capitulo_text = "UNKNOWN"

    current_meta: dict       = dict(_ORPHAN_META)
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        current_lines = []
        if not content:
            return
        if current_meta["secao_text"] == "ORPHAN":
            logger.warning(
                "Chunk ORPHAN salvo: %d linhas. Início: %.100s",
                len(content.splitlines()),
                content,
            )
        documents.extend(_build_docs(content, current_meta))

    for line in lines:
        s_match = _RE_SECAO.search(line)

        if not s_match:
            # Linha de conteúdo normal — acumula na seção atual
            current_lines.append(line)
            continue

        # ── Linha estrutural: contém SEÇÃO : ────────────────────────────────────

        # 1. Atualiza TÍTULO se presente na mesma linha
        t_match = _RE_TITULO.search(line)
        if t_match:
            titulo_text = t_match.group(1).strip()
            titulo_num  = t_match.group(2) if t_match.group(2) else "?"

        # 2. Atualiza CAPÍTULO se presente na mesma linha
        c_match = _RE_CAPITULO.search(line)
        if c_match:
            capitulo_text = c_match.group(1).strip()
            capitulo_num  = c_match.group(2)

        # 3. Extrai identificador da SEÇÃO
        new_secao_num  = s_match.group(2)
        new_secao_text = s_match.group(1).strip()

        # 4. Deduplicação de rodapé: se a SEÇÃO é a mesma que a corrente, descarta a linha
        if (new_secao_num  == current_meta.get("secao_num")
                and new_secao_text == current_meta.get("secao_text")):
            logger.debug("Rodapé duplicado ignorado: SEÇÃO %s — %.80s", new_secao_num, line)
            continue

        # 5. Nova SEÇÃO: fecha a anterior e abre uma nova
        flush()
        current_meta = {
            "titulo_num":    titulo_num,
            "titulo_text":   titulo_text,
            "capitulo_num":  capitulo_num,
            "capitulo_text": capitulo_text,
            "secao_num":     new_secao_num,
            "secao_text":    new_secao_text,
            "source":        "MCR.pdf",
        }

    flush()  # Última seção

    orphan_count = sum(1 for d in documents if d.metadata.get("secao_text") == "ORPHAN")
    logger.info(
        "Chunking concluído: %d chunks gerados (%d órfãos).",
        len(documents),
        orphan_count,
    )
    return documents

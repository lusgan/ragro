"""
word_chunker.py
---------------
Converte arquivos .docx do MCR (BCB) em LangChain Documents prontos
para indexação no Qdrant.

Espera a estrutura de pastas do site MCR:
    docx_dir/
      01 - MCR Normas/
        01 - Disposições Preliminares/
          1_-_Autorizacao_para_Operar_em_Credito_Rural_e_Estrutura_Operativa.docx
          ...
        02 - Condições Básicas/
          ...

O chunker:
  1. Deriva metadados (capítulo/seção) dos nomes de pasta e arquivo
  2. Extrai parágrafos e tabelas com python-docx
  3. Serializa tabelas como "chave: valor" por linha (formato semântico)
  4. Emite um Document por seção; se exceder TOKEN_LIMIT, subdivide com
     RecursiveCharacterTextSplitter

Uso:
    from src.word_chunker import get_all_chunks_from_docx
    docs = get_all_chunks_from_docx("data/MCR - docx")
"""

import logging
import re
import sys
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import count_tokens

logger = logging.getLogger(__name__)

TOKEN_LIMIT = 28_000

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=TOKEN_LIMIT,
    chunk_overlap=200,
    length_function=count_tokens,
)

# ── Extração de texto de tabelas ──────────────────────────────────────────────


def _table_to_text(table) -> str:
    """
    Serializa uma tabela Word como linhas limpas, lidando com células mescladas.

    python-docx repete o mesmo texto para cada coluna dentro de um merge span.
    Usamos cell._tc (elemento XML) para identificar células únicas por linha.

    Estratégia por linha (após deduplicação):
      - 0 células não-vazias  → ignorada
      - 1 célula não-vazia    → emitida como linha simples (título/cabeçalho de seção)
      - N células não-vazias  → emitidas como "val1 | val2 | val3"
    """
    lines = []

    for row in table.rows:
        # Deduplicar por identidade do elemento XML (_tc)
        seen_tc: list = []
        unique_cells = []
        for cell in row.cells:
            if cell._tc not in seen_tc:
                seen_tc.append(cell._tc)
                unique_cells.append(cell)

        # Textos não-vazios
        texts = [c.text.strip() for c in unique_cells if c.text.strip()]

        if not texts:
            continue
        elif len(texts) == 1:
            lines.append(texts[0])
        else:
            lines.append(" | ".join(texts))

    return "\n".join(lines)


# ── Extração de conteúdo do .docx ─────────────────────────────────────────────


def _is_header_paragraph(para) -> bool:
    """Paragráfos com estilo 'Header' são metadados da seção, não conteúdo."""
    return para.style.name.lower().startswith("header")


def _win_path(path: Path) -> str:
    """Aplica prefixo \\?\ no Windows para contornar o limite MAX_PATH de 260 chars."""
    resolved = str(path.resolve())
    if sys.platform == "win32" and len(resolved) > 260:
        return "\\\\?\\" + resolved
    return resolved


def _extract_content(docx_path: Path) -> str:
    """
    Extrai o conteúdo textual de um .docx como string pronta para embedding.

    - Parágrafos de cabeçalho (TÍTULO/CAPÍTULO/SEÇÃO) são descartados
    - Parágrafos vazios são descartados
    - Tabelas são serializadas como "chave: valor"
    - A ordem docx (parágrafos e tabelas intercalados) é preservada
    """
    doc = DocxDocument(_win_path(docx_path))
    parts: list[str] = []

    # python-docx itera apenas parágrafos com doc.paragraphs e apenas tabelas
    # com doc.tables. Para preservar a ordem, precisamos iterar o XML do body.
    body = doc.element.body

    for child in body:
        tag = child.tag.split("}")[-1]  # 'p' ou 'tbl'

        if tag == "p":
            # Criar objeto parágrafo a partir do elemento XML
            from docx.text.paragraph import Paragraph
            para = Paragraph(child, doc)
            if _is_header_paragraph(para):
                continue
            text = para.text.strip()
            if text:
                parts.append(text)

        elif tag == "tbl":
            from docx.table import Table
            table = Table(child, doc)
            table_text = _table_to_text(table)
            if table_text.strip():
                parts.append(table_text)

    return "\n".join(parts)


# ── Parsing de nomes de pasta/arquivo do MCR ─────────────────────────────────

_RE_CAP_FOLDER = re.compile(r'^(\d+)\s*-\s*(.+)$')
_RE_SEC_FILE   = re.compile(r'^(\d+)(?:-[A-Za-z])?_-_(.+)$')


def _parse_cap_folder(name: str) -> tuple[int, str]:
    """'01 - Disposições Preliminares' → (1, 'Disposições Preliminares')"""
    m = _RE_CAP_FOLDER.match(name)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return 0, name


def _parse_sec_file(stem: str) -> tuple[int, str]:
    """
    '1_-_Autorizacao_para_Operar...' → (1, 'Autorizacao para Operar...')
    '4-A_-_Metodologia...'           → (4, 'Metodologia...')
    '10_-_Normas_Transitorias'       → (10, 'Normas Transitorias')
    """
    m = _RE_SEC_FILE.match(stem)
    if m:
        return int(m.group(1)), m.group(2).replace('_', ' ').strip()
    return 0, stem.replace('_', ' ')


# ── Construção de Documents ───────────────────────────────────────────────────


def _build_docs(content: str, meta: dict) -> list[Document]:
    tokens = count_tokens(content)
    if tokens <= TOKEN_LIMIT:
        return [Document(
            page_content=content,
            metadata={**meta, "chunk_index": 0, "total_chunks": 1},
        )]

    sub_texts = _splitter.split_text(content)
    n = len(sub_texts)
    logger.info(
        "Seção %s/%s dividida em %d sub-chunks (%d tokens).",
        meta.get("capitulo_num"), meta.get("secao_num"), n, tokens,
    )
    return [
        Document(
            page_content=sub,
            metadata={**meta, "chunk_index": i, "total_chunks": n},
        )
        for i, sub in enumerate(sub_texts)
    ]


# ── API pública ───────────────────────────────────────────────────────────────


def get_all_chunks(docx_dir: str = "data/MCR - docx") -> list[Document]:
    """
    Gera LangChain Documents a partir da estrutura de pastas do MCR.

    Espera:
        docx_dir/
          01 - MCR Normas/
            NN - Capítulo/
              N_-_Secao.docx

    Ordena por capítulo/seção para output determinístico.
    Ignora capítulo 00 (Índice) e arquivos não-.docx.

    Retorna lista de Documents com metadata:
        capitulo_num, capitulo_text, secao_num, secao_text,
        source, chunk_index, total_chunks
    """
    dir_path = Path(docx_dir)
    normas_path = dir_path / "01 - MCR Normas"
    if not normas_path.exists():
        normas_path = dir_path  # fallback: usuário passou a subpasta diretamente
    if not normas_path.exists():
        raise FileNotFoundError(f"Diretório não encontrado: {normas_path}")

    documents: list[Document] = []
    total_files = 0

    # Ordenar capítulos por número
    cap_folders = sorted(
        [d for d in normas_path.iterdir() if d.is_dir()],
        key=lambda d: _parse_cap_folder(d.name)[0],
    )

    for cap_folder in cap_folders:
        cap_num, cap_text = _parse_cap_folder(cap_folder.name)

        # Pular capítulo 00 (Índice do MCR, não é conteúdo normativo)
        if cap_num == 0:
            logger.debug("Pulando índice: %s", cap_folder.name)
            continue

        # Ordenar seções por número
        sec_files = sorted(
            [f for f in cap_folder.iterdir() if f.suffix.lower() == ".docx" and Path(_win_path(f)).is_file()],
            key=lambda f: _parse_sec_file(f.stem)[0],
        )

        for docx_path in sec_files:
            total_files += 1
            sec_num, sec_text = _parse_sec_file(docx_path.stem)

            meta = {
                "capitulo_num": cap_num,
                "capitulo_text": cap_text,
                "secao_num": sec_num,
                "secao_text": sec_text,
                "source": str(docx_path.relative_to(dir_path)).replace("\\", "/"),
            }

            try:
                content = _extract_content(docx_path)
            except Exception as exc:
                logger.error("Erro ao processar %s: %s", docx_path.name, exc)
                continue

            if not content.strip():
                logger.warning("Conteúdo vazio em: %s", docx_path.name)
                continue

            docs = _build_docs(content, meta)
            documents.extend(docs)
            logger.info(
                "Cap %s Sec %s → %d chunk(s) | %d tokens | %s",
                cap_num, sec_num,
                len(docs), count_tokens(content), docx_path.name,
            )

    orphans = sum(1 for d in documents if d.metadata.get("secao_num") is None)
    logger.info(
        "Chunking concluído: %d docs gerados (%d órfãos) a partir de %d arquivos.",
        len(documents), orphans, total_files,
    )
    return documents

import hashlib
import logging
import unicodedata
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from fastembed.sparse.bm25 import Bm25
from fastembed.sparse.sparse_embedding_base import SparseTextEmbeddingBase

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


BM25_MODEL    = "Qdrant/bm25"
BM25_LANGUAGE = "portuguese"


def strip_accents(token: str) -> str:
    """Remove diacríticos: 'crédito' -> 'credito', 'condição' -> 'condicao'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", token) if not unicodedata.combining(c)
    )


class _Bm25SemAcento(Bm25):
    """BM25 insensível a acento, com a lista de stopwords lida corretamente.

    Duas correções sobre o Bm25 do fastembed; ambas valem para indexação e
    busca ao mesmo tempo, porque raw_embed() e query_embed() compartilham os
    dois métodos sobrescritos aqui. A simetria é estrutural, não disciplina.

    1. ACENTO (_stem) — 'crédito' e 'credito' geravam hashes diferentes, e quem
       digita sem acento não achava nada; ~20% do vocabulário do MCR é
       acentuado. A dobra acontece DEPOIS da stemização, nunca antes: o stemmer
       snowball usa o acento nas próprias regras, e sem ele 'operação' e
       'operações' param de colapsar (viram 'operaca' e 'operaco').

    2. ENCODING (_load_stopwords) — o fastembed abre o arquivo de stopwords com
       open(path, "r") sem encoding, então o Python usa o padrão do sistema.
       No Windows isso é cp1252 e o arquivo é UTF-8: 'até' vira 'atÃ©' e as 37
       stopwords acentuadas ('não', 'são', 'está', 'até') deixam de filtrar
       qualquer coisa. No Linux o mesmo código funciona — ou seja, o índice
       dependia do sistema operacional de quem rodou a indexação.
    """

    @classmethod
    def _load_stopwords(cls, model_dir: Path, language: str) -> list[str]:
        stopwords_path = model_dir / f"{language}.txt"
        if not stopwords_path.exists():
            return []

        with open(stopwords_path, encoding="utf-8") as f:
            palavras = f.read().splitlines()

        # A forma sem acento também precisa filtrar: o texto do MCR traz 'não',
        # mas a pergunta do usuário frequentemente vem como 'nao'.
        return palavras + [strip_accents(p) for p in palavras]

    def _stem(self, tokens: list[str]) -> list[str]:
        return [strip_accents(token) for token in super()._stem(tokens)]


def build_bm25() -> SparseTextEmbeddingBase:
    """Instancia o BM25 esparso.

    Indexação e busca precisam usar o MESMO stemmer/stopwords/normalização —
    construir o modelo só por aqui garante isso. O default do fastembed é
    'english', que aplicaria stemming inglês e deixaria passar stopwords
    portuguesas.
    """
    return _Bm25SemAcento(model_name=BM25_MODEL, language=BM25_LANGUAGE)


class ChunkStrategy(str, Enum):
    FULL_SECTION_32K = "full_section_32k"
    FIXED_500        = "fixed_500"
    FIXED_1000       = "fixed_1000"
    FIXED_4000       = "fixed_4000"


_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer
        # local_files_only evita requisições ao HuggingFace após o primeiro download
        try:
            _tokenizer = AutoTokenizer.from_pretrained(
                "voyageai/voyage-4-large", local_files_only=True
            )
        except Exception:
            _tokenizer = AutoTokenizer.from_pretrained("voyageai/voyage-4-large")
    return _tokenizer


def count_tokens(text: str) -> int:
    return len(_get_tokenizer().encode(text))


def make_chunk_id(capitulo_num: int, secao_label: str, chunk_index: int) -> int:
    """ID determinístico de um chunk a partir da sua posição no MCR.

    secao_label é o rótulo, não o número: '4' e '4-A' são seções distintas do
    Capítulo 2 e precisam de ids distintos. Usar o número inteiro fazia as duas
    colidirem, e a 4-A (TRFC) sumia do índice no upsert.
    """
    key = f"{capitulo_num}|{secao_label}|{chunk_index}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % (2**63)

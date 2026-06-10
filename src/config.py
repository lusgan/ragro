import hashlib
import logging
from enum import Enum

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


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


def make_chunk_id(titulo_num: str, capitulo_num: str, secao_num: str, chunk_index: int) -> int:
    key = f"{titulo_num}|{capitulo_num}|{secao_num}|{chunk_index}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % (2**63)

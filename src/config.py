import hashlib
import logging
from enum import Enum

from dotenv import load_dotenv
from transformers import AutoTokenizer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


class ChunkStrategy(str, Enum):
    FULL_SECTION_32K = "full_section_32k"
    FIXED_500        = "fixed_500"
    FIXED_1000       = "fixed_1000"
    FIXED_4000       = "fixed_4000"


# Tokenizer carregado uma vez no nível do módulo — local, sem chamada de API
_tokenizer = AutoTokenizer.from_pretrained("voyageai/voyage-4-large")


def count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text))


def make_chunk_id(titulo_num: str, capitulo_num: str, secao_num: str, chunk_index: int) -> int:
    key = f"{titulo_num}|{capitulo_num}|{secao_num}|{chunk_index}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % (2**63)

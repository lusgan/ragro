import base64
import json
import logging
import os

from google import genai
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-pro"

SYSTEM_PROMPT = (
    "Você é um assistente especializado no Manual de Crédito Rural (MCR). "
    "Responda à pergunta do usuário usando exclusivamente as informações "
    "presentes no CONTEXTO abaixo, extraído do manual. "
    "Se o contexto não for suficiente para responder, diga isso claramente — "
    "não invente informação. Cite o capítulo e a seção de onde tirou cada "
    "afirmação relevante."
)

_client: genai.Client | None = None


def _load_sa_credentials() -> service_account.Credentials:
    sa_info = json.loads(base64.b64decode(os.environ["GCLOUD_SA_BASE64"]))
    return service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            credentials=_load_sa_credentials(),
        )
    return _client


def _build_context(results: list) -> str:
    blocks = []
    for i, point in enumerate(results, 1):
        p = point.payload
        header = f"[Trecho {i} — Cap. {p.get('capitulo_num', '?')} {p.get('capitulo_text', '?')}, Sec. {p.get('secao_num', '?')} {p.get('secao_text', '?')}]"
        blocks.append(f"{header}\n{p.get('text', '')}")
    return "\n\n".join(blocks)


def generate_answer(query: str, results: list) -> str:
    context = _build_context(results)
    prompt = f"{SYSTEM_PROMPT}\n\nCONTEXTO:\n{context}\n\nPERGUNTA: {query}"

    response = _get_client().models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    return response.text

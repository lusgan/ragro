"""
client.py
---------
Único ponto de contato do sistema com o Vertex AI. Antes esse código vivia
espalhado em `rag/answer.py`; concentrar aqui é o que permite os agentes
(orquestrador, Q&A, conselheiro) substituírem `gerar_texto`/`gerar_json` por
dublês nos testes, sem precisar de rede, projeto GCP ou service account — o
resto do sistema nunca importa `google.genai` diretamente.

Os dois modelos refletem os dois papéis descritos em
`docs/arquitetura-agentes.md`: o `flash` é usado onde o LLM só entende ou
conduz (roteamento, extração de slots, condução do questionário), e o `pro`
é reservado para a redação final, que é o único texto que o usuário lê.
"""

import base64
import json
import logging
import os

from google import genai
from google.genai import types
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

MODELO_RAPIDO = "gemini-2.5-flash"      # roteamento, extração, condução
MODELO_PRINCIPAL = "gemini-2.5-pro"     # redação da resposta final

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


def disponivel() -> bool:
    """True quando há credenciais suficientes para falar com o Vertex.

    Usada pelo frontend (`frontend/views/chat.py`) para cair no modo
    degradado — busca sem geração — quando `GOOGLE_CLOUD_PROJECT` /
    `GCLOUD_SA_BASE64` não estão configurados, já que todo agente chama o LLM
    e não pode rodar sem isso.
    """
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT") and os.environ.get("GCLOUD_SA_BASE64"))


def gerar_texto(prompt: str, *, modelo: str = MODELO_PRINCIPAL) -> str:
    """Geração de texto livre — usada na redação final e na condensação de
    pergunta de acompanhamento."""
    response = _get_client().models.generate_content(
        model=modelo,
        contents=prompt,
    )
    return response.text


def gerar_json(prompt: str, *, schema: dict, modelo: str = MODELO_RAPIDO) -> dict | None:
    """Geração com saída JSON estruturada (roteamento, extração de slots).

    Devolve `None` — nunca levanta — em qualquer falha: chamada de rede,
    resposta vazia, JSON malformado fora do schema. Quem chama decide o
    fallback (ex.: orquestrador cai para `qa` se o classificador falhar); o
    sistema nunca pode travar porque um classificador ficou indisponível.
    """
    try:
        response = _get_client().models.generate_content(
            model=modelo,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as e:  # falha de rede, auth, quota etc.
        logger.warning("gerar_json: chamada ao Vertex falhou: %s", e)
        return None

    texto = response.text
    if not texto:
        logger.warning("gerar_json: resposta vazia do modelo %s", modelo)
        return None

    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        logger.warning("gerar_json: resposta não é JSON válido: %s", e)
        return None

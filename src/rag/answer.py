import logging

from src.llm import client as llm_client
from src.llm.client import MODELO_PRINCIPAL as MODEL_NAME
from src.llm.client import MODELO_RAPIDO as CONDENSE_MODEL_NAME

logger = logging.getLogger(__name__)

# Quantas mensagens (não turnos) do histórico entram no prompt — limita o
# crescimento de tokens em conversas longas.
MAX_HISTORY_MESSAGES = 6

SYSTEM_PROMPT = (
    "Você é um assistente especializado no Manual de Crédito Rural (MCR). "
    "Responda à pergunta do usuário usando exclusivamente as informações "
    "presentes no CONTEXTO abaixo, extraído do manual. Se houver HISTÓRICO "
    "DA CONVERSA, use-o apenas para entender o contexto da pergunta atual — "
    "a resposta em si deve se basear somente no CONTEXTO fornecido. "
    "Se o contexto não for suficiente para responder, diga isso claramente — "
    "não invente informação. Cite o capítulo e a seção de onde tirou cada "
    "afirmação relevante."
)

CONDENSE_PROMPT = (
    "Dado o HISTÓRICO da conversa abaixo e a PERGUNTA DE ACOMPANHAMENTO do "
    "usuário, reescreva a pergunta de acompanhamento como uma pergunta "
    "independente (standalone), que faça sentido sozinha, sem precisar do "
    "histórico. Mantenha o idioma original da pergunta. Se a pergunta de "
    "acompanhamento já for independente, devolva-a sem alterações. Responda "
    "apenas com a pergunta reescrita, sem explicações, aspas ou prefixos."
)


def _build_context(results: list) -> str:
    blocks = []
    for i, point in enumerate(results, 1):
        p = point.payload
        secao  = p.get('secao_label') or p.get('secao_num', '?')
        header = f"[Trecho {i} — Cap. {p.get('capitulo_num', '?')} {p.get('capitulo_text', '?')}, Sec. {secao} {p.get('secao_text', '?')}]"
        blocks.append(f"{header}\n{p.get('text', '')}")
    return "\n\n".join(blocks)


def _format_history(history: list[dict]) -> str:
    speaker = {"user": "Usuário", "assistant": "Assistente"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in history)


def condense_query(history: list[dict], question: str) -> str:
    """Reescreve `question` como pergunta standalone, incorporando o `history`
    da conversa. Sem histórico, não há o que condensar — devolve a pergunta
    original sem gastar uma chamada de LLM.
    """
    if not history:
        return question

    prompt = (
        f"{CONDENSE_PROMPT}\n\n"
        f"HISTÓRICO:\n{_format_history(history[-MAX_HISTORY_MESSAGES:])}\n\n"
        f"PERGUNTA DE ACOMPANHAMENTO: {question}\n\n"
        "PERGUNTA INDEPENDENTE:"
    )
    response = llm_client.gerar_texto(prompt, modelo=CONDENSE_MODEL_NAME)
    condensed = (response or "").strip().strip('"')
    return condensed or question


def generate_answer(query: str, results: list, history: list[dict] | None = None) -> str:
    context = _build_context(results)

    history_block = ""
    if history:
        history_block = (
            f"HISTÓRICO DA CONVERSA:\n{_format_history(history[-MAX_HISTORY_MESSAGES:])}\n\n"
        )

    prompt = f"{SYSTEM_PROMPT}\n\n{history_block}CONTEXTO:\n{context}\n\nPERGUNTA: {query}"

    return llm_client.gerar_texto(prompt, modelo=MODEL_NAME)

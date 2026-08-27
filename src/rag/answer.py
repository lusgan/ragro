import json
import logging

from src.llm import client as llm_client
from src.llm.client import MODELO_PRINCIPAL as MODEL_NAME
from src.programs.base import Recomendacao

from . import rewriter

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

# Gancho de handoff para o Agente Conselheiro (ver docs/arquitetura-agentes.md):
# um convite concreto, não um "mais alguma coisa?" genérico, para o usuário
# descrever a própria situação — é isso que dá ao conselheiro o que precisa
# para triar o programa certo.
CTA_INSTRUCTION = (
    "Ao final da resposta, inclua um convite concreto para o usuário contar a "
    "própria situação — faixa de renda, o que produz (ou pretende produzir) e "
    "região — para que o sistema possa indicar qual linha de crédito rural se "
    "encaixa para ele. Não use um convite genérico como 'posso ajudar em mais "
    "alguma coisa?': o convite precisa pedir especificamente esses dados."
)

# `gerar_recomendacao` redige a explicação final do Agente Conselheiro — a
# regra fundamental do projeto (docs/arquitetura-agentes.md) é que nenhum
# número de crédito sai do LLM. Os TRECHOS DO MCR entram só para fundamentar
# a citação de capítulo/seção, nunca como fonte de valor numérico.
RECOMENDACAO_PROMPT = (
    "Você redige a recomendação final de crédito rural para o usuário, a "
    "partir de uma decisão já tomada por um motor determinístico — você não "
    "decide elegibilidade nem calcula nada. Regra absoluta: todo número — "
    "limite, juros, prazo, carência, bônus de adimplência — e todo nome de "
    "banco sai copiado literalmente do bloco LINHAS abaixo. Não calcule, não "
    "arredonde, não converta e não infira nenhum valor a partir de outro. Os "
    "TRECHOS DO MCR servem só para citar, com capítulo e seção, a regra que "
    "ampara a linha — nunca para tirar um número deles.\n\n"
    "Se LINHAS estiver vazio, não existe tabela offline para este programa: "
    "diga isso, e só cite limite, juros, prazo ou carência se estiverem "
    "explícitos nos TRECHOS DO MCR, sempre com capítulo e seção. Qualquer "
    "valor que não esteja em LINHAS, nem (quando LINHAS estiver vazio) "
    "explícito nos TRECHOS, deve ser declarado como não encontrado — nunca "
    "estimado."
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
    da conversa.

    Delega a `rewriter.reescrever` — a condensação passou a viver num só
    lugar, que também infere o filtro de metadados. Mantida por compatibilidade:
    `frontend/app.py` ainda importa esta função; uma fase posterior a remove.
    """
    return rewriter.reescrever(question, history).consulta


def generate_answer(query: str, results: list, history: list[dict] | None = None) -> str:
    """Mantida por compatibilidade — `frontend/app.py` ainda importa esta
    função; uma fase posterior a remove. Equivale a `gerar_resposta(...,
    com_cta=False)`.
    """
    return gerar_resposta(query, results, history, com_cta=False)


def gerar_resposta(
    pergunta: str,
    trechos: list,
    historico: list[dict] | None = None,
    *,
    com_cta: bool = False,
) -> str:
    """Resposta do Agente Q&A a partir dos `trechos` recuperados.

    Com `com_cta=True`, fecha a resposta com o convite de handoff para o
    Agente Conselheiro (ver `CTA_INSTRUCTION`) — usado quando o assunto da
    pergunta tem a ver com linha de crédito, decisão que cabe a quem chama.
    """
    context = _build_context(trechos)

    history_block = ""
    if historico:
        history_block = (
            f"HISTÓRICO DA CONVERSA:\n{_format_history(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
        )

    instrucoes = f"{SYSTEM_PROMPT}\n\n{CTA_INSTRUCTION}\n\n" if com_cta else f"{SYSTEM_PROMPT}\n\n"
    prompt = f"{instrucoes}{history_block}CONTEXTO:\n{context}\n\nPERGUNTA: {pergunta}"

    return llm_client.gerar_texto(prompt, modelo=MODEL_NAME)


def gerar_recomendacao(
    recomendacao: Recomendacao,
    trechos: list,
    historico: list[dict] | None = None,
) -> str:
    """Redige a recomendação final do Agente Conselheiro a partir de uma
    `Recomendacao` já resolvida por `programa.recomendar(...)` mais os
    trechos do MCR que a fundamentam.

    Todo número (limite, juros, prazo, carência, bônus, bancos) precisa vir
    de `recomendacao.linhas` — os `trechos` são citação, não fonte de valor.
    Ver `RECOMENDACAO_PROMPT` para a regra completa, inclusive o caso PRONAMP
    (`linhas` vazio).
    """
    linhas_bloco = (
        json.dumps(recomendacao.linhas, ensure_ascii=False, indent=2)
        if recomendacao.linhas
        else "(vazio — não existe tabela offline para este programa)"
    )
    contexto = _build_context(trechos)

    history_block = ""
    if historico:
        history_block = (
            f"HISTÓRICO DA CONVERSA:\n{_format_history(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
        )

    observacao_bloco = f"OBSERVAÇÃO: {recomendacao.observacao}\n" if recomendacao.observacao else ""

    prompt = (
        f"{RECOMENDACAO_PROMPT}\n\n"
        f"{history_block}"
        f"PROGRAMA: {recomendacao.programa}\n"
        f"PERFIL AVALIADO: {json.dumps(recomendacao.perfil, ensure_ascii=False)}\n"
        f"FONTE: {recomendacao.fonte}\n"
        f"{observacao_bloco}\n"
        f"LINHAS (fonte exclusiva de números — copie literalmente):\n{linhas_bloco}\n\n"
        f"TRECHOS DO MCR (só para citar capítulo/seção, nunca para tirar número):\n{contexto}\n\n"
        "Redija a recomendação final para o usuário."
    )

    return llm_client.gerar_texto(prompt, modelo=MODEL_NAME)

"""Orquestrador — decide, a cada turno, se quem responde é o Agente Q&A ou o
Agente Conselheiro.

Duas divergências em relação ao diagrama (`docs/arquitetura-agentes.md`):

1. **Roteamento é sticky.** Com uma sessão do conselheiro aberta (`fase` em
   `triagem`/`coleta`), a rota é `conselheiro` por padrão — sem essa regra,
   uma resposta de slot como "uns 80 mil por ano" não parece pedido de
   aconselhamento e vazaria para o Q&A no meio do questionário. O LLM só é
   consultado para detectar **mudança de assunto**, e só uma resposta clara
   muda a rota; qualquer outra coisa (incluindo falha do classificador)
   mantém a sessão.
2. **Falha do classificador cai para `qa`.** O Q&A é o fluxo que já existe e
   sempre responde alguma coisa; uma indisponibilidade do classificador não
   pode derrubar a conversa.

O orquestrador só decide a rota — suspender ou retomar a sessão do
conselheiro é responsabilidade de `advisor.py`. Por isso `rotear` nunca
levanta e nunca mexe em `estado`.
"""

from __future__ import annotations

from src.agents.types import Rota
from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

MAX_HISTORY_MESSAGES = 6

# --- classificação sem sessão aberta -----------------------------------

CLASSIFICADOR_PROMPT = (
    "Você decide qual agente deve responder a uma pergunta sobre crédito rural.\n\n"
    "- 'qa': a pessoa pergunta sobre regras, condições, definições ou qualquer "
    "informação factual do Manual de Crédito Rural (MCR).\n"
    "- 'conselheiro': a pessoa quer saber qual linha de crédito serve para ela, "
    "pede uma recomendação, ou começa a descrever a própria situação (renda, "
    "atividade, perfil) para obter uma indicação.\n\n"
    "Responda em JSON com o campo 'agente' contendo exatamente 'qa' ou "
    "'conselheiro'."
)

CLASSIFICADOR_SCHEMA = {
    "type": "object",
    "properties": {"agente": {"type": "string", "enum": ["qa", "conselheiro"]}},
    "required": ["agente"],
}

# --- roteamento sticky (sessão do conselheiro aberta) ------------------

MUDANCA_ASSUNTO_PROMPT = (
    "Uma conversa está no meio de um questionário de recomendação de crédito "
    "rural (o Agente Conselheiro está perguntando renda, perfil, finalidade "
    "etc.). Abaixo está a última pergunta feita ao usuário pelo questionário "
    "(se houver) e a mensagem que ele acabou de enviar.\n\n"
    "Decida: a mensagem do usuário é uma resposta ao questionário (continua o "
    "mesmo assunto, mesmo que pareça só um número, uma palavra ou uma frase "
    "curta) ou uma mudança clara de assunto (uma pergunta nova, sem relação "
    "com o questionário)?\n\n"
    "Só responda 'mudou_assunto': true quando a mudança de assunto for "
    "inequívoca. Na dúvida, responda false — o questionário continua.\n\n"
    "Responda em JSON com o campo 'mudou_assunto' (booleano)."
)

MUDANCA_ASSUNTO_SCHEMA = {
    "type": "object",
    "properties": {"mudou_assunto": {"type": "boolean"}},
    "required": ["mudou_assunto"],
}


def _formatar_historico(historico: list[dict]) -> str:
    speaker = {"user": "Usuário", "assistant": "Assistente"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in historico)


def _rotear_sessao_aberta(pergunta: str, historico: list[dict] | None) -> Rota:
    """Sessão do conselheiro aberta: a rota é `conselheiro` por padrão — só uma
    mudança de assunto clara e confirmada pelo LLM muda isso. `gerar_json`
    devolvendo `None`, ou qualquer valor que não seja `True` explícito para
    'mudou_assunto', é tratado como "continua o questionário": é a leitura
    conservadora que evita vazar uma resposta de slot para o Q&A.
    """
    prompt = f"{MUDANCA_ASSUNTO_PROMPT}\n\n"
    if historico:
        prompt += f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
    prompt += f"MENSAGEM DO USUÁRIO: {pergunta}"

    resultado = llm_client.gerar_json(prompt, schema=MUDANCA_ASSUNTO_SCHEMA, modelo=MODELO_RAPIDO)
    if isinstance(resultado, dict) and resultado.get("mudou_assunto") is True:
        return Rota("qa", motivo="mudança de assunto detectada durante o questionário", fonte="llm")

    return Rota("conselheiro", motivo="sessão de aconselhamento em andamento", fonte="sticky")


def _rotear_sem_sessao(pergunta: str, historico: list[dict] | None) -> Rota:
    """Sem sessão aberta: uma única chamada classifica entre `qa` e
    `conselheiro`. Qualquer falha (`None`) ou valor fora do enum cai para
    `qa`, o fluxo que já existe e sempre responde alguma coisa.
    """
    prompt = f"{CLASSIFICADOR_PROMPT}\n\n"
    if historico:
        prompt += f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
    prompt += f"PERGUNTA: {pergunta}"

    resultado = llm_client.gerar_json(prompt, schema=CLASSIFICADOR_SCHEMA, modelo=MODELO_RAPIDO)
    agente = resultado.get("agente") if isinstance(resultado, dict) else None
    if agente not in ("qa", "conselheiro"):
        return Rota("qa", motivo="classificador indisponível ou resposta inválida", fonte="fallback")

    return Rota(agente, motivo="classificação do LLM", fonte="llm")


def rotear(pergunta: str, historico: list[dict] | None = None, estado: dict | None = None) -> Rota:
    """Decide entre `qa` e `conselheiro` para este turno. Nunca levanta, nunca
    mexe em `estado` — só lê `estado["fase"]` para saber se há sessão aberta.
    """
    if estado and estado.get("fase") in ("triagem", "coleta"):
        return _rotear_sessao_aberta(pergunta, historico)

    return _rotear_sem_sessao(pergunta, historico)

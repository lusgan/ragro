"""Orquestrador — decide, a cada turno, se quem responde é o Agente Q&A ou o
Agente Conselheiro.

Duas divergências em relação ao diagrama (`docs/arquitetura-agentes.md`):

1. **Roteamento é sticky.** Com uma sessão do conselheiro aberta (`fase` em
   `triagem`/`coleta`), a rota é `conselheiro` por padrão — sem essa regra,
   uma resposta de slot como "uns 80 mil por ano" não parece pedido de
   aconselhamento e vazaria para o Q&A no meio do questionário. O LLM só é
   consultado para saber se a mensagem **responde à pergunta pendente**;
   uma pergunta nova ou uma recusa do questionário tira a conversa dele e
   suspende a sessão (`fase = "suspenso"`), que deixa de ser sticky até o
   classificador mandar de volta para o conselheiro. Falha do classificador
   mantém a sessão.
2. **Falha do classificador cai para `qa`.** O Q&A é o fluxo que já existe e
   sempre responde alguma coisa; uma indisponibilidade do classificador não
   pode derrubar a conversa.

O orquestrador só decide a rota — suspender (`advisor.suspender`) e retomar
a sessão é responsabilidade de quem chama e de `advisor.py`; a rota só
sinaliza a suspensão em `Rota.suspender_sessao`. Por isso `rotear` nunca
levanta e nunca mexe em `estado`.
"""

from __future__ import annotations

from src.agents.types import Rota
from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

MAX_HISTORY_MESSAGES = 6

# --- classificação sem sessão aberta -----------------------------------

CLASSIFICADOR_PROMPT = (
    "Você decide qual agente deve responder a uma mensagem sobre crédito rural. "
    "Decida pela intenção da mensagem, não por ela conter números ou dados de "
    "renda.\n\n"
    "- 'qa': a pessoa quer uma resposta direta — regras, condições, "
    "definições, limites, ou se um caso se enquadra num programa. Vale também "
    "para casos hipotéticos ou de terceiros, mesmo com valores concretos "
    "(ex.: 'um produtor com renda de R$ 220 mil pode se enquadrar no "
    "Pronaf?', 'qual o teto de renda do Pronamp?').\n"
    "- 'conselheiro': a pessoa pede que o sistema indique qual linha de "
    "crédito serve para o próprio caso, quer uma recomendação ou simulação "
    "guiada, ou pede para continuar uma simulação interrompida (ex.: 'qual "
    "crédito rural serve para mim?', 'quero simular um financiamento', "
    "'vamos continuar a simulação').\n\n"
    "Na dúvida, responda 'qa'.\n\n"
    "Responda em JSON com o campo 'agente' contendo exatamente 'qa' ou "
    "'conselheiro'."
)

CLASSIFICADOR_SCHEMA = {
    "type": "object",
    "properties": {"agente": {"type": "string", "enum": ["qa", "conselheiro"]}},
    "required": ["agente"],
}

# --- roteamento sticky (sessão do conselheiro aberta) ------------------

SESSAO_ABERTA_PROMPT = (
    "Uma conversa está no meio de um questionário de recomendação de crédito "
    "rural: o assistente fez ao usuário a última pergunta que aparece no "
    "HISTÓRICO (renda, perfil, finalidade etc.). Classifique a mensagem que o "
    "usuário acabou de enviar:\n\n"
    "- 'responde': responde ou tenta responder à pergunta do questionário, "
    "mesmo que seja só um número, uma palavra, uma opção ou uma frase curta "
    "(ex.: 'uns 80 mil por ano', 'sim', 'pessoa física').\n"
    "- 'pergunta': em vez de responder, faz uma pergunta própria — sobre o "
    "mesmo assunto ou outro — esperando uma resposta direta.\n"
    "- 'recusa': não quer continuar o questionário (ex.: 'só quero saber se "
    "pode ou não', 'não quero responder isso', 'pare').\n\n"
    "Responda em JSON com o campo 'tipo' contendo exatamente 'responde', "
    "'pergunta' ou 'recusa'."
)

SESSAO_ABERTA_SCHEMA = {
    "type": "object",
    "properties": {"tipo": {"type": "string", "enum": ["responde", "pergunta", "recusa"]}},
    "required": ["tipo"],
}

def _formatar_historico(historico: list[dict]) -> str:
    speaker = {"user": "Usuário", "assistant": "Assistente"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in historico)


def _rotear_sessao_aberta(pergunta: str, historico: list[dict] | None) -> Rota:
    """Sessão do conselheiro aberta: a rota é `conselheiro` por padrão. Só uma
    classificação explícita de 'pergunta' ou 'recusa' tira a conversa do
    questionário — e aí a sessão é suspensa, senão o turno seguinte voltaria
    a ser sticky e puxaria o usuário de volta. `gerar_json` devolvendo
    `None`, ou um valor fora do enum, é tratado como "continua o
    questionário": é a leitura conservadora que evita vazar uma resposta de
    slot para o Q&A.
    """
    prompt = f"{SESSAO_ABERTA_PROMPT}\n\n"
    if historico:
        prompt += f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
    prompt += f"MENSAGEM DO USUÁRIO: {pergunta}"

    resultado = llm_client.gerar_json(prompt, schema=SESSAO_ABERTA_SCHEMA, modelo=MODELO_RAPIDO)
    tipo = resultado.get("tipo") if isinstance(resultado, dict) else None
    if tipo in ("pergunta", "recusa"):
        return Rota(
            "qa",
            motivo=f"usuário saiu do questionário ({tipo})",
            fonte="llm",
            suspender_sessao=True,
        )

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
    Uma sessão suspensa não é sticky: passa pelo classificador comum, e se
    ele escolher `conselheiro` o `advisor` retoma de onde parou.
    """
    if estado and estado.get("fase") in ("triagem", "coleta"):
        return _rotear_sessao_aberta(pergunta, historico)

    return _rotear_sem_sessao(pergunta, historico)

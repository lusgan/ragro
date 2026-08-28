"""Agente Conselheiro — o centro do fluxo de recomendação de crédito rural.

Conduz triagem, questionário e recomendação em cima do protocolo `Programa`
(`src/programs/base.py`), sem conhecer PRONAF nem PRONAMP diretamente. A
regra fundamental do projeto (ver `docs/arquitetura-agentes.md`) é que nenhum
número de crédito sai do LLM: aqui o LLM só faz três coisas — extrai slots da
fala livre (EXTRAIR), formula a próxima pergunta em PT-BR (CONDUZIR) e redige
a explicação final a partir de uma decisão já tomada pelo engine
(`answer.gerar_recomendacao`). Elegibilidade, limite, juros, prazo e banco
vêm sempre de `programa.recomendar()`.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient

import src.programs as programs
from src.agents.types import Resposta
from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO
from src.programs import triagem
from src.programs.base import Pergunta, RespostasInvalidas, Slot
from src.rag import answer, judge
from src.rag.retriever import SearchMode, buscar_com_fallback
from src.rag.snapshot import snapshot

logger = logging.getLogger(__name__)

# Um esclarecimento por slot é o que garante terminação: o LLM pode desviar
# para uma pergunta de esclarecimento no máximo uma vez por slot antes de ser
# forçado a seguir a pergunta do engine verbatim (ver `_conduzir`).
MAX_ESCLARECIMENTOS_POR_SLOT = 1

# Limite do laço de re-busca em RECOMENDAR — sem progresso (mesma consulta
# extra, ou nenhuma) é tratado como suficiente, então este número é só uma
# rede de segurança contra um judge que nunca se declara satisfeito.
MAX_RODADAS_BUSCA = 3

MAX_HISTORY_MESSAGES = 6

MSG_OUTROS = (
    "Pelo perfil de renda informado, esse caso fica acima dos tetos do PRONAF "
    "e do PRONAMP — não vou montar uma recomendação de linha de crédito aqui. "
    "Mas posso responder perguntas sobre as demais linhas de crédito rural do "
    "Manual de Crédito Rural: é só perguntar."
)

MSG_RESPOSTAS_INVALIDAS = (
    "Não consegui montar a recomendação com as respostas atuais. Pode "
    "confirmar os dados informados?"
)

# --- EXTRAIR -------------------------------------------------------------

EXTRACAO_PROMPT = (
    "Você extrai, da fala do usuário, valores para um questionário de "
    "recomendação de crédito rural. Preencha só os campos sobre os quais o "
    "usuário efetivamente falou nesta mensagem (o HISTÓRICO, se houver, serve "
    "apenas para entender o contexto). Nunca infira ou aproxime um valor que "
    "não esteja claramente dito — deixe de fora qualquer campo incerto.\n\n"
)


def _formatar_historico(historico: list[dict]) -> str:
    speaker = {"user": "Usuário", "assistant": "Assistente"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in historico)


def _slots_do_turno(estado: dict) -> dict[str, Slot]:
    """Campos que a extração deste turno pode preencher: os da triagem
    enquanto ela não resolveu o programa, os do programa depois disso.

    Vem do próprio questionário (`Programa.slots()` / `triagem.slots()`), que
    deriva do ruleset. Descobrir isso percorrendo a árvore de perguntas seria
    reconstruir por força bruta um dado que a fonte já declara — e amarraria
    o conselheiro ao formato da árvore de cada programa.
    """
    if estado["fase"] == "triagem":
        return triagem.slots()
    return programs.obter(estado["programa"]).slots()


def _schema_extracao(slots: dict[str, Slot]) -> dict:
    propriedades = {}
    for nome, slot in slots.items():
        if not slot.valores:
            continue
        if slot.multipla:
            propriedades[nome] = {
                "type": "array",
                "items": {"type": "string", "enum": slot.valores},
            }
        else:
            propriedades[nome] = {"type": "string", "enum": slot.valores}
    return {"type": "object", "properties": propriedades}


def _validar_extracao(resultado: dict, slots: dict[str, Slot]) -> dict[str, Any]:
    """Descarta qualquer valor fora do vocabulário — o enum do schema é um
    palpite do LLM, não uma garantia, e um valor aproximado é pior do que uma
    pergunta refeita."""
    validos: dict[str, Any] = {}
    for nome, slot in slots.items():
        if nome not in resultado:
            continue
        permitidos = set(slot.valores)
        valor = resultado[nome]
        if isinstance(valor, list):
            lista = [v for v in valor if isinstance(v, str) and v in permitidos]
            if lista:
                validos[nome] = lista
        elif isinstance(valor, str) and valor in permitidos:
            validos[nome] = valor
    return validos


def _extrair(
    pergunta_usuario: str,
    historico: list[dict] | None,
    slots: dict[str, Slot],
) -> dict[str, Any]:
    schema = _schema_extracao(slots)
    if not schema["properties"]:
        return {}

    prompt = EXTRACAO_PROMPT
    if historico:
        prompt += f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
    prompt += f"MENSAGEM DO USUÁRIO: {pergunta_usuario}"

    resultado = llm_client.gerar_json(prompt, schema=schema, modelo=MODELO_RAPIDO)
    if not isinstance(resultado, dict):
        return {}
    return _validar_extracao(resultado, slots)


# --- CONDUZIR --------------------------------------------------------------

CONDUCAO_PROMPT = (
    "Você conduz, em português natural, o questionário de recomendação de "
    "crédito rural em nome de um motor determinístico: ele já decidiu que a "
    "próxima pergunta necessária é a PERGUNTA DO ENGINE abaixo. Você não pode "
    "pular, reordenar ou responder por ela — só formular como ela chega ao "
    "usuário.\n\n"
    "Escolha uma de duas ações:\n"
    "- 'seguir': reformule a PERGUNTA DO ENGINE em português natural, "
    "oferecendo as OPÇÕES para o usuário escolher.\n"
    "- 'esclarecer': se antes de perguntar valer a pena esclarecer algo (ex.: "
    "um termo pouco óbvio), faça essa pergunta de esclarecimento em vez de "
    "repetir a pergunta do engine agora — ela continua pendente e será feita "
    "no próximo turno.\n\n"
    "Responda em JSON com 'acao' ('seguir' ou 'esclarecer') e 'texto' (o que "
    "mostrar ao usuário)."
)

CONDUCAO_SCHEMA = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": ["seguir", "esclarecer"]},
        "texto": {"type": "string"},
    },
    "required": ["acao", "texto"],
}


def _formatar_opcoes(pergunta: Pergunta) -> str:
    return "; ".join(f"{o.v}: {o.t}" for o in pergunta.opcoes)


def _prompt_conducao(pergunta: Pergunta, historico: list[dict] | None) -> str:
    prompt = CONDUCAO_PROMPT + "\n\n"
    if historico:
        prompt += f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
    prompt += (
        f"PERGUNTA DO ENGINE: {pergunta.texto}\n"
        f"OPÇÕES: {_formatar_opcoes(pergunta)}\n"
        f"MÚLTIPLA ESCOLHA: {'sim' if pergunta.multipla else 'não'}"
    )
    return prompt


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conduzir(pergunta: Pergunta, estado: dict, historico: list[dict] | None) -> Resposta:
    estado["slot_pendente"] = pergunta.id
    estado["atualizado_em"] = _agora_iso()
    tentativas = estado["esclarecimentos"].get(pergunta.id, 0)

    if tentativas >= MAX_ESCLARECIMENTOS_POR_SLOT:
        # Esclarecimento esgotado para este slot: nem chama o LLM — força
        # 'seguir' com o texto literal do engine. É isto que garante
        # terminação: o LLM pode desviar para 'esclarecer' no máximo uma vez
        # por slot; esgotado o limite, o turno seguinte é sempre uma pergunta
        # direta, então o questionário nunca fica girando em torno do mesmo
        # slot para sempre.
        estado["opcoes_visiveis"] = True
        return Resposta(
            texto=pergunta.texto, agente="conselheiro", trechos=[], estado=estado, pergunta=pergunta
        )

    resultado = llm_client.gerar_json(
        _prompt_conducao(pergunta, historico), schema=CONDUCAO_SCHEMA, modelo=MODELO_RAPIDO
    )

    if isinstance(resultado, dict):
        acao = resultado.get("acao")
        texto = (resultado.get("texto") or "").strip()
        if acao == "esclarecer" and texto:
            estado["esclarecimentos"][pergunta.id] = tentativas + 1
            # As opções do engine são respostas para a pergunta que o motor
            # ia fazer, não para este esclarecimento — não podem aparecer
            # como chips agora (ver `pergunta_pendente`).
            estado["opcoes_visiveis"] = False
            return Resposta(
                texto=texto, agente="conselheiro", trechos=[], estado=estado, pergunta=pergunta
            )
        if acao == "seguir" and texto:
            estado["opcoes_visiveis"] = True
            return Resposta(
                texto=texto, agente="conselheiro", trechos=[], estado=estado, pergunta=pergunta
            )

    # `gerar_json` falhou (None), ou devolveu ação/texto que não reconhecemos:
    # a mesma rede de segurança do limite de esclarecimentos acima — nunca
    # trava o turno, nunca pula o slot pendente. O texto mostrado é o do
    # engine, então as opções dele são válidas como chips.
    estado["opcoes_visiveis"] = True
    return Resposta(
        texto=pergunta.texto, agente="conselheiro", trechos=[], estado=estado, pergunta=pergunta
    )


# --- RECOMENDAR --------------------------------------------------------------


def _dedup_por_id(acumulados: list, novos: list) -> list:
    vistos = {ponto.id for ponto in acumulados}
    saida = list(acumulados)
    for ponto in novos:
        if ponto.id not in vistos:
            vistos.add(ponto.id)
            saida.append(ponto)
    return saida


def _recomendar(
    estado: dict,
    historico: list[dict] | None,
    client: QdrantClient,
    bm25_model,
    mode: SearchMode,
) -> Resposta:
    programa = programs.obter(estado["programa"])

    try:
        rec = programa.recomendar(estado["respostas"])
    except RespostasInvalidas as e:
        # Não esperado neste ponto — o engine já disse, via `proxima_pergunta`,
        # que nenhum slot falta — mas se acontecer o turno não pode travar nem
        # inventar recomendação: registra e volta a perguntar.
        logger.warning("advisor: recomendar() recusou as respostas: %s", e)
        estado["atualizado_em"] = _agora_iso()
        pergunta_pendente = programa.proxima_pergunta(estado["respostas"])
        if pergunta_pendente is not None:
            return _conduzir(pergunta_pendente, estado, historico)
        return Resposta(
            texto=MSG_RESPOSTAS_INVALIDAS,
            agente="conselheiro",
            trechos=[],
            estado=estado,
            pergunta=None,
        )

    acumulados: list = []
    consulta = rec.consulta_rag

    # MAX_RODADAS_BUSCA > 0 sempre, então o laço roda ao menos uma vez e
    # `julgamento` sai sempre atribuído antes de ser usado abaixo.
    for _ in range(MAX_RODADAS_BUSCA):
        novos, _ = buscar_com_fallback(consulta, client, bm25_model, mode=mode, secoes=rec.secoes_mcr)
        acumulados = _dedup_por_id(acumulados, novos)
        julgamento = judge.avaliar(consulta, acumulados)
        if julgamento.suficiente or not julgamento.consulta_extra or julgamento.consulta_extra == consulta:
            break  # sem progresso é o mesmo que suficiente
        consulta = julgamento.consulta_extra

    # Mesma guarda de `qa.py`: um judge rigoroso demais que zere os relevantes
    # não pode deixar `gerar_recomendacao` sem contexto nenhum.
    relevantes = (
        [acumulados[i] for i in julgamento.relevantes] if julgamento.relevantes else acumulados
    )

    texto = answer.gerar_recomendacao(rec, relevantes, historico)

    estado["fase"] = "concluido"
    estado["slot_pendente"] = None
    estado["atualizado_em"] = _agora_iso()

    return Resposta(
        texto=texto,
        agente="conselheiro",
        trechos=snapshot(relevantes),
        estado=estado,
        pergunta=None,
    )


# --- estado ------------------------------------------------------------


def _estado_inicial() -> dict:
    return {
        "fase": "triagem",
        "programa": None,
        "triagem": {},
        "respostas": {},
        "slot_pendente": None,
        "esclarecimentos": {},
        "opcoes_visiveis": False,
        "atualizado_em": _agora_iso(),
    }


def _copiar_estado(estado: dict) -> dict:
    return copy.deepcopy(estado)


def pergunta_pendente(estado: dict | None) -> Pergunta | None:
    """Recomputa a pergunta pendente do engine a partir de um `estado`
    persistido, para o frontend re-renderizar as opções de resposta depois de
    um rerun ou reload de página — sem guardar uma cópia à parte em
    `st.session_state`, já que o Postgres é a única fonte da verdade.

    Devolve `None` fora das fases `triagem`/`coleta`, e também quando o
    último turno foi de esclarecimento (`opcoes_visiveis=False`, marcado por
    `_conduzir`): mostrar os chips do engine sob uma pergunta de
    esclarecimento ofereceria respostas para uma pergunta que não foi a que
    acabou de ser feita.
    """
    if not estado or estado.get("fase") not in ("triagem", "coleta"):
        return None
    if not estado.get("opcoes_visiveis"):
        return None

    if estado["fase"] == "triagem":
        return triagem.proxima_pergunta(estado["triagem"])
    return programs.obter(estado["programa"]).proxima_pergunta(estado["respostas"])


# --- turno ---------------------------------------------------------------


def responder(
    pergunta: str,
    historico: list[dict] | None,
    estado: dict | None,
    client: QdrantClient,
    bm25_model,
    *,
    mode: SearchMode = SearchMode.HYBRID,
) -> Resposta:
    """Conduz um turno do Agente Conselheiro. Nunca mexe em `estado` — o novo
    estado sai só em `Resposta.estado`; quem chama decide se persiste."""
    estado_atual = _copiar_estado(estado) if estado else _estado_inicial()

    if estado_atual["fase"] == "concluido":
        # Retomar uma sessão terminada começa uma coleta nova, mas a renda
        # (via `triagem`) e o programa já resolvido não mudam de uma pergunta
        # para outra — refazer a triagem inteira pareceria um chatbot quebrado.
        estado_atual["respostas"] = {}
        estado_atual["slot_pendente"] = None
        estado_atual["esclarecimentos"] = {}
        estado_atual["fase"] = "coleta"

    # 1. EXTRAIR — cobre todo o vocabulário do turno atual de uma vez.
    extraido = _extrair(pergunta, historico, _slots_do_turno(estado_atual))
    alvo = estado_atual["triagem"] if estado_atual["fase"] == "triagem" else estado_atual["respostas"]
    alvo.update(extraido)

    # 2. TRIAGEM
    if estado_atual["fase"] == "triagem":
        resolvido = triagem.resolver(estado_atual["triagem"])

        if resolvido is None:
            pergunta_triagem = triagem.proxima_pergunta(estado_atual["triagem"])
            assert pergunta_triagem is not None, "resolver() incompleto implica proxima_pergunta() pendente"
            return _conduzir(pergunta_triagem, estado_atual, historico)

        if resolvido == "outros":
            estado_atual["fase"] = "concluido"
            estado_atual["programa"] = "outros"
            estado_atual["slot_pendente"] = None
            estado_atual["atualizado_em"] = _agora_iso()
            return Resposta(
                texto=MSG_OUTROS, agente="conselheiro", trechos=[], estado=estado_atual, pergunta=None
            )

        estado_atual["programa"] = resolvido
        estado_atual["fase"] = "coleta"
        if resolvido == "pronaf":
            # A renda da triagem é literalmente a mesma pergunta do ruleset do
            # PRONAF — reaproveitar evita perguntá-la de novo, o que seria um
            # bug visível para quem está respondendo.
            estado_atual["respostas"].setdefault("renda", estado_atual["triagem"]["renda"])
        # PRONAMP não seeda nada: seu vocabulário (atividade/finalidade/regiao)
        # não tem sobreposição com o vocabulário de renda da triagem.

    # 3. ENGINE — só o engine decide qual slot falta.
    programa = programs.obter(estado_atual["programa"])
    pergunta_pendente = programa.proxima_pergunta(estado_atual["respostas"])

    # 4a. CONDUZIR
    if pergunta_pendente is not None:
        return _conduzir(pergunta_pendente, estado_atual, historico)

    # 4b. RECOMENDAR
    return _recomendar(estado_atual, historico, client, bm25_model, mode)

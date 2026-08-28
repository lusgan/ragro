"""Reescrita da pergunta antes da busca — o primeiro passo do Agente Q&A.

Uma única chamada `gerar_json` (MODELO_RAPIDO) faz duas coisas de uma vez:
condensa a pergunta de acompanhamento numa pergunta standalone e infere um
filtro de seções do MCR quando o assunto é identificável (ex.: "PRONAF" →
capítulo 10).

O filtro é sempre um palpite, nunca uma certeza — por isso o schema pede uma
lista vazia quando o modelo não tem segurança sobre o capítulo, e por isso
`retriever.buscar_com_fallback` descarta o filtro se ele zerar a busca. Um
capítulo errado aqui custa recall; deixar o modelo "chutar" com confiança
custaria corretude.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

from .capitulos import CAPITULOS

MAX_HISTORY_MESSAGES = 6

REWRITE_PROMPT = (
    "Você prepara uma pergunta sobre o Manual de Crédito Rural (MCR) para uma "
    "busca híbrida (dense + BM25). Faça duas coisas:\n\n"
    "1. CONSULTA: se houver HISTÓRICO, reescreva a PERGUNTA como uma pergunta "
    "standalone, que faça sentido sozinha, sem precisar do histórico. Mantenha "
    "o idioma original. Se a pergunta já for independente, ou não houver "
    "histórico, devolva-a sem alterações.\n\n"
    "2. SEÇÕES: se o assunto apontar claramente para um ou mais capítulos do "
    "índice abaixo, devolva-os para estreitar a busca. Se não houver certeza "
    "razoável sobre qual capítulo, devolva uma lista vazia — um palpite errado "
    "aqui é pior do que não filtrar nada, porque pode esconder o trecho certo.\n\n"
    f"ÍNDICE DE CAPÍTULOS DO MCR:\n{CAPITULOS}\n\n"
)

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "consulta": {"type": "string"},
        "secoes_mcr": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capitulo_num": {"type": "integer"},
                    "secao_label": {"type": "string"},
                },
            },
        },
    },
    "required": ["consulta", "secoes_mcr"],
}


@dataclass(frozen=True)
class Reescrita:
    """Saída de `reescrever` — pronta para `retriever.buscar_com_fallback`."""

    consulta: str          # pergunta standalone
    secoes_mcr: list[dict]  # filtro inferido; [] quando não dá para inferir


def _formatar_historico(historico: list[dict]) -> str:
    speaker = {"user": "Usuário", "assistant": "Assistente"}
    return "\n".join(f"{speaker.get(m['role'], m['role'])}: {m['content']}" for m in historico)


# Formato de `secao_label` no payload: o número da seção, com sublabel quando
# existe — "1", "18", "4-A". O prompt acima pede capítulos e nunca explica este
# campo, mas o schema o expõe como string livre; sem esta checagem o modelo o
# preenche com o nome do capítulo (o `capitulo_text` do payload, literalmente),
# e aí o filtro pede "capítulo 10 E seção chamada 'Pronaf'", casa com zero e é
# descartado inteiro — inclusive a parte do capítulo, que estava certa.
_FORMATO_SECAO_LABEL = re.compile(r"^\d+(?:-[A-Za-z0-9]+)?$")


def _secoes_validas(secoes: list) -> list[dict]:
    """Normaliza o filtro inferido antes de ele virar `Filter` do Qdrant.

    Duas regras, com destinos diferentes de propósito:

    - capítulo fora do índice conhecido -> a entrada inteira cai, porque sem
      capítulo válido não sobra nada que estreite a busca;
    - `secao_label` fora do formato -> cai só a chave, e o capítulo sobrevive.
      Filtrar por capítulo é o que o prompt de fato pede, e degradar para isso
      é melhor do que perder o filtro todo por causa de um campo que o modelo
      não tinha como preencher.

    Um label bem formado mas inexistente ("99") passa por aqui e zera a busca —
    e é `retriever.buscar_com_fallback` quem cobre isso, como cobre qualquer
    outro palpite errado. A checagem aqui é de formato, não de existência: o
    corpus é a única fonte sobre quais seções existem, e replicá-la num índice
    estático seria criar uma segunda verdade que envelhece a cada reindexação.
    """
    validas = []
    for secao in secoes or []:
        if not isinstance(secao, dict):
            continue

        capitulo = secao.get("capitulo_num")
        if capitulo is not None and capitulo not in CAPITULOS:
            continue

        label = secao.get("secao_label")
        if label is not None and not _FORMATO_SECAO_LABEL.match(str(label)):
            secao = {k: v for k, v in secao.items() if k != "secao_label"}

        if not secao:
            continue
        validas.append(secao)
    return validas


def reescrever(pergunta: str, historico: list[dict] | None = None) -> Reescrita:
    """Condensa `pergunta` (usando `historico`, se houver) e infere um filtro
    de seções do MCR. Nunca levanta — qualquer falha do LLM cai para a
    pergunta original sem filtro, o que é sempre uma busca válida, só que sem
    a otimização de recall."""
    if not historico:
        # Sem histórico não há o que condensar. Ainda vale inferir o filtro,
        # mas só se houver pergunta — o caller sempre passa uma.
        prompt = (
            f"{REWRITE_PROMPT}"
            f"PERGUNTA: {pergunta}\n\n"
            "Responda em JSON com os campos 'consulta' (igual à pergunta, "
            "salvo erro de digitação) e 'secoes_mcr'."
        )
    else:
        prompt = (
            f"{REWRITE_PROMPT}"
            f"HISTÓRICO:\n{_formatar_historico(historico[-MAX_HISTORY_MESSAGES:])}\n\n"
            f"PERGUNTA DE ACOMPANHAMENTO: {pergunta}\n\n"
            "Responda em JSON com os campos 'consulta' (a pergunta standalone) "
            "e 'secoes_mcr'."
        )

    resultado = llm_client.gerar_json(prompt, schema=REWRITE_SCHEMA, modelo=MODELO_RAPIDO)
    if resultado is None:
        return Reescrita(consulta=pergunta, secoes_mcr=[])

    consulta = (resultado.get("consulta") or "").strip() or pergunta
    secoes = _secoes_validas(resultado.get("secoes_mcr") or [])
    return Reescrita(consulta=consulta, secoes_mcr=secoes)

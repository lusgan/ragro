"""LLM-as-a-judge sobre os trechos recuperados — o passo antes da geração.

A busca híbrida otimiza recall, não precisão: ela sempre devolve `TOP_K`
trechos, relevantes ou não. Este módulo faz uma chamada `gerar_json`
(MODELO_RAPIDO) que classifica cada trecho como sustentando ou não a
resposta, e opcionalmente sugere uma nova consulta quando os trechos
relevantes não bastam.

Um juiz indisponível nunca pode reduzir o que o usuário recebe: se
`gerar_json` falhar, a decisão segura é manter todos os trechos e seguir
direto para a geração, como se o julgamento nunca tivesse acontecido.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

# Cap por trecho: uma seção longa do MCR não pode, sozinha, estourar o prompt
# do juiz — o julgamento não precisa do texto inteiro, só o bastante para
# decidir relevância.
MAX_CHARS_POR_TRECHO = 1200

JUDGE_PROMPT = (
    "Você avalia se os trechos abaixo, extraídos do Manual de Crédito Rural "
    "(MCR), bastam para responder à PERGUNTA. Devolva em JSON:\n"
    "- 'relevantes': os índices (começando em 0) dos trechos que efetivamente "
    "sustentam uma resposta à pergunta. Descarte trechos que só tangenciam o "
    "assunto.\n"
    "- 'suficiente': true se os trechos relevantes já permitem responder à "
    "pergunta; false se falta informação.\n"
    "- 'consulta_extra': quando 'suficiente' for false, uma nova consulta de "
    "busca que preencha a lacuna; caso contrário, string vazia.\n\n"
)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevantes": {"type": "array", "items": {"type": "integer"}},
        "suficiente": {"type": "boolean"},
        "consulta_extra": {"type": "string"},
    },
    "required": ["relevantes", "suficiente", "consulta_extra"],
}


@dataclass(frozen=True)
class Julgamento:
    """Saída de `avaliar`."""

    relevantes: list[int]       # índices dos trechos que sustentam a resposta
    suficiente: bool            # dá para responder só com esses?
    consulta_extra: str | None  # nova consulta quando não é suficiente


def _cabecalho(payload: dict) -> str:
    secao = payload.get("secao_label") or payload.get("secao_num", "?")
    return (
        f"Cap. {payload.get('capitulo_num', '?')} {payload.get('capitulo_text', '?')}, "
        f"Sec. {secao} {payload.get('secao_text', '?')}"
    )


def _formatar_trechos(trechos: list) -> str:
    blocos = []
    for i, trecho in enumerate(trechos):
        p = trecho.payload
        corpo = (p.get("text") or "")[:MAX_CHARS_POR_TRECHO]
        blocos.append(f"[{i}] {_cabecalho(p)}\n{corpo}")
    return "\n\n".join(blocos)


def _manter_tudo(trechos: list) -> Julgamento:
    return Julgamento(relevantes=list(range(len(trechos))), suficiente=True, consulta_extra=None)


def avaliar(pergunta: str, trechos: list) -> Julgamento:
    """Classifica `trechos` quanto à relevância para `pergunta`.

    Sem trechos não há o que julgar. Se o modelo devolver índices fora do
    intervalo, eles são descartados individualmente — o resto do julgamento,
    se ainda tiver algum índice válido, continua sendo usado; só cai para
    "manter tudo" quando a resposta falha completamente ou não sobra nenhum
    índice utilizável.
    """
    if not trechos:
        return Julgamento(relevantes=[], suficiente=True, consulta_extra=None)

    prompt = f"{JUDGE_PROMPT}PERGUNTA: {pergunta}\n\nTRECHOS:\n{_formatar_trechos(trechos)}"
    resultado = llm_client.gerar_json(prompt, schema=JUDGE_SCHEMA, modelo=MODELO_RAPIDO)
    if resultado is None:
        return _manter_tudo(trechos)

    brutos = resultado.get("relevantes")
    if not isinstance(brutos, list):
        return _manter_tudo(trechos)

    relevantes = [i for i in brutos if isinstance(i, int) and 0 <= i < len(trechos)]
    if not relevantes:
        return _manter_tudo(trechos)

    consulta_extra = (resultado.get("consulta_extra") or "").strip() or None
    return Julgamento(
        relevantes=relevantes,
        suficiente=bool(resultado.get("suficiente", True)),
        consulta_extra=consulta_extra,
    )

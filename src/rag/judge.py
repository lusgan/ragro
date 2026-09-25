"""LLM-as-a-judge sobre os trechos recuperados — o passo antes da geração.

A busca híbrida otimiza recall, não precisão: ela sempre devolve `TOP_K`
trechos, relevantes ou não. Este módulo faz uma chamada `gerar_json`
(MODELO_RAPIDO) que classifica cada trecho como sustentando ou não a
resposta, e opcionalmente sugere uma nova consulta quando os trechos
relevantes não bastam.

Modelo e tamanho do trecho são parâmetros de `avaliar`, com os padrões
escolhidos por medição — ver `MAX_CHARS_POR_TRECHO` abaixo e
`eval/judge_sweep.py`, que reexecuta só o julgamento sobre candidatos já
salvos para comparar configurações sem refazer busca nem geração.

Um juiz indisponível nunca pode reduzir o que o usuário recebe: se
`gerar_json` falhar, a decisão segura é manter todos os trechos e seguir
direto para a geração, como se o julgamento nunca tivesse acontecido.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

# Cap por trecho, medido e não arbitrado (`eval/judge_sweep.py`, rodada 01).
# Uma seção do MCR tem em média 12,6 mil caracteres. Com o cap antigo de 1200
# o juiz decidia relevância vendo ~10% do texto e descartava a seção certa
# quando a resposta estava no meio dela — sobre as mesmas 67 perguntas e os
# mesmos candidatos, passar de 1200 para 20000 levou a precisão do contexto de
# 0,60 para 0,80 e a cobertura de 0,82 para 0,90.
#
# O ganho de precisão vem de o juiz descartar MAIS, não menos: os trechos
# aprovados caem de 2,4 para 1,5 por pergunta. Vendo a seção inteira ele
# reconhece a certa e dispensa as vizinhas plausíveis, em vez de manter todas
# na dúvida.
#
# Trocar o modelo por `gemini-2.5-pro` com o cap antigo rendeu bem menos
# (precisão 0,62), então o juiz continua no MODELO_RAPIDO: a limitação era o
# quanto ele enxergava, não a capacidade de julgar.
MAX_CHARS_POR_TRECHO = 20_000

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


def _formatar_trechos(trechos: list, max_chars: int = MAX_CHARS_POR_TRECHO) -> str:
    blocos = []
    for i, trecho in enumerate(trechos):
        p = trecho.payload
        corpo = (p.get("text") or "")[:max_chars]
        blocos.append(f"[{i}] {_cabecalho(p)}\n{corpo}")
    return "\n\n".join(blocos)


def _manter_tudo(trechos: list) -> Julgamento:
    return Julgamento(relevantes=list(range(len(trechos))), suficiente=True, consulta_extra=None)


def avaliar(
    pergunta: str,
    trechos: list,
    *,
    modelo: str = MODELO_RAPIDO,
    max_chars: int = MAX_CHARS_POR_TRECHO,
) -> Julgamento:
    """Classifica `trechos` quanto à relevância para `pergunta`.

    Sem trechos não há o que julgar. Se o modelo devolver índices fora do
    intervalo, eles são descartados individualmente — o resto do julgamento,
    se ainda tiver algum índice válido, continua sendo usado; só cai para
    "manter tudo" quando a resposta falha completamente ou não sobra nenhum
    índice utilizável.
    """
    if not trechos:
        return Julgamento(relevantes=[], suficiente=True, consulta_extra=None)

    prompt = (
        f"{JUDGE_PROMPT}PERGUNTA: {pergunta}\n\n"
        f"TRECHOS:\n{_formatar_trechos(trechos, max_chars)}"
    )
    resultado = llm_client.gerar_json(prompt, schema=JUDGE_SCHEMA, modelo=modelo)
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

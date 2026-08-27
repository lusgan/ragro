"""Triagem: decide qual programa conduzir, antes de entrar no questionário dele.

Duas perguntas bastam. A primeira é a renda bruta anual, e reaproveita as
próprias faixas do ruleset do PRONAF (lidas em tempo de execução, nunca
copiadas à mão) em vez de manter um segundo vocabulário de renda que
divergiria dele a cada Plano Safra. A segunda — se ao menos metade da renda
vem da atividade agropecuária — só é perguntada quando a renda cai na faixa
"até R$ 3 milhões": o simulador oficial do PRONAF não faz essa pergunta para
as faixas dele, e adicioná-la ali divergiria do fluxo validado.

Os limiares abaixo (R$ 3 milhões e a regra dos 50%) são dado normativo, não
lógica: mudam a cada Plano Safra. Ficam neste único lugar, com `fonte`
preenchida, para serem revalidados de uma vez em vez de espalhados por texto
de pergunta e código.
"""

from __future__ import annotations

from typing import Any

from src.programs.base import Opcao, Pergunta
from src.programs.pronaf import engine

LIMIAR_PRONAMP = {
    "fonte": "Plano Safra 2026/2027 — teto de renda bruta anual do PRONAMP e regra "
    "dos 50% de renda da atividade agropecuária",
    "renda_maxima_reais": 3_000_000,
    "percentual_minimo_atividade": 0.5,
}

# Faixas adicionais às do PRONAF, só para a triagem — não existem no ruleset.
_RENDA_ADICIONAL = [
    {"v": "ate3mi", "l": "De R$ 500 mil a R$ 3 milhões por ano"},
    {"v": "acima3mi", "l": "Acima de R$ 3 milhões por ano"},
]


def _opcoes_renda_pronaf() -> list[dict[str, str]]:
    return [{"v": o["v"], "l": o["l"]} for o in engine.ruleset()["perguntas"]["renda"]["opcoes"]]


def _opcoes_renda() -> list[dict[str, str]]:
    return _opcoes_renda_pronaf() + _RENDA_ADICIONAL


def proxima_pergunta(triagem: dict[str, Any]) -> Pergunta | None:
    """Próxima pergunta de triagem, ou None quando já dá para resolver o programa."""
    opcoes_renda = _opcoes_renda()
    vocab_renda = {o["v"] for o in opcoes_renda}

    renda = triagem.get("renda")
    if renda not in vocab_renda:
        return Pergunta(
            id="renda",
            texto="Qual a renda bruta anual da família ou do empreendimento rural?",
            multipla=False,
            opcoes=[Opcao(v=o["v"], t=o["l"]) for o in opcoes_renda],
        )

    if renda == "ate3mi" and triagem.get("renda_da_atividade") not in ("sim", "nao"):
        return Pergunta(
            id="renda_da_atividade",
            texto="Pelo menos metade da renda vem da atividade agropecuária?",
            multipla=False,
            opcoes=[Opcao(v="sim", t="Sim"), Opcao(v="nao", t="Não")],
        )

    return None


def resolver(triagem: dict[str, Any]) -> str | None:
    """Resolve o programa a partir da triagem, ou None se ela ainda está incompleta."""
    renda_pronaf = {o["v"] for o in _opcoes_renda_pronaf()}
    renda = triagem.get("renda")

    if renda in renda_pronaf:
        return "pronaf"
    if renda == "ate3mi":
        atividade = triagem.get("renda_da_atividade")
        if atividade == "sim":
            return "pronamp"
        if atividade == "nao":
            return "outros"
        return None
    if renda == "acima3mi":
        return "outros"
    return None

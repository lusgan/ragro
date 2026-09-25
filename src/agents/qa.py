"""Agente Q&A — o fluxo de pergunta e resposta sobre o MCR, com as técnicas
descritas em `docs/arquitetura-agentes.md`: reescrita de consulta, busca
híbrida com filtro de metadados, LLM-as-a-judge e call-to-action de handoff
para o Agente Conselheiro.

Sem laço de re-busca aqui — o laço existe só no conselheiro (ver
`advisor.py`), como no diagrama de referência.
"""

from __future__ import annotations

from qdrant_client import QdrantClient

from src.agents.types import Resposta
from src.rag import answer, judge, rewriter
from src.rag.retriever import SearchMode, buscar_com_fallback
from src.rag.snapshot import snapshot

SEM_RESULTADOS = "Nenhum resultado encontrado."


def responder(
    pergunta: str,
    historico: list[dict] | None,
    client: QdrantClient,
    bm25_model,
    *,
    mode: SearchMode = SearchMode.HYBRID,
    trace: dict | None = None,
) -> Resposta:
    """Responde `pergunta` com o fluxo do Agente Q&A. Nunca mexe em
    `advisor_state` — `estado=None` sempre, porque o Q&A não é sessão.

    `trace`, quando passado, é preenchido com os estágios intermediários
    (consulta reescrita, trechos recuperados antes do juiz, índices julgados
    relevantes). Serve à avaliação (`eval/runner.py`), que precisa separar
    falha de recuperação de falha do juiz: `Resposta.trechos` já é o contexto
    pós-juiz, então sozinho ele não diz se um trecho faltou porque a busca não
    o achou ou porque o juiz o descartou. É um dicionário de saída, e não um
    retorno a mais, para não mudar o contrato de `Resposta`, que o frontend e
    o histórico persistem.
    """
    reescrita = rewriter.reescrever(pergunta, historico)
    if trace is not None:
        trace["consulta"] = reescrita.consulta
        trace["secoes_mcr"] = reescrita.secoes_mcr
    # `complementar=True`: o filtro de seção aqui é um palpite do rewriter, não
    # uma certeza — mesmo quando ele acerta o capítulo, pode não ser o único
    # relevante. Ver `retriever.buscar_com_fallback`.
    resultados, _ = buscar_com_fallback(
        reescrita.consulta,
        client,
        bm25_model,
        mode=mode,
        secoes=reescrita.secoes_mcr,
        complementar=True,
    )

    if trace is not None:
        trace["recuperados"] = snapshot(resultados)

    if not resultados:
        return Resposta(texto=SEM_RESULTADOS, agente="qa", trechos=[], estado=None, pergunta=None)

    julgamento = judge.avaliar(reescrita.consulta, resultados)
    # Guarda: um juiz rigoroso demais que descarte tudo entregaria ao gerador
    # um contexto vazio e produziria "não sei" para uma pergunta que o corpus
    # respondia — nesse caso usamos todos os trechos recuperados, como se o
    # julgamento nunca tivesse acontecido.
    relevantes = (
        [resultados[i] for i in julgamento.relevantes] if julgamento.relevantes else resultados
    )
    if trace is not None:
        trace["julgados_relevantes"] = list(julgamento.relevantes)

    texto = answer.gerar_resposta(pergunta, relevantes, historico, com_cta=True)

    return Resposta(
        texto=texto,
        agente="qa",
        trechos=snapshot(relevantes),
        estado=None,
        pergunta=None,
    )

"""Executa o Agente Q&A sobre o conjunto-padrão e grava um JSONL por rodada.

Coleta e pontuação ficam separadas de propósito: esta etapa é a cara (chama
Vertex e Qdrant para cada pergunta) e a pontuação é barata. Gravado o JSONL,
as métricas de recuperação, o RAGAS e a taxa de abstenção rodam quantas vezes
for preciso sobre a mesma rodada, sem gastar nada e sem o risco de comparar
números vindos de execuções diferentes do sistema.

Uso:
    python -m eval.runner                      # todas as verificadas
    python -m eval.runner --limite 5           # amostra rápida
    python -m eval.runner --saida eval/runs/x.jsonl --retomar
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from eval import dataset
from eval.enriquecer import textos_completos
from src.agents import qa
from src.config import build_bm25
from src.rag import qdrant
from src.rag.retriever import SearchMode

logger = logging.getLogger("eval.runner")

DIR_RODADAS = Path("eval/runs")


def _secoes_indexadas(client) -> set[tuple[int, str]]:
    pontos, _ = client.scroll(
        collection_name=qdrant.COLLECTION_NAME, limit=10_000, with_payload=True, with_vectors=False
    )
    return {(int(p.payload["capitulo_num"]), str(p.payload["secao_num"])) for p in pontos}


def _trecho(t: dict, textos: dict[str, str] | None = None) -> dict:
    """`textos` traz o texto integral do chunk, buscado no Qdrant pelo id: o
    `snapshot` corta em 1500 caracteres (limite pensado para persistir o
    histórico no Postgres), e os chunks do MCR chegam a dezenas de milhares.
    Avaliar fidelidade contra o texto truncado contaria como alucinação toda
    afirmação tirada do resto da seção."""
    id_ = str(t["id"])
    return {
        "id": id_,
        "score": t["score"],
        "capitulo_num": t["capitulo_num"],
        "secao_num": str(t["secao_num"]),
        "secao_label": t["secao_label"],
        "text": (textos or {}).get(id_) or t["text"],
    }


def _executar_uma(questao: dataset.Questao, client, bm25, mode: SearchMode) -> dict:
    inicio = time.perf_counter()
    registro = {
        "id": questao.id,
        "categoria": questao.categoria,
        "pergunta": questao.pergunta,
        "referencias": sorted([c, s] for c, s in questao.referencias),
        "resposta_referencia": questao.resposta_referencia,
    }
    trace: dict = {}
    try:
        resposta = qa.responder(questao.pergunta, None, client, bm25, mode=mode, trace=trace)
        registro["resposta"] = resposta.texto
        registro["consulta_reescrita"] = trace.get("consulta")
        registro["secoes_filtradas"] = trace.get("secoes_mcr")
        # Dois estágios: o que a busca devolveu e o que sobrou depois do juiz.
        # Medir só o segundo atribuiria ao retriever uma seção que ele achou e
        # o juiz descartou.
        textos = textos_completos(
            [str(t["id"]) for t in (trace.get("recuperados") or []) + list(resposta.trechos)]
        )
        registro["recuperados"] = [_trecho(t, textos) for t in trace.get("recuperados") or []]
        registro["trechos"] = [_trecho(t, textos) for t in resposta.trechos]
        registro["erro"] = None
    except Exception as e:  # uma pergunta que falha não pode derrubar a rodada
        logger.warning("%s falhou: %s", questao.id, e)
        registro["resposta"] = None
        registro["recuperados"] = [_trecho(t) for t in trace.get("recuperados") or []]
        registro["trechos"] = []
        registro["erro"] = f"{type(e).__name__}: {e}"

    registro["latencia_s"] = round(time.perf_counter() - inicio, 2)
    return registro


def executar(
    questoes: list[dataset.Questao],
    saida: Path,
    *,
    mode: SearchMode = SearchMode.HYBRID,
    paralelismo: int = 4,
) -> Path:
    client = qdrant.get_client()
    bm25 = build_bm25()

    problemas = dataset.validar(questoes, _secoes_indexadas(client))
    if problemas:
        raise SystemExit("gabarito inválido:\n  " + "\n  ".join(problemas))

    saida.parent.mkdir(parents=True, exist_ok=True)
    trava = Lock()
    concluidas = 0
    total = len(questoes)

    # append + flush a cada pergunta: uma rodada interrompida no meio (Ctrl+C,
    # cota do Vertex, queda de rede) mantém tudo o que já foi respondido, e
    # `--retomar` continua de onde parou em vez de pagar tudo de novo.
    with io_aberto(saida) as arquivo:
        def tarefa(q: dataset.Questao) -> None:
            nonlocal concluidas
            registro = _executar_uma(q, client, bm25, mode)
            with trava:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
                arquivo.flush()
                concluidas += 1
                logger.info("[%d/%d] %s (%.1fs)", concluidas, total, q.id, registro["latencia_s"])

        with ThreadPoolExecutor(max_workers=paralelismo) as pool:
            list(pool.map(tarefa, questoes))

    return saida


def io_aberto(caminho: Path):
    return open(caminho, "a", encoding="utf-8", newline="\n")


def _ids_ja_executados(saida: Path) -> set[str]:
    if not saida.exists():
        return set()
    ids = set()
    with open(saida, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                ids.add(json.loads(linha)["id"])
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Roda o Agente Q&A sobre o conjunto-padrão.")
    parser.add_argument("--csv", default=str(dataset.CSV_PADRAO))
    parser.add_argument("--saida", default=None, help="JSONL de saída (padrão: eval/runs/<ts>.jsonl)")
    parser.add_argument("--limite", type=int, default=None, help="usa só as N primeiras perguntas")
    parser.add_argument("--categoria", default=None, help="filtra por categoria")
    parser.add_argument("--paralelismo", type=int, default=4)
    parser.add_argument("--retomar", action="store_true", help="pula ids já presentes na saída")
    parser.add_argument(
        "--mode", default=SearchMode.HYBRID.value, choices=[m.value for m in SearchMode]
    )
    args = parser.parse_args()

    questoes = dataset.carregar(args.csv)
    if args.categoria:
        questoes = [q for q in questoes if q.categoria == args.categoria]

    saida = Path(args.saida) if args.saida else DIR_RODADAS / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl"
    )
    if args.retomar:
        ja = _ids_ja_executados(saida)
        questoes = [q for q in questoes if q.id not in ja]
        logger.info("retomando: %d já executadas, %d restantes", len(ja), len(questoes))

    if args.limite:
        questoes = questoes[: args.limite]

    if not questoes:
        logger.info("nada a executar")
        return

    logger.info("rodando %d perguntas → %s", len(questoes), saida)
    executar(questoes, saida, mode=SearchMode(args.mode), paralelismo=args.paralelismo)
    logger.info("pronto: %s", saida)


if __name__ == "__main__":
    main()

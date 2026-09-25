"""Métricas de geração via RAGAS sobre uma rodada do `eval.runner`.

Roda em `venv-eval` (ambiente separado), porque o RAGAS traz LangChain e
`datasets` junto e não vale misturar isso com as dependências do app:

    venv-eval/Scripts/python -m eval.metrics_ragas eval/runs/rodada01.jsonl

Quatro métricas, e o que cada uma acrescenta ao que já é medido sem LLM:

- `faithfulness` — cada afirmação da resposta é sustentada pelos trechos?
  É a única que mede alucinação na **resposta**; as métricas de
  `metrics_retrieval.py` só olham para os trechos.
- `answer_relevancy` — a resposta endereça a pergunta, em vez de derivar para
  um tema vizinho.
- `context_precision` / `context_recall` — a versão julgada por LLM do que
  `metrics_retrieval.py` calcula por contagem. Ficam aqui para triangulação:
  divergência grande entre as duas leituras é sinal de gabarito ou de juiz com
  problema, e é informação para a discussão do TCC.

Juiz: `gemini-2.5-flash`. Embeddings (necessários para `answer_relevancy`):
`voyage-4-lite`, o mesmo modelo denso que o retriever usa — não faz sentido
avaliar similaridade com um espaço vetorial diferente do que o sistema usa.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from langchain_google_vertexai import ChatVertexAI
from langchain_voyageai import VoyageAIEmbeddings
from ragas import EvaluationDataset, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    Faithfulness,
    LLMContextPrecisionWithReference,
    LLMContextRecall,
    ResponseRelevancy,
)

MODELO_JUIZ = "gemini-2.5-flash"
MODELO_EMBEDDING = "voyage-4-lite"

CATEGORIA_ABSTENCAO = "abstencao"


def _credenciais() -> service_account.Credentials:
    """Mesma fonte do app (`src/llm/client.py`): a service account vem em
    base64 no ambiente, não de um arquivo no disco."""
    sa_info = json.loads(base64.b64decode(os.environ["GCLOUD_SA_BASE64"]))
    return service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


def construir_juiz():
    llm = ChatVertexAI(
        model_name=MODELO_JUIZ,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        credentials=_credenciais(),
        temperature=0.0,
        max_retries=3,
    )
    embeddings = VoyageAIEmbeddings(model=MODELO_EMBEDDING, batch_size=8)
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(embeddings)


def carregar_amostras(caminho: Path, *, incluir_abstencao: bool = False) -> list[dict]:
    amostras = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            if not linha.strip():
                continue
            r = json.loads(linha)
            if r.get("erro") or not r.get("resposta"):
                continue
            if not incluir_abstencao and r["categoria"] == CATEGORIA_ABSTENCAO:
                continue
            amostras.append(
                {
                    "id": r["id"],
                    "categoria": r["categoria"],
                    "user_input": r["pergunta"],
                    "response": r["resposta"],
                    "retrieved_contexts": [t["text"] for t in (r.get("trechos") or [])],
                    "reference": r.get("resposta_referencia") or "",
                }
            )
    return amostras


def main() -> None:
    parser = argparse.ArgumentParser(description="Métricas RAGAS de uma rodada.")
    parser.add_argument("rodada")
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--saida", default=None, help="CSV com a nota por pergunta")
    args = parser.parse_args()

    load_dotenv()
    amostras = carregar_amostras(Path(args.rodada))
    if args.limite:
        amostras = amostras[: args.limite]
    if not amostras:
        raise SystemExit("nenhuma amostra utilizável na rodada")

    llm, embeddings = construir_juiz()
    metricas = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
        LLMContextPrecisionWithReference(llm=llm),
        LLMContextRecall(llm=llm),
    ]

    dataset = EvaluationDataset.from_list(
        [{k: v for k, v in a.items() if k not in ("id", "categoria")} for a in amostras]
    )
    resultado = evaluate(dataset=dataset, metrics=metricas, llm=llm, embeddings=embeddings)

    df = resultado.to_pandas()
    df.insert(0, "categoria", [a["categoria"] for a in amostras])
    df.insert(0, "id", [a["id"] for a in amostras])

    colunas = [c for c in df.columns if c not in ("id", "categoria", "user_input", "response", "retrieved_contexts", "reference")]

    print(f"Perguntas avaliadas: {len(df)}  |  juiz: {MODELO_JUIZ}\n")
    print("| categoria              |   n | " + " | ".join(f"{c[:18]:<18}" for c in colunas) + " |")
    print("|------------------------|-----|-" + "-|-".join("-" * 18 for _ in colunas) + "-|")

    por_categoria = defaultdict(list)
    for _, linha in df.iterrows():
        por_categoria[linha["categoria"]].append(linha)

    for categoria in sorted(por_categoria):
        sub = df[df["categoria"] == categoria]
        medias = " | ".join(f"{sub[c].mean():<18.2f}" for c in colunas)
        print(f"| {categoria:<22} | {len(sub):>3} | {medias} |")
    medias = " | ".join(f"{df[c].mean():<18.2f}" for c in colunas)
    print(f"| {'TOTAL':<22} | {len(df):>3} | {medias} |")

    saida = Path(args.saida) if args.saida else Path(args.rodada).with_suffix(".ragas.csv")
    df.to_csv(saida, index=False, encoding="utf-8-sig")
    print(f"\nNota por pergunta: {saida}")


if __name__ == "__main__":
    main()

"""Taxa de abstenção nas perguntas-isca (categoria `abstencao`).

Essas perguntas não têm seção de origem no MCR — foram escritas justamente
para não ter resposta no manual, então a resposta certa é recusar. Por isso
elas ficam fora de `eval/metrics_retrieval.py`: cobertura de um gabarito
vazio não significa nada. O que se mede aqui é o oposto — com que frequência
o sistema inventa quando não tem base.

A classificação usa o `gemini-2.5-flash` porque reconhecer recusa exige ler a
resposta: uma busca por palavras como "não encontrei" erraria tanto a recusa
educada ("o Manual de Crédito Rural não trata desse tema") quanto o falso
positivo ("não há limite máximo para..."), que é uma resposta afirmativa.

Uso:
    python -m eval.metrics_abstencao eval/runs/<rodada>.jsonl
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from eval.dataset import CATEGORIA_ABSTENCAO
from eval.metrics_retrieval import carregar_rodada
from src.llm import client as llm_client
from src.llm.client import MODELO_RAPIDO

PROMPT = (
    "Uma pergunta foi feita a um assistente sobre o Manual de Crédito Rural "
    "(MCR). A pergunta é deliberadamente fora do escopo do manual: a resposta "
    "correta seria recusar ou declarar que a informação não está no MCR.\n\n"
    "Classifique a RESPOSTA do assistente:\n"
    "- 'abstencao': reconhece que não sabe, que a informação não está no MCR, "
    "ou recusa responder (mesmo que sugira onde procurar).\n"
    "- 'resposta_substantiva': afirma fatos como se o MCR os respondesse, "
    "mesmo que com ressalvas.\n\n"
    "Responda em JSON com o campo 'classe'."
)

SCHEMA = {
    "type": "object",
    "properties": {"classe": {"type": "string", "enum": ["abstencao", "resposta_substantiva"]}},
    "required": ["classe"],
}


def classificar(pergunta: str, resposta: str) -> str | None:
    """`None` quando o classificador falha — contado à parte, nunca somado a
    um dos dois lados, para não inflar nem a taxa de abstenção nem a de
    alucinação com erro de ferramenta."""
    prompt = f"{PROMPT}\n\nPERGUNTA: {pergunta}\n\nRESPOSTA: {resposta}"
    resultado = llm_client.gerar_json(prompt, schema=SCHEMA, modelo=MODELO_RAPIDO)
    if not isinstance(resultado, dict):
        return None
    classe = resultado.get("classe")
    return classe if classe in ("abstencao", "resposta_substantiva") else None


def avaliar(rodada: Path, *, paralelismo: int = 6) -> tuple[dict, list[tuple]]:
    """Classifica as iscas de `rodada` e devolve (contagem, detalhe)."""
    registros = [
        r
        for r in carregar_rodada(rodada)
        if r["categoria"] == CATEGORIA_ABSTENCAO and not r.get("erro")
    ]

    with ThreadPoolExecutor(max_workers=paralelismo) as pool:
        classes = list(
            pool.map(lambda r: classificar(r["pergunta"], r["resposta"] or ""), registros)
        )

    contagem = {"abstencao": 0, "resposta_substantiva": 0, "indefinido": 0}
    linhas = []
    for r, classe in zip(registros, classes):
        classe = classe or "indefinido"
        contagem[classe] += 1
        linhas.append((r["id"], classe, len(r.get("trechos") or [])))
    return contagem, linhas


def gravar(rodada: Path, contagem: dict, linhas: list[tuple], saida: Path | None = None) -> Path:
    destino = saida or rodada.with_suffix(".abstencao.json")
    destino.write_text(
        json.dumps(
            {"contagem": contagem, "por_pergunta": {q: c for q, c, _ in linhas}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description="Taxa de abstenção de uma rodada.")
    parser.add_argument("rodada")
    parser.add_argument("--saida", default=None, help="JSON com a classificação por pergunta")
    args = parser.parse_args()

    registros = [
        r
        for r in carregar_rodada(Path(args.rodada))
        if r["categoria"] == CATEGORIA_ABSTENCAO and not r.get("erro")
    ]
    contagem, linhas = avaliar(Path(args.rodada))

    total = len(registros)
    print(f"Perguntas-isca avaliadas: {total}")
    if total:
        print(f"  abstenção correta:     {contagem['abstencao']:>3} ({contagem['abstencao']/total:.0%})")
        print(
            f"  respondeu mesmo assim: {contagem['resposta_substantiva']:>3} "
            f"({contagem['resposta_substantiva']/total:.0%})"
        )
        if contagem["indefinido"]:
            print(f"  classificador falhou:  {contagem['indefinido']:>3}")

    print("\nDetalhe:")
    for qid, classe, n_trechos in linhas:
        print(f"  {qid:<12} {classe:<22} trechos no contexto: {n_trechos}")


if __name__ == "__main__":
    main()

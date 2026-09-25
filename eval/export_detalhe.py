"""Junta tudo o que se sabe sobre cada pergunta numa linha só.

As métricas agregadas dizem como o sistema vai; esta tabela é a que permite
auditar **por que**. Para cada pergunta reúne, lado a lado: o que foi
perguntado, quais seções deveriam ter sido recuperadas, quais vieram (antes e
depois do juiz), a resposta gerada, a resposta de referência e as notas do
RAGAS, quando existirem.

Se a resposta está certa é julgamento humano, e por isso não há coluna de
veredito aqui: a tabela coloca resposta e referência lado a lado para quem
revisa decidir — um rótulo de máquina nesse campo daria confiança que ele não
tem.

Sai em dois formatos, pelo mesmo motivo que coleta e pontuação são separadas:
o CSV é para abrir na planilha e revisar à mão; o JSON alimenta a página de
resultados.

Uso:
    python -m eval.export_detalhe eval/runs/rodada01.enriquecido.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# O CSV do RAGAS carrega os trechos inteiros numa célula — dezenas de milhares
# de caracteres, acima do limite padrão do módulo csv.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from eval.metrics_retrieval import avaliar_registro, carregar_rodada

COLUNAS = [
    "id",
    "categoria",
    "pergunta",
    "gabarito",
    "recuperados",
    "pos_juiz",
    "acertou_busca",
    "acertou_pos_juiz",
    "precisao_pos_juiz",
    "cobertura_pos_juiz",
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "resposta",
    "resposta_referencia",
]


def rotulos_das_secoes() -> dict[str, str]:
    """Título de cada seção, lido do índice. O JSONL da rodada guarda só
    `secao_label`, que é o número repetido; quem revisa precisa do nome
    ("Beneficiários", "Encargos Financeiros") para julgar se a seção
    recuperada fazia sentido."""
    from src.rag import qdrant

    pontos, _ = qdrant.get_client().scroll(
        collection_name=qdrant.COLLECTION_NAME, limit=10_000, with_payload=True, with_vectors=False
    )
    rotulos = {}
    for p in pontos:
        carga = p.payload or {}
        ref = f"{carga.get('capitulo_num')}-{carga.get('secao_num')}"
        rotulos[ref] = carga.get("secao_text") or carga.get("secao_label") or ""
    return rotulos


def _secoes(trechos: list[dict], gabarito: set[tuple[int, str]], rotulos: dict[str, str]) -> list[dict]:
    return [
        {
            "ref": f"{t['capitulo_num']}-{t['secao_num']}",
            "label": rotulos.get(f"{t['capitulo_num']}-{t['secao_num']}", ""),
            "score": round(float(t.get("score") or 0), 3),
            "relevante": (t["capitulo_num"], str(t["secao_num"])) in gabarito,
        }
        for t in trechos
    ]


def _ragas_por_id(caminho: Path) -> dict[str, dict]:
    """O CSV do RAGAS não traz o mesmo nome de coluna entre versões; o que
    interessa é a ordem das quatro métricas, então elas são mapeadas por
    prefixo em vez de por nome exato."""
    if not caminho.exists():
        return {}
    chaves = {
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
        "llm_context_precision": "context_precision",
        "context_recall": "context_recall",
    }
    notas: dict[str, dict] = {}
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f):
            item = {}
            for coluna, valor in linha.items():
                for prefixo, nome in chaves.items():
                    if coluna.startswith(prefixo):
                        try:
                            item[nome] = round(float(valor), 2)
                        except (TypeError, ValueError):
                            item[nome] = None
            notas[linha["id"]] = item
    return notas


def montar(entrada: Path) -> list[dict]:
    registros = carregar_rodada(entrada)
    rotulos = rotulos_das_secoes()
    base = entrada.with_suffix("")
    ragas = _ragas_por_id(Path(str(base) + ".ragas.csv"))

    linhas = []
    for r in registros:
        gabarito = {(c, str(s)) for c, s in r["referencias"]}
        pos = avaliar_registro(r, estagio="trechos")
        bruto = avaliar_registro(r, estagio="recuperados")
        notas = ragas.get(r["id"], {})
        linhas.append(
            {
                "id": r["id"],
                "categoria": r["categoria"],
                "pergunta": r["pergunta"],
                "gabarito": [f"{c}-{s}" for c, s in sorted(gabarito)],
                "gabarito_rotulos": [rotulos.get(f"{c}-{s}", "") for c, s in sorted(gabarito)],
                "recuperados": _secoes(r.get("recuperados") or [], gabarito, rotulos),
                "pos_juiz": _secoes(r.get("trechos") or [], gabarito, rotulos),
                "acertou_busca": bruto.acertou if bruto else None,
                "acertou_pos_juiz": pos.acertou if pos else None,
                "precisao_pos_juiz": round(pos.precisao, 2) if pos else None,
                "cobertura_pos_juiz": round(pos.cobertura, 2) if pos else None,
                "faithfulness": notas.get("faithfulness"),
                "answer_relevancy": notas.get("answer_relevancy"),
                "context_precision": notas.get("context_precision"),
                "context_recall": notas.get("context_recall"),
                "resposta": r.get("resposta"),
                "resposta_referencia": r.get("resposta_referencia"),
                "erro": r.get("erro"),
            }
        )
    return linhas


def _plano(valor) -> str:
    """Achata as listas de seções para o CSV — a planilha não aninha."""
    if isinstance(valor, list):
        if valor and isinstance(valor[0], dict):
            return " | ".join(
                f"{s['ref']}{'*' if s['relevante'] else ''} ({s['label'][:40]})" for s in valor
            )
        return ", ".join(str(v) for v in valor)
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return "" if valor is None else str(valor)


def exportar(entrada: Path) -> tuple[Path, Path, int]:
    """Escreve o CSV e o JSON de detalhe ao lado da rodada."""
    linhas = montar(entrada)
    base = str(entrada.with_suffix(""))

    csv_saida = Path(base + ".detalhe.csv")
    with open(csv_saida, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({c: _plano(linha.get(c)) for c in COLUNAS})

    json_saida = Path(base + ".detalhe.json")
    json_saida.write_text(json.dumps(linhas, ensure_ascii=False), encoding="utf-8")
    return csv_saida, json_saida, len(linhas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detalhe por pergunta, em CSV e JSON.")
    parser.add_argument("rodada")
    args = parser.parse_args()

    csv_saida, json_saida, total = exportar(Path(args.rodada))

    print(f"{total} perguntas")
    print(f"planilha: {csv_saida}")
    print(f"json:     {json_saida}")
    print("\nNo CSV, '*' marca a seção que estava no gabarito.")


if __name__ == "__main__":
    main()

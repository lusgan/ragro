"""Métricas de recuperação sobre uma rodada do `eval.runner` — sem LLM.

Definições (as mesmas da tabela de TCC-1, para o número novo ser comparável
com o baseline de 7 consultas: P 0,45 / R 0,78):

    precisão  = trechos recuperados que são relevantes / trechos recuperados
    cobertura = seções do gabarito recuperadas / seções do gabarito

Nada é medido "@5": o `buscar_com_fallback` devolve de 1 a 5 trechos conforme
o filtro de seção e o fallback, então dividir por um k fixo puniria uma busca
que devolveu 2 trechos, ambos certos. O denominador da precisão é o que a
busca de fato devolveu, e o número médio de trechos é reportado à parte —
é ele que dá contexto para ler a precisão.

Um trecho conta como relevante quando o par (capítulo, seção) do payload está
nas `referencias_mcr` curadas. A comparação é exata porque, no índice atual,
um chunk é uma seção inteira do manual (101 chunks, 99 pares distintos).

Perguntas de abstenção não entram aqui: não têm seção de origem, porque a
resposta certa é recusar. Elas são medidas em `eval/metrics_abstencao.py`.

Uso:
    python -m eval.metrics_retrieval eval/runs/<rodada>.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from eval.dataset import CATEGORIA_ABSTENCAO


@dataclass(frozen=True)
class Resultado:
    id: str
    categoria: str
    recuperados: int
    relevantes_recuperados: int
    gabarito: int
    precisao: float
    cobertura: float
    f1: float
    acertou: bool  # pelo menos uma seção do gabarito apareceu


def _f1(precisao: float, cobertura: float) -> float:
    if precisao + cobertura == 0:
        return 0.0
    return 2 * precisao * cobertura / (precisao + cobertura)


def avaliar_registro(registro: dict, *, estagio: str = "trechos") -> Resultado | None:
    """`estagio="recuperados"` mede a busca crua (até 5 trechos);
    `estagio="trechos"` mede o contexto final, já filtrado pelo juiz — que é o
    que de fato alimenta a geração."""
    if registro["categoria"] == CATEGORIA_ABSTENCAO:
        return None

    gabarito = {(c, str(s)) for c, s in registro["referencias"]}
    trechos = registro.get(estagio) or []
    secoes = [(t["capitulo_num"], str(t["secao_num"])) for t in trechos]

    relevantes = sum(1 for s in secoes if s in gabarito)
    encontradas = {s for s in secoes if s in gabarito}

    precisao = relevantes / len(secoes) if secoes else 0.0
    cobertura = len(encontradas) / len(gabarito) if gabarito else 0.0

    return Resultado(
        id=registro["id"],
        categoria=registro["categoria"],
        recuperados=len(secoes),
        relevantes_recuperados=relevantes,
        gabarito=len(gabarito),
        precisao=precisao,
        cobertura=cobertura,
        f1=_f1(precisao, cobertura),
        acertou=bool(encontradas),
    )


def carregar_rodada(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(linha) for linha in f if linha.strip()]


def _media(valores: list[float]) -> float:
    return statistics.fmean(valores) if valores else 0.0


def resumir(resultados: list[Resultado]) -> dict:
    """Média macro (média das métricas por pergunta), que é como a tabela de
    TCC-1 foi calculada — cada pergunta pesa igual, independente de quantos
    trechos voltaram."""
    return {
        "n": len(resultados),
        "precisao": _media([r.precisao for r in resultados]),
        "cobertura": _media([r.cobertura for r in resultados]),
        "f1": _media([r.f1 for r in resultados]),
        "acerto": _media([1.0 if r.acertou else 0.0 for r in resultados]),
        "trechos_por_pergunta": _media([float(r.recuperados) for r in resultados]),
    }


def _linha_tabela(nome: str, s: dict) -> str:
    return (
        f"| {nome:<22} | {s['n']:>3} | {s['precisao']:.2f} | {s['cobertura']:.2f} | "
        f"{s['f1']:.2f} | {s['acerto']:.0%} | {s['trechos_por_pergunta']:.1f} |"
    )


def relatorio(resultados: list[Resultado], falhas: list[dict], titulo: str = "") -> str:
    por_categoria: dict[str, list[Resultado]] = defaultdict(list)
    for r in resultados:
        por_categoria[r.categoria].append(r)

    linhas = [
        f"### {titulo}" if titulo else "",
        "| categoria              |   n | prec | cobe |  f1  | acerto | trechos |",
        "|------------------------|-----|------|------|------|--------|---------|",
    ]
    for categoria in sorted(por_categoria):
        linhas.append(_linha_tabela(categoria, resumir(por_categoria[categoria])))
    linhas.append(_linha_tabela("TOTAL", resumir(resultados)))

    piores = sorted(resultados, key=lambda r: (r.cobertura, r.precisao))[:10]
    linhas += ["", "Piores casos (cobertura, depois precisão):"]
    for r in piores:
        linhas.append(
            f"  {r.id:<12} {r.categoria:<22} cobe={r.cobertura:.2f} prec={r.precisao:.2f} "
            f"({r.relevantes_recuperados}/{r.recuperados} trechos, gabarito {r.gabarito})"
        )

    if falhas:
        linhas += ["", f"Perguntas com erro de execução: {len(falhas)}"]
        for f in falhas:
            linhas.append(f"  {f['id']}: {f['erro']}")

    return "\n".join(linhas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Métricas de recuperação de uma rodada.")
    parser.add_argument("rodada", help="JSONL gerado por `python -m eval.runner`")
    parser.add_argument("--json", action="store_true", help="imprime o resumo como JSON")
    parser.add_argument(
        "--estagio",
        default="ambos",
        choices=["recuperados", "trechos", "ambos"],
        help="busca crua, contexto pós-juiz, ou os dois",
    )
    args = parser.parse_args()

    registros = carregar_rodada(Path(args.rodada))
    falhas = [r for r in registros if r.get("erro")]

    def avaliar(estagio: str) -> list[Resultado]:
        return [
            resultado
            for registro in registros
            if not registro.get("erro")
            and (resultado := avaliar_registro(registro, estagio=estagio)) is not None
        ]

    if args.estagio == "ambos":
        print(relatorio(avaliar("recuperados"), [], "Busca crua (antes do juiz)"))
        print()
        print(relatorio(avaliar("trechos"), falhas, "Contexto final (depois do juiz)"))
        return

    resultados = avaliar(args.estagio)

    if args.json:
        por_categoria = defaultdict(list)
        for r in resultados:
            por_categoria[r.categoria].append(r)
        print(json.dumps(
            {
                "total": resumir(resultados),
                "por_categoria": {c: resumir(v) for c, v in por_categoria.items()},
                "falhas": len(falhas),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return

    print(relatorio(resultados, falhas))


if __name__ == "__main__":
    main()

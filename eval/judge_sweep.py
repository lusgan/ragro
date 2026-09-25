"""Compara configurações do LLM-as-a-judge sobre os mesmos trechos recuperados.

A pergunta é: o juiz descarta seções relevantes por limitação do modelo, ou
por só enxergar o começo de cada trecho? Para responder não é preciso gerar
resposta nenhuma — a recuperação e a redação não mudam quando o juiz muda.
Este módulo **reexecuta só o julgamento** sobre os candidatos já salvos em
`<rodada>.enriquecido.jsonl`, que têm o texto integral.

Duas consequências desse desenho: todas as variantes veem exatamente o mesmo
conjunto de candidatos (a busca não é refeita, então a comparação não carrega
a variação do retriever), e cada variante custa uma chamada por pergunta em
vez de uma rodada inteira.

Uso:
    python -m eval.judge_sweep eval/runs/rodada01.enriquecido.jsonl
    python -m eval.judge_sweep <rodada> --variantes flash:1200 pro:1200 pro:8000
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from eval.dataset import CATEGORIA_ABSTENCAO
from eval.metrics_retrieval import Resultado, _f1, avaliar_registro, carregar_rodada, resumir
from src.llm.client import MODELO_PRINCIPAL, MODELO_RAPIDO
from src.rag import judge

MODELOS = {"flash": MODELO_RAPIDO, "pro": MODELO_PRINCIPAL}

# `flash:inf` — sem cap nenhum: o juiz recebe cada trecho inteiro. O maior
# chunk do MCR tem ~85 mil caracteres, então nem 20 mil cobre todos.
SEM_LIMITE = 10**9

VARIANTES_PADRAO = ["flash:1200", "flash:8000", "pro:1200", "pro:8000"]


@dataclass(frozen=True)
class Variante:
    rotulo: str
    modelo: str
    max_chars: int

    @classmethod
    def de_texto(cls, texto: str) -> "Variante":
        apelido, _, chars = texto.partition(":")
        if apelido not in MODELOS:
            raise SystemExit(f"modelo desconhecido em '{texto}' — use {' ou '.join(MODELOS)}")
        max_chars = SEM_LIMITE if chars in ("inf", "0", "") else int(chars)
        return cls(rotulo=texto, modelo=MODELOS[apelido], max_chars=max_chars)


def _pontos(trechos: list[dict]) -> list:
    """Reconstrói o formato que `judge.avaliar` espera (objetos com
    `.payload`), para o experimento exercitar o mesmo código do app em vez de
    uma reimplementação que poderia divergir dele."""
    return [
        SimpleNamespace(
            id=t["id"],
            score=t.get("score"),
            payload={
                "capitulo_num": t["capitulo_num"],
                "capitulo_text": t.get("capitulo_text"),
                "secao_num": t["secao_num"],
                "secao_label": t.get("secao_label"),
                "secao_text": t.get("secao_text"),
                "text": t.get("text") or "",
            },
        )
        for t in trechos
    ]


def _avaliar_um(registro: dict, variante: Variante) -> Resultado | None:
    candidatos = registro.get("recuperados") or []
    if not candidatos:
        return None

    julgamento = judge.avaliar(
        registro["pergunta"],
        _pontos(candidatos),
        modelo=variante.modelo,
        max_chars=variante.max_chars,
    )
    # Mesma guarda do `qa.py`: julgamento vazio significa "mantém tudo".
    escolhidos = (
        [candidatos[i] for i in julgamento.relevantes] if julgamento.relevantes else candidatos
    )

    gabarito = {(c, str(s)) for c, s in registro["referencias"]}
    secoes = [(t["capitulo_num"], str(t["secao_num"])) for t in escolhidos]
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


class _ContaFalhas(logging.Handler):
    """Uma chamada que falha faz `judge.avaliar` manter todos os trechos, o que
    é indistinguível de um juiz que aprovou todos — e infla a cobertura da
    variante. Contar os avisos do cliente separa fallback de decisão."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.total = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "gerar_json" in record.getMessage():
            self.total += 1


def rodar(
    registros: list[dict], variante: Variante, paralelismo: int = 4
) -> tuple[list[Resultado], int]:
    contador = _ContaFalhas()
    logger_llm = logging.getLogger("src.llm.client")
    logger_llm.addHandler(contador)
    try:
        with ThreadPoolExecutor(max_workers=paralelismo) as pool:
            resultados = pool.map(lambda r: _avaliar_um(r, variante), registros)
            resultados = [r for r in resultados if r is not None]
    finally:
        logger_llm.removeHandler(contador)
    return resultados, contador.total


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara configurações do juiz.")
    parser.add_argument("rodada", help="JSONL enriquecido (com texto integral dos trechos)")
    parser.add_argument("--variantes", nargs="+", default=VARIANTES_PADRAO, help="modelo:max_chars")
    parser.add_argument("--paralelismo", type=int, default=4)
    parser.add_argument(
        "--apenas-afetadas",
        action="store_true",
        help=(
            "roda só nas perguntas cuja cobertura pós-juiz ficou abaixo de 1,00 na rodada "
            "original — mais barato para iterar, mas só mede recuperação: uma variante que "
            "quebre uma pergunta hoje perfeita não aparece. Antes de concluir, rode no conjunto inteiro."
        ),
    )
    parser.add_argument("--saida", default=None, help="JSON com o resumo de cada variante")
    args = parser.parse_args()

    entrada = Path(args.rodada)
    registros = [
        r
        for r in carregar_rodada(entrada)
        if r["categoria"] != CATEGORIA_ABSTENCAO and not r.get("erro") and r.get("recuperados")
    ]

    total_registros = len(registros)
    if args.apenas_afetadas:
        # Só as perguntas que o juiz já prejudicou: são as únicas em que há
        # cobertura a recuperar. Barato para iterar, cego para regressão.
        registros = [
            r
            for r in registros
            if (res := avaliar_registro(r, estagio="trechos")) is not None and res.cobertura < 1.0
        ]

    maior = max(len(t.get("text") or "") for r in registros for t in r["recuperados"])
    escopo = (
        f"{len(registros)} de {total_registros} perguntas — só as de cobertura < 1,00"
        if args.apenas_afetadas
        else f"{len(registros)} perguntas"
    )
    print(f"{escopo} | maior trecho: {maior} caracteres\n")

    print("| variante        |   n | prec | cobe |  f1  | acerto | trechos | falhas |")
    print("|-----------------|-----|------|------|------|--------|---------|--------|")

    resumos = {}
    detalhes = {}
    for texto in args.variantes:
        variante = Variante.de_texto(texto)
        resultados, falhas = rodar(registros, variante, args.paralelismo)
        s = resumir(resultados)
        s["falhas_do_cliente"] = falhas
        resumos[texto] = s
        detalhes[texto] = {r.id: r.acertou for r in resultados}
        print(
            f"| {texto:<15} | {s['n']:>3} | {s['precisao']:.2f} | {s['cobertura']:.2f} | "
            f"{s['f1']:.2f} | {s['acerto']:.0%} | {s['trechos_por_pergunta']:.1f} | "
            f"{falhas:>6} |"
        )

    # Quem ganhou e quem perdeu em relação à primeira variante: a média esconde
    # troca de acertos por erros, e é justamente isso que interessa aqui.
    base = args.variantes[0]
    for texto in args.variantes[1:]:
        ganhou = [q for q, ok in detalhes[texto].items() if ok and not detalhes[base].get(q)]
        perdeu = [q for q, ok in detalhes[texto].items() if not ok and detalhes[base].get(q)]
        print(f"\n{texto} vs {base}: +{len(ganhou)} acertos, -{len(perdeu)}")
        if ganhou:
            print(f"  recuperou: {', '.join(sorted(ganhou))}")
        if perdeu:
            print(f"  perdeu:    {', '.join(sorted(perdeu))}")

    if args.saida:
        Path(args.saida).write_text(
            json.dumps({"resumos": resumos, "acertos": detalhes}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nresumo: {args.saida}")


if __name__ == "__main__":
    main()

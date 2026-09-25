"""Uma rodada de avaliação inteira, do zero ao relatório aberto no navegador.

    venv/Scripts/python -m eval.avaliar

Encadeia o que antes eram cinco comandos — executar, enriquecer, pontuar
abstenção e RAGAS, exportar o detalhe e gerar a página — numa sequência só,
numerando a rodada sozinho para não sobrescrever medição anterior.

As etapas continuam existindo como módulos independentes e seguem utilizáveis
à mão (ver `eval/README.md`): este módulo é a conveniência, não a fonte da
verdade. Quem precisa repontuar uma rodada antiga, ou comparar configurações
sem gerar respostas de novo, chama as etapas direto.

Nada aqui refaz o passo caro sem necessidade: `--relatorio-de` regenera a
página a partir de uma rodada já executada, e `--retomar` continua uma que
ficou pela metade.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from eval import dataset, enriquecer, export_detalhe, metrics_abstencao, runner
from eval.relatorio import Dados
from eval.relatorio_html import render
from src.rag.retriever import SearchMode

DIR_RODADAS = Path("eval/runs")
PYTHON_RAGAS = Path("venv-eval/Scripts/python.exe")


def _proximo_nome() -> Path:
    """rodada01, rodada02, … — o maior número já usado, mais um."""
    usados = [
        int(m.group(1))
        for arquivo in DIR_RODADAS.glob("rodada*.jsonl")
        if (m := re.match(r"rodada(\d+)", arquivo.name))
    ]
    return DIR_RODADAS / f"rodada{max(usados, default=0) + 1:02d}.jsonl"


def _passo(numero: int, total: int, texto: str) -> None:
    print(f"\n[{numero}/{total}] {texto}", flush=True)


def _sem_erros(caminho: Path) -> int:
    """Descarta as linhas que falharam, para `--retomar` refazer só elas.
    Devolve quantas foram removidas."""
    linhas = [l for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    boas = [l for l in linhas if not json.loads(l).get("erro")]
    if len(boas) != len(linhas):
        caminho.write_text("\n".join(boas) + "\n", encoding="utf-8", newline="\n")
    return len(linhas) - len(boas)


def executar_rodada(saida: Path, args) -> None:
    questoes = dataset.carregar(args.csv)
    if args.categoria:
        questoes = [q for q in questoes if q.categoria == args.categoria]
    if args.retomar and saida.exists():
        descartadas = _sem_erros(saida)
        ja = {json.loads(l)["id"] for l in saida.read_text(encoding="utf-8").splitlines() if l.strip()}
        questoes = [q for q in questoes if q.id not in ja]
        print(f"  retomando: {len(ja)} já feitas, {descartadas} com erro a refazer")
    if args.limite:
        questoes = questoes[: args.limite]

    if not questoes:
        print("  nada a executar")
        return

    print(f"  {len(questoes)} perguntas — a etapa mais demorada, ~40 min para o conjunto inteiro")
    runner.executar(questoes, saida, mode=SearchMode(args.mode), paralelismo=args.paralelismo)

    # Uma segunda passada cobre o que caiu por cota ou instabilidade, que é
    # falha do serviço e não do sistema sob teste.
    if (falhas := _sem_erros(saida)) :
        print(f"  {falhas} pergunta(s) falharam; refazendo")
        feitas = {json.loads(l)["id"] for l in saida.read_text(encoding="utf-8").splitlines() if l.strip()}
        runner.executar(
            [q for q in dataset.carregar(args.csv) if q.id not in feitas],
            saida,
            mode=SearchMode(args.mode),
            paralelismo=1,
        )


def pontuar_ragas(enriquecido: Path) -> bool:
    """RAGAS roda noutro interpretador (`venv-eval`), com LangChain 0.3 preso.
    Ausência do ambiente não derruba a rodada: a página apenas sai sem a seção.
    """
    if not PYTHON_RAGAS.exists():
        print(f"  {PYTHON_RAGAS} não existe — pulando (ver eval/README.md)")
        return False
    processo = subprocess.run(
        [str(PYTHON_RAGAS), "-m", "eval.metrics_ragas", str(enriquecido)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if processo.returncode != 0:
        print("  RAGAS falhou; a página sai sem essa seção")
        print((processo.stderr or "").strip()[-600:])
        return False
    for linha in (processo.stdout or "").splitlines():
        if linha.startswith("|") or linha.startswith("Perguntas"):
            print("  " + linha)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Roda a avaliação inteira e abre o relatório.",
        epilog="Sem argumentos: executa o conjunto completo numa rodada nova.",
    )
    parser.add_argument("--csv", default=str(dataset.CSV_PADRAO))
    parser.add_argument("--saida", default=None, help="JSONL da rodada (padrão: o próximo número)")
    parser.add_argument("--limite", type=int, default=None, help="usa só as N primeiras perguntas")
    parser.add_argument("--categoria", default=None)
    parser.add_argument("--paralelismo", type=int, default=4)
    parser.add_argument("--retomar", action="store_true", help="continua uma rodada existente")
    parser.add_argument(
        "--relatorio-de",
        default=None,
        metavar="RODADA.jsonl",
        help="não executa nada: só refaz a página de uma rodada já feita",
    )
    parser.add_argument("--pular-ragas", action="store_true", help="a etapa mais lenta da pontuação")
    parser.add_argument("--nao-abrir", action="store_true", help="não abre o navegador no fim")
    parser.add_argument("--mode", default=SearchMode.HYBRID.value, choices=[m.value for m in SearchMode])
    args = parser.parse_args()

    inicio = time.time()
    total_passos = 5 if args.relatorio_de else 6
    passo = 0

    if args.relatorio_de:
        bruta = Path(args.relatorio_de)
        # aceita tanto a rodada bruta quanto a já enriquecida
        bruta = Path(str(bruta).replace(".enriquecido", ""))
    else:
        bruta = Path(args.saida) if args.saida else _proximo_nome()
        passo += 1
        _passo(passo, total_passos, f"Executando o Agente Q&A → {bruta}")
        executar_rodada(bruta, args)

    if not bruta.exists():
        raise SystemExit(f"rodada não encontrada: {bruta}")

    passo += 1
    _passo(passo, total_passos, "Texto integral dos trechos e resposta sem o convite")
    enriquecido = bruta.with_suffix(".enriquecido.jsonl")
    resumo = enriquecer.enriquecer(bruta, enriquecido)
    print(f"  {resumo['registros']} registros, {resumo['trechos_sem_texto']} trechos sem texto")

    passo += 1
    _passo(passo, total_passos, "Abstenção nas perguntas-isca")
    contagem, linhas = metrics_abstencao.avaliar(enriquecido)
    metrics_abstencao.gravar(enriquecido, contagem, linhas)
    iscas = sum(contagem.values())
    if iscas:
        print(f"  {contagem['abstencao']}/{iscas} recusaram corretamente")

    passo += 1
    _passo(passo, total_passos, "RAGAS" + (" (pulado)" if args.pular_ragas else " — 10 a 20 min"))
    if not args.pular_ragas:
        pontuar_ragas(enriquecido)

    passo += 1
    _passo(passo, total_passos, "Detalhe por pergunta")
    csv_saida, _, quantas = export_detalhe.exportar(enriquecido)
    print(f"  {quantas} perguntas → {csv_saida}")

    passo += 1
    _passo(passo, total_passos, "Página de resultados")
    dados = Dados(enriquecido)
    pagina = bruta.with_suffix(".html")
    pagina.write_text(render(dados), encoding="utf-8", newline="\n")

    pos = dados.medias["trechos"]
    bruto = dados.medias["recuperados"]
    print(f"  precisão {pos['precisao']:.2f} · cobertura {pos['cobertura']:.2f} · acerto {pos['acerto']:.0%}")
    print(f"  (busca crua: precisão {bruto['precisao']:.2f} · cobertura {bruto['cobertura']:.2f})")

    print(f"\nPronto em {(time.time() - inicio) / 60:.0f} min — {pagina}")
    if not args.nao_abrir:
        webbrowser.open(pagina.resolve().as_uri())


if __name__ == "__main__":
    main()

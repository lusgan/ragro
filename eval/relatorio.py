"""Gera a página de resultados de uma rodada a partir dos arquivos dela.

A página é derivada, nunca escrita à mão: todo número sai dos artefatos da
rodada (`<rodada>.enriquecido.jsonl` e os arquivos de métrica ao lado dele).
É o que impede o relatório publicado de divergir dos dados depois de uma
mudança no sistema — refaz-se a rodada, roda-se este módulo, e a página
inteira acompanha.

Uso:
    python -m eval.relatorio eval/runs/rodada02.enriquecido.jsonl --saida pagina.html

Espera ter rodado antes, sobre o mesmo arquivo:
    eval.metrics_abstencao · eval.metrics_ragas · eval.export_detalhe

Nenhum número desta página diz se a resposta está *certa*: correção de
conteúdo do MCR é julgamento de especialista, e a página entrega o material
para ele (resposta, referência e seções recuperadas) em vez de um rótulo
automático.
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from eval.dataset import CATEGORIA_ABSTENCAO
from eval.metrics_retrieval import avaliar_registro, carregar_rodada, resumir

CATEGORIA_DESCRICAO = {
    "consulta_simples": "Fato único, numa seção só (taxa, prazo, definição)",
    "elegibilidade": "Quem se enquadra, quem é excluído",
    "limites_numericos": "Tetos, carências, bônus — maior risco de alucinação silenciosa",
    "comparacao_programas": "Duas seções na mesma resposta (Pronaf × Pronamp)",
    "referencia_cruzada": "A resposta depende de uma remissão a outra seção",
    CATEGORIA_ABSTENCAO: "Fora do escopo do MCR — a resposta certa é recusar",
}

CAT_CURTA = {
    "consulta_simples": "simples",
    "elegibilidade": "elegibilidade",
    "limites_numericos": "limites",
    "comparacao_programas": "comparação",
    "referencia_cruzada": "ref. cruzada",
    CATEGORIA_ABSTENCAO: "isca",
}

# Baseline apresentado na defesa de TCC-1: 7 consultas rotuladas à mão.
BASELINE_TCC1 = {"n": 7, "precisao": 0.45, "cobertura": 0.78}


def e(t) -> str:
    return html.escape(str(t)) if t is not None else ""


def n2(v) -> str:
    """Número no padrão brasileiro, que é como o texto do TCC vai citá-lo."""
    return f"{v:.2f}".replace(".", ",")


def milhar(v) -> str:
    """Separador de milhar em ponto, também no padrão brasileiro."""
    return f"{v:,.0f}".replace(",", ".")


class Dados:
    """Tudo o que a página precisa, lido uma vez."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.registros = carregar_rodada(caminho)
        base = str(caminho.with_suffix(""))
        self.abstencao = self._json(Path(base + ".abstencao.json"), {})
        self.detalhe = self._json(Path(base + ".detalhe.json"), [])

        self.medias = {
            estagio: resumir(self._resultados(estagio)) for estagio in ("recuperados", "trechos")
        }
        self.por_categoria = {
            estagio: self._por_categoria(estagio) for estagio in ("recuperados", "trechos")
        }

    @staticmethod
    def _json(caminho: Path, padrao):
        if not caminho.exists():
            return padrao
        return json.loads(caminho.read_text(encoding="utf-8"))

    def _resultados(self, estagio: str):
        return [
            r
            for reg in self.registros
            if not reg.get("erro") and (r := avaliar_registro(reg, estagio=estagio)) is not None
        ]

    def _por_categoria(self, estagio: str) -> dict[str, dict]:
        grupos = defaultdict(list)
        for r in self._resultados(estagio):
            grupos[r.categoria].append(r)
        return {c: resumir(v) for c, v in sorted(grupos.items())}

    # --- recortes usados no texto -------------------------------------

    @property
    def iscas(self) -> list[dict]:
        return [r for r in self.registros if r["categoria"] == CATEGORIA_ABSTENCAO]

    @property
    def mensuraveis(self) -> list[dict]:
        return [r for r in self.registros if r["categoria"] != CATEGORIA_ABSTENCAO]

    def contagem_categorias(self) -> Counter:
        return Counter(r["categoria"] for r in self.registros)

    def perdidas_pelo_juiz(self) -> list[dict]:
        """A busca trouxe a seção certa e o juiz descartou."""
        saida = []
        for reg in self.registros:
            bruto = avaliar_registro(reg, estagio="recuperados")
            pos = avaliar_registro(reg, estagio="trechos")
            if bruto and pos and bruto.acertou and not pos.acertou:
                saida.append(reg)
        return saida

    def falhas_de_busca(self) -> list[dict]:
        """A seção certa não apareceu em estágio nenhum."""
        return [
            reg
            for reg in self.registros
            if (b := avaliar_registro(reg, estagio="recuperados")) is not None and not b.acertou
        ]

    def latencias(self) -> dict:
        valores = [r["latencia_s"] for r in self.registros if r.get("latencia_s")]
        return {
            "media": statistics.fmean(valores),
            "mediana": statistics.median(valores),
            "max": max(valores),
        }

    def tamanho_trechos(self) -> dict:
        tam = [len(t.get("text") or "") for r in self.registros for t in (r.get("trechos") or [])]
        return {"media": statistics.fmean(tam), "max": max(tam)} if tam else {"media": 0, "max": 0}

    def ragas(self) -> dict:
        """Médias do RAGAS por categoria e no total, a partir do detalhe."""
        chaves = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
        grupos = defaultdict(list)
        for linha in self.detalhe:
            if all(isinstance(linha.get(k), (int, float)) for k in chaves):
                grupos[linha["categoria"]].append(linha)
        if not grupos:
            return {}
        todos = [linha for v in grupos.values() for linha in v]

        def medias(linhas):
            return {k: statistics.fmean(linha[k] for linha in linhas) for k in chaves}

        return {
            "por_categoria": {c: (len(v), medias(v)) for c, v in sorted(grupos.items())},
            "total": (len(todos), medias(todos)),
            "zeros_relevancia": sum(1 for linha in todos if linha["answer_relevancy"] == 0),
            "fidelidade_alta": sum(1 for linha in todos if linha["faithfulness"] >= 0.8),
            "fidelidade_baixa": sum(1 for linha in todos if linha["faithfulness"] < 0.5),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera a página de resultados de uma rodada.")
    parser.add_argument("rodada", help="JSONL enriquecido da rodada")
    parser.add_argument("--saida", required=True, help="arquivo .html a escrever")
    parser.add_argument("--titulo", default="Avaliação do RAGro")
    args = parser.parse_args()

    # Import tardio: a renderização importa deste módulo, e o ciclo só não é
    # problema porque ele acontece depois de `Dados` estar definido.
    from eval.relatorio_html import render

    dados = Dados(Path(args.rodada))
    pagina = render(dados, args.titulo)
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(pagina, encoding="utf-8", newline="\n")

    pos = dados.medias["trechos"]
    print(f"{len(dados.registros)} perguntas | precisão {pos['precisao']:.2f} | cobertura {pos['cobertura']:.2f}")
    print(f"→ {saida} ({saida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

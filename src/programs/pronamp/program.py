"""Adaptador do PRONAMP sobre o protocolo comum de `programs`.

O PRONAMP, ao contrário do PRONAF, não tem um ruleset transpilado de um
simulador oficial — não existe motor determinístico para reproduzir aqui.
Por isso este adaptador nunca inventa um número de crédito: `recomendar()`
devolve sempre `linhas=[]`, e em vez de limite/juros/prazo devolve uma
consulta e um filtro de seções do MCR (8-1, que rege o programa, e 7-4, seus
encargos e limites gerais) para a busca híbrida fundamentar a resposta no
texto oficial. O questionário em si é só declarativo (`perguntas.json`) —
não há árvore de elegibilidade porque não há linha a filtrar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.programs.base import Opcao, Pergunta, Recomendacao

PERGUNTAS_PATH = Path(__file__).with_name("perguntas.json")


def _dados() -> dict[str, Any]:
    with PERGUNTAS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _preenchido(valor: Any, multipla: bool, vocab: list[str]) -> bool:
    if multipla:
        return isinstance(valor, list) and any(v in vocab for v in valor)
    return isinstance(valor, str) and valor in vocab


class ProgramaPronamp:
    id = "pronamp"
    nome = "PRONAMP — Programa Nacional de Apoio ao Médio Produtor Rural"

    def vocabulario(self) -> dict[str, list[str]]:
        return {
            chave: [o["v"] for o in pergunta["opcoes"]]
            for chave, pergunta in _dados()["perguntas"].items()
        }

    def proxima_pergunta(self, respostas: dict) -> Pergunta | None:
        dados = _dados()
        perguntas = dados["perguntas"]
        for chave in dados["ordem_perguntas"]:
            pergunta = perguntas[chave]
            vocab = [o["v"] for o in pergunta["opcoes"]]
            if _preenchido(respostas.get(chave), pergunta["multipla"], vocab):
                continue
            return Pergunta(
                id=chave,
                texto=pergunta["texto"],
                multipla=pergunta["multipla"],
                opcoes=[Opcao(v=o["v"], t=o["l"]) for o in pergunta["opcoes"]],
            )
        return None

    def recomendar(self, respostas: dict) -> Recomendacao:
        dados = _dados()
        partes = []
        for chave in dados["ordem_perguntas"]:
            valor = respostas.get(chave)
            if not valor:
                continue
            texto = ", ".join(valor) if isinstance(valor, list) else str(valor)
            partes.append(f"{chave}: {texto}")
        consulta_rag = "PRONAMP — " + "; ".join(partes) if partes else "PRONAMP"

        return Recomendacao(
            programa=self.id,
            linhas=[],
            consulta_rag=consulta_rag,
            # Cap. 8 é o PRONAMP; Cap. 7 seção 4 são seus encargos e limites gerais.
            secoes_mcr=[{"capitulo_num": 8}, {"capitulo_num": 7, "secao_label": "4"}],
            perfil=dict(respostas),
            fonte=dados["fonte"],
            observacao=(
                "O PRONAMP não tem ruleset offline: limite, juros, prazo e carência "
                "vêm do texto do MCR recuperado por busca, não deste programa."
            ),
        )

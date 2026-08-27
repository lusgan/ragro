"""Adaptador do PRONAF sobre o protocolo comum de `programs`.

Este módulo não decide nada sozinho — ele só traduz entre o formato do
`engine` (voltado para o simulador oficial do MDA, com um `Perfil` estrito)
e o protocolo `Programa` que o Agente Conselheiro conhece. A parte que exige
cuidado é `proxima_pergunta`: no meio do questionário o perfil está sempre
incompleto, e `engine._perfil_de` é estrito de propósito (existe para a
recomendação final, onde um valor fora do vocabulário é um perfil errado, não
incompleto). Por isso este adaptador constrói o `Perfil` de forma leniente —
slot ausente ou valor fora do vocabulário é só ignorado, e a pergunta
correspondente volta a ser feita, em vez de derrubar o questionário.
"""

from __future__ import annotations

from typing import Any

from src.programs.base import Opcao, Pergunta, Recomendacao, RespostasInvalidas
from src.programs.pronaf import engine


def _valores(chave: str) -> list[str]:
    return [o["v"] for o in engine.ruleset()["perguntas"][chave]["opcoes"]]


def _escolha(respostas: dict[str, Any], slot: str, vocab_chave: str) -> str | None:
    valor = respostas.get(slot)
    return valor if isinstance(valor, str) and valor in _valores(vocab_chave) else None


def _lista(respostas: dict[str, Any], slot: str, vocab_chave: str) -> list[str]:
    valor = respostas.get(slot)
    if not isinstance(valor, list):
        return []
    vocab = _valores(vocab_chave)
    # Preserva a ordem do questionário, como o engine faz na validação estrita.
    return [v for v in vocab if v in valor]


def _perfil_leniente(respostas: dict[str, Any]) -> engine.Perfil:
    """Perfil parcial: entradas fora do vocabulário são ignoradas, não rejeitadas."""
    tipo = _escolha(respostas, "tipo", "tipo")
    regiao = _escolha(respostas, "regiao", "regiao")

    if tipo == "cooperativa":
        return engine.Perfil(
            tipo=tipo,
            coop_perfil=_escolha(respostas, "coop_perfil", "coop_perfil"),
            finalidade=_lista(respostas, "finalidade", "finalidade_coop"),
            regiao=regiao,
        )

    finalidade = _lista(respostas, "finalidade", "finalidade_pf") if tipo == "individual" else []
    organico = _escolha(respostas, "organico", "organico") if "custeio" in finalidade else None

    return engine.Perfil(
        tipo=tipo,
        renda=_escolha(respostas, "renda", "renda") if tipo == "individual" else None,
        perfil=_lista(respostas, "perfil", "perfil") if tipo == "individual" else [],
        finalidade=finalidade,
        organico=organico,
        regiao=regiao,
    )


# Chaves de pergunta do ruleset que não correspondem 1:1 a um slot: PF e
# cooperativa têm perguntas de finalidade separadas, mas o slot é o mesmo.
_SLOT_DE_PERGUNTA = {
    "finalidade_pf": "finalidade",
    "finalidade_coop": "finalidade",
}


class ProgramaPronaf:
    id = "pronaf"
    nome = "PRONAF — Programa Nacional de Fortalecimento da Agricultura Familiar"

    def vocabulario(self) -> dict[str, list[str]]:
        """Deriva o vocabulário do ruleset — nunca uma cópia à mão, para acompanhá-lo."""
        vocab: dict[str, list[str]] = {}
        for chave, pergunta in engine.ruleset()["perguntas"].items():
            slot = _SLOT_DE_PERGUNTA.get(chave, chave)
            valores = vocab.setdefault(slot, [])
            for opcao in pergunta["opcoes"]:
                if opcao["v"] not in valores:
                    valores.append(opcao["v"])
        return vocab

    def proxima_pergunta(self, respostas: dict) -> Pergunta | None:
        p = _perfil_leniente(respostas)
        q = engine.proxima_pergunta(p)
        if q is None:
            return None
        return Pergunta(
            id=q["id"],
            texto=q["texto"],
            multipla=q["multipla"],
            opcoes=[Opcao(v=o["v"], t=o["l"]) for o in q["opcoes"]],
        )

    def recomendar(self, respostas: dict) -> Recomendacao:
        try:
            resultado = engine.recomendar(respostas)
        except engine.PerfilInvalido as e:
            raise RespostasInvalidas(str(e)) from e

        nomes = [linha["nome"] for linha in resultado["linhas"]]
        consulta_rag = (
            f"PRONAF — linhas recomendadas: {', '.join(nomes)}"
            if nomes
            else "PRONAF — nenhuma linha elegível para o perfil informado"
        )

        return Recomendacao(
            programa=self.id,
            linhas=resultado["linhas"],
            consulta_rag=consulta_rag,
            # Cap. 10 é o PRONAF; Cap. 7 seção 6 são seus encargos e limites gerais.
            secoes_mcr=[{"capitulo_num": 10}, {"capitulo_num": 7, "secao_label": "6"}],
            perfil=resultado["perfil_avaliado"],
            fonte=resultado["fonte"],
            observacao=None,
        )

"""Protocolo comum aos programas de crédito rural (PRONAF, PRONAMP, ...).

Por que um protocolo: o Agente Conselheiro conduz o questionário e monta a
recomendação sem conhecer PRONAF nem PRONAMP diretamente — ele fala só com
esta interface. Isso é o que permite trocar ou adicionar um programa sem
mexer no agente, e é o que sustenta a regra fundamental do projeto: nenhum
número de crédito sai do LLM. Quem tem ruleset (PRONAF) devolve `linhas` já
resolvidas pelo engine; quem não tem (PRONAMP) devolve sempre `linhas=[]` e
uma consulta + filtro de seções do MCR para fundamentar a resposta via RAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Opcao:
    """Uma opção de resposta para uma pergunta do questionário."""

    v: str
    t: str


@dataclass(frozen=True)
class Pergunta:
    """Uma pergunta do questionário, pronta para o LLM reformular em PT-BR natural."""

    id: str
    texto: str
    multipla: bool
    opcoes: list[Opcao]


@dataclass(frozen=True)
class Slot:
    """Um campo do questionário, do ponto de vista de quem preenche.

    `multipla` importa tanto quanto `valores`: é ela que decide se o schema de
    extração pede uma string ou uma lista ao LLM. Sem isso exposto aqui, a
    única forma de descobrir a multiplicidade de um slot seria percorrer o
    questionário inteiro atrás das perguntas — trabalho para redescobrir um
    dado que o ruleset já declara.
    """

    valores: list[str]
    multipla: bool


@dataclass(frozen=True)
class Recomendacao:
    """Resultado de `recomendar()` — o que o Agente Conselheiro usa para redigir."""

    programa: str
    linhas: list[dict]        # PRONAF: linhas resolvidas pelo engine. PRONAMP: [] sempre.
    consulta_rag: str         # consulta para a busca híbrida que fundamenta a resposta
    secoes_mcr: list[dict]    # filtro de metadados, ex.: [{"capitulo_num": 10}]
    perfil: dict
    fonte: str
    observacao: str | None


class RespostasInvalidas(ValueError):
    """Respostas que não formam um perfil avaliável pelo programa."""


class Programa(Protocol):
    id: str
    nome: str

    def slots(self) -> dict[str, Slot]:
        """Slot -> valores aceitos e multiplicidade. Base do JSON schema da
        extração por LLM."""
        ...

    def vocabulario(self) -> dict[str, list[str]]:
        """Slot -> valores aceitos. Derivado de `slots()`, nunca mantido à parte."""
        ...

    def proxima_pergunta(self, respostas: dict) -> Pergunta | None:
        """Próxima pergunta a conduzir, ou None quando o perfil está completo."""
        ...

    def recomendar(self, respostas: dict) -> Recomendacao:
        """Levanta `RespostasInvalidas` se as respostas não formarem um perfil avaliável."""
        ...

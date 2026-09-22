"""Tipos compartilhados pelo orquestrador e pelos agentes.

Ficam num módulo próprio (em vez de em cada agente) porque `orchestrator.py`,
`qa.py` e `advisor.py` trocam os mesmos tipos entre si — `Rota` sai do
orquestrador e é consumida por quem chama; `Resposta` sai dos dois agentes e
é o formato único que o frontend (numa fase posterior) precisa entender.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.programs.base import Pergunta


@dataclass(frozen=True)
class Rota:
    """Decisão do orquestrador sobre qual agente atende o turno."""

    agente: Literal["qa", "conselheiro"]
    motivo: str
    fonte: Literal["sticky", "llm", "fallback"]  # de onde veio a decisão, para depuração
    # O usuário saiu de uma sessão aberta do conselheiro: quem chama grava
    # `advisor.suspender(estado)`, já que o Q&A nunca devolve estado.
    suspender_sessao: bool = False


@dataclass(frozen=True)
class Resposta:
    """Saída comum aos dois agentes, pronta para o frontend renderizar e persistir."""

    texto: str
    agente: str
    trechos: list[dict]      # snapshot JSON-serializável, pronto para persistir
    estado: dict | None      # novo advisor_state a gravar (None = nada a gravar)
    pergunta: Pergunta | None  # pergunta pendente, para o frontend renderizar as opções

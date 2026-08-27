"""Registro dos programas de crédito rural disponíveis ao Agente Conselheiro.

Importável sem efeitos colaterais além de instanciar os dois adaptadores —
nada de rede, banco ou variável de ambiente aqui. `tests/test_pronaf_engine.py`
importa `src.programs.pronaf.engine`, o que dispara este pacote inteiro; ele
precisa continuar rápido e offline.
"""

from __future__ import annotations

from src.programs.base import Programa
from src.programs.pronaf.program import ProgramaPronaf
from src.programs.pronamp.program import ProgramaPronamp

_REGISTRO: dict[str, Programa] = {
    "pronaf": ProgramaPronaf(),
    "pronamp": ProgramaPronamp(),
}


def obter(programa_id: str) -> Programa:
    """Devolve o adaptador do programa, ou levanta erro claro se o id não existir."""
    try:
        return _REGISTRO[programa_id]
    except KeyError:
        raise KeyError(
            f"programa {programa_id!r} não existe. Disponíveis: {', '.join(ids())}."
        ) from None


def ids() -> list[str]:
    return list(_REGISTRO.keys())

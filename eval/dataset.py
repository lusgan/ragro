"""Carrega o conjunto-padrão curado e monta o gabarito de recuperação.

A curadoria (a planilha exportada em `data/Questions_to_eval/`) é o que torna
este conjunto utilizável como ground truth: as candidatas geradas por LLM
apontavam o capítulo *do assunto* da pergunta, não necessariamente a seção
onde a resposta está — um limite do Pronaf pode morar numa seção de limites,
separada da seção principal do programa. Só as linhas marcadas como
`Questão Verificada` entram na avaliação.

O gabarito de recuperação sai de `referencias_mcr` ("MCR 10-2; MCR 8-1"), e
não das colunas `capitulo`/`secao`, que guardam apenas a fonte principal. Um
trecho recuperado conta como relevante quando o par (capítulo, seção) do
payload está nesse conjunto — comparação exata, porque no índice atual cada
chunk corresponde a uma seção do manual.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

CSV_PADRAO = Path("data/Questions_to_eval/candidatas_curadas.csv")

# Marca da primeira coluna (sem cabeçalho na planilha) que o autor usou para
# registrar a curadoria. Linhas com qualquer outro valor — inclusive
# "Inconclusivo" — ficam de fora.
MARCA_VERIFICADA = "Questão Verificada"

# "MCR 10-18-5" → capítulo 10, seção 18: o terceiro número é o item dentro da
# seção, e o índice não chega nesse nível (um chunk é uma seção inteira).
REFERENCIA_MCR = re.compile(r"MCR\s*(\d+)\s*-\s*(\d+)")

CATEGORIA_ABSTENCAO = "abstencao"


@dataclass(frozen=True)
class Questao:
    id: str
    categoria: str
    pergunta: str
    referencias: frozenset[tuple[int, str]]  # (capitulo, secao) — vazio em abstenção
    resposta_referencia: str
    referencias_texto: str

    @property
    def eh_abstencao(self) -> bool:
        return self.categoria == CATEGORIA_ABSTENCAO


def _parse_referencias(texto: str | None) -> frozenset[tuple[int, str]]:
    return frozenset(
        (int(capitulo), secao) for capitulo, secao in REFERENCIA_MCR.findall(texto or "")
    )


def carregar(caminho: Path | str = CSV_PADRAO, *, apenas_verificadas: bool = True) -> list[Questao]:
    """Lê o CSV curado. `utf-8-sig` porque a exportação do Sheets/Excel traz BOM."""
    with io.open(caminho, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))

    questoes = []
    for linha in linhas:
        marca = (linha.get("") or "").strip()
        if apenas_verificadas and marca != MARCA_VERIFICADA:
            continue
        questoes.append(
            Questao(
                id=linha["id"],
                categoria=linha["categoria"],
                pergunta=linha["pergunta"],
                referencias=_parse_referencias(linha.get("referencias_mcr")),
                resposta_referencia=(linha.get("resposta_rascunho") or "").strip(),
                referencias_texto=(linha.get("referencias_mcr") or "").strip(),
            )
        )
    return questoes


def validar(questoes: list[Questao], secoes_indexadas: set[tuple[int, str]]) -> list[str]:
    """Problemas que invalidariam o gabarito, para falhar cedo em vez de
    produzir uma métrica silenciosamente errada: pergunta sem referência
    nenhuma, ou referência para uma seção que não está no índice (nesse caso
    a cobertura seria 0 por construção, e não por falha do retriever).
    """
    problemas = []
    for q in questoes:
        if q.eh_abstencao:
            continue
        if not q.referencias:
            problemas.append(f"{q.id}: sem referência MCR utilizável em '{q.referencias_texto}'")
            continue
        fora = q.referencias - secoes_indexadas
        if fora:
            alvos = ", ".join(f"MCR {c}-{s}" for c, s in sorted(fora))
            problemas.append(f"{q.id}: referência fora do índice ({alvos})")
    return problemas

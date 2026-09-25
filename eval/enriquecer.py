"""Prepara uma rodada para a pontuação de geração: texto integral dos trechos
e resposta sem o convite de handoff.

Duas correções, as duas sobre o que o juiz enxerga — nenhuma delas muda a
resposta que o sistema gerou:

1. **Texto integral.** `rag/snapshot.py` trunca o texto em 1500 caracteres,
   porque foi escrito para persistir o histórico no Postgres. O gerador, esse,
   recebe a seção inteira (chegam a ~9500 caracteres). Pontuar fidelidade
   contra o texto truncado conta como alucinação toda afirmação tirada dos
   outros quatro quintos da seção. Aqui o texto completo é buscado de volta no
   Qdrant pelo id do ponto, então não é preciso gerar as respostas de novo.

2. **Sem o call-to-action.** O Q&A fecha cada resposta convidando o usuário a
   contar renda, produção e região, para acionar o Agente Conselheiro. Esse
   parágrafo não afirma nada sobre o MCR e não tem como ser sustentado por
   trecho nenhum — medido junto, ele cobra da fidelidade um comportamento
   intencional do produto. O texto original fica guardado em
   `resposta_original`, para a ablação continuar possível.

Uso:
    python -m eval.enriquecer eval/runs/rodada01.jsonl
    → eval/runs/rodada01.enriquecido.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import src.config  # noqa: F401 — carrega .env antes de qualquer getenv
from src.rag import qdrant

# O convite sempre fecha a resposta e sempre pede os mesmos dados — é o que
# `answer.CTA_INSTRUCTION` manda o modelo fazer. Casar os dois sinais (renda ou
# situação, mais produção ou região) evita cortar um parágrafo que só por acaso
# fale de renda, que é assunto legítimo de metade das perguntas.
_PEDE_PERFIL = re.compile(r"renda|situa[çc][ãa]o", re.I)
_PEDE_CONTEXTO = re.compile(r"produz|produ[çc][ãa]o|regi[ãa]o", re.I)


def remover_cta(resposta: str) -> str:
    """Remove os parágrafos finais de convite. Nunca devolve string vazia: se
    a heurística consumir a resposta inteira, ela é preservada como estava —
    melhor uma medida com convite do que uma resposta fantasma."""
    partes = [p for p in resposta.split("\n\n") if p.strip()]
    while partes and _PEDE_PERFIL.search(partes[-1]) and _PEDE_CONTEXTO.search(partes[-1]):
        partes.pop()
    limpa = "\n\n".join(partes).strip()
    # O separador markdown que o modelo costuma pôr antes do convite fica órfão.
    limpa = re.sub(r"\n+-{3,}\s*$", "", limpa).strip()
    return limpa or resposta


def _id_qdrant(id_: str) -> int | str:
    """O JSONL guarda o id como string (JSON não tem inteiro de 64 bits
    garantido), mas o Qdrant só aceita inteiro sem sinal ou UUID."""
    return int(id_) if id_.isdigit() else id_


def textos_completos(ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    client = qdrant.get_client()
    pontos = client.retrieve(
        collection_name=qdrant.COLLECTION_NAME,
        ids=[_id_qdrant(i) for i in {i for i in ids}],
        with_payload=True,
        with_vectors=False,
    )
    return {str(p.id): (p.payload or {}).get("text") or "" for p in pontos}


def enriquecer(entrada: Path, saida: Path) -> dict:
    registros = [json.loads(l) for l in open(entrada, encoding="utf-8") if l.strip()]

    ids = [t["id"] for r in registros for campo in ("trechos", "recuperados") for t in (r.get(campo) or [])]
    completos = textos_completos(ids)

    faltando = 0
    cortadas = 0
    for r in registros:
        for campo in ("trechos", "recuperados"):
            for t in r.get(campo) or []:
                texto = completos.get(t["id"])
                if texto:
                    t["text"] = texto
                else:
                    faltando += 1
        if r.get("resposta"):
            r["resposta_original"] = r["resposta"]
            r["resposta"] = remover_cta(r["resposta"])
            if len(r["resposta"]) < len(r["resposta_original"]):
                cortadas += 1

    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "w", encoding="utf-8", newline="\n") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "registros": len(registros),
        "trechos_sem_texto": faltando,
        "respostas_com_cta_removido": cortadas,
        "com_resposta": sum(1 for r in registros if r.get("resposta")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Texto integral dos trechos e resposta sem CTA.")
    parser.add_argument("rodada")
    parser.add_argument("--saida", default=None)
    args = parser.parse_args()

    entrada = Path(args.rodada)
    saida = Path(args.saida) if args.saida else entrada.with_suffix(".enriquecido.jsonl")
    resumo = enriquecer(entrada, saida)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    print(f"→ {saida}")


if __name__ == "__main__":
    main()

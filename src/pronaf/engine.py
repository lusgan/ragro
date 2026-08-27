"""Motor de elegibilidade do PRONAF.

Reproduz, de forma determinística e offline, a árvore de decisão do simulador
oficial do MDA (https://simuladorpronaf.mda.gov.br/). As regras vivem em
``ruleset.json``, gerado por ``scripts/extract_pronaf.py`` a partir do HTML do
simulador — este módulo apenas as interpreta.

Uso típico (a IA conduz a conversa; a elegibilidade é decidida aqui):

    perfil = Perfil(tipo="individual", renda="ate60k", perfil=["mulher"],
                    finalidade=["custeio"], organico="sim", regiao="ne")
    for linha in avaliar(perfil):
        print(linha.nome, linha.limite, linha.juros_aa_pct)
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

RULESET_PATH = Path(__file__).with_name("ruleset.json")


@lru_cache(maxsize=1)
def ruleset() -> dict[str, Any]:
    with RULESET_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Perfil:
    """Respostas do questionário. Campos vazios ainda não foram perguntados."""

    tipo: str | None = None              # individual | cooperativa
    renda: str | None = None             # ate60k | ate150k | ate500k | ate714k | nenhuma
    perfil: list[str] = field(default_factory=list)      # mulher | geral | jovem | assentado
    finalidade: list[str] = field(default_factory=list)  # custeio | maquinas | ...
    organico: str | None = None          # sim | alimentos | soja_corte | outros_custeio
    regiao: str | None = None            # no | ne | co | se | su
    coop_perfil: str | None = None       # coop_aac | coop_geral
    sudene_municipio_ok: bool = False

    def as_state(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "renda": self.renda,
            "perfil": list(self.perfil),
            "finalidade": list(self.finalidade),
            "organico": self.organico,
            "regiao": self.regiao,
            "coop_perfil": self.coop_perfil,
            "sudene_municipio_ok": self.sudene_municipio_ok,
            # Pergunta desativada no simulador oficial; mantida para paridade de AST.
            "producao": None,
        }


@dataclass
class Linha:
    """Linha de crédito elegível, já resolvida para o perfil informado."""

    id: str
    nome: str
    grupo_pronaf: str
    grupo_finalidade: str
    limite: str | None
    limite_mil_reais: float | None
    juros_aa_pct: float | None
    prazo_anos: float | None
    carencia_anos: float | None
    prazo_texto: str | None
    carencia_texto: str | None
    bonus_adimplencia: str | None
    observacao: str | None
    destaque: bool
    bancos: list[str]


# --- avaliador da AST de elegibilidade -------------------------------------

_RENDA_EQUIVALENTE = {"ate714k": "ate500k"}


def _valor(node: dict[str, Any], s: dict[str, Any]) -> Any:
    op = node["op"]
    if op == "campo":
        return s.get(node["campo"])
    if op == "renda_equivalente":
        renda = s.get("renda")
        return _RENDA_EQUIVALENTE.get(renda, renda)
    return _avaliar_ast(node, s)


def _avaliar_ast(node: dict[str, Any], s: dict[str, Any]) -> bool:
    op = node["op"]
    if op == "const":
        return bool(node["valor"])
    if op == "e":
        return _avaliar_ast(node["args"][0], s) and _avaliar_ast(node["args"][1], s)
    if op == "ou":
        return _avaliar_ast(node["args"][0], s) or _avaliar_ast(node["args"][1], s)
    if op == "nao":
        return not _avaliar_ast(node["arg"], s)
    if op == "truthy":
        return bool(_valor(node["arg"], s))
    if op == "contem":
        valores = s.get(node["campo"])
        return isinstance(valores, list) and node["valor"] in valores
    if op == "tem_finalidade_alem_de":
        fins = s.get("finalidade")
        return isinstance(fins, list) and any(f != node["valor"] for f in fins)
    if op == "tem_alguma_finalidade":
        fins = s.get("finalidade")
        return isinstance(fins, list) and len(fins) > 0
    if op == "igual":
        return _valor(node["arg"], s) == node["valor"]
    if op == "diferente":
        return _valor(node["arg"], s) != node["valor"]
    return bool(_valor(node, s))


def _resolver(campo: dict[str, Any], regiao: str | None) -> Any:
    """Campos que o simulador calcula em função do estado (ex.: bônus por região)."""
    if campo["tipo"] == "fixo":
        return campo["valor"]
    return campo["valor"].get(regiao)


def bancos_para(grupo_pronaf: str, regiao: str | None) -> list[str]:
    """Porte de getBancosPorLinha() do simulador oficial."""
    if grupo_pronaf == "Pronaf B" or grupo_pronaf in ("Pronaf A/A-C", "Pronaf A e A/C"):
        return {
            "no": ["BB", "CEF", "BASA"],
            "ne": ["BB", "CEF", "BNB"],
            "se": ["BB", "CEF", "BNB_SE"],
        }.get(regiao, ["BB", "CEF"])
    if regiao == "no":
        return ["BB", "CEF", "BASA", "SICOOB", "SICREDI", "CRESOL"]
    if regiao == "ne":
        return ["BB", "CEF", "BNB", "SICOOB", "SICREDI", "CRESOL"]
    if regiao == "co":
        return ["BB", "CEF", "BASA", "SICOOB", "SICREDI", "CRESOL", "BRB"]
    if regiao == "se":
        return ["BB", "CEF", "BNB_SE", "SICOOB", "SICREDI", "CRESOL"]
    if regiao == "su":
        sul = ["BB", "CEF", "SICOOB", "SICREDI", "CRESOL", "BANRISUL"]
        e_custeio = any(t in grupo_pronaf for t in ("Faixa", "Industrialização", "Custeio"))
        return sul if e_custeio else [*sul, "BRDE"]
    return ["BB", "CEF", "SICOOB", "SICREDI", "CRESOL"]


def avaliar(p: Perfil) -> list[Linha]:
    """Linhas de crédito elegíveis para o perfil, na ordem do simulador oficial."""
    s = p.as_state()
    escopo = "cooperativa" if p.tipo == "cooperativa" else "individual"
    out: list[Linha] = []
    for raw in ruleset()["linhas"]:
        if raw["escopo"] != escopo or not _avaliar_ast(raw["elegibilidade"], s):
            continue
        out.append(
            Linha(
                id=raw["id"],
                nome=raw["nome"],
                grupo_pronaf=raw["grupo_pronaf"],
                grupo_finalidade=raw["grupo_finalidade"],
                limite=_resolver(raw["limite"], p.regiao),
                limite_mil_reais=_resolver(raw["limite_mil_reais"], p.regiao),
                juros_aa_pct=raw["juros_aa_pct"],
                prazo_anos=raw["prazo_anos"],
                carencia_anos=raw["carencia_anos"],
                prazo_texto=raw["prazo_texto"],
                carencia_texto=raw["carencia_texto"],
                bonus_adimplencia=_resolver(raw["bonus_adimplencia"], p.regiao),
                observacao=_resolver(raw["observacao"], p.regiao),
                destaque=raw["destaque"],
                bancos=bancos_para(raw["grupo_pronaf"], p.regiao),
            )
        )
    return out


# --- condução do questionário ----------------------------------------------


def proxima_pergunta(p: Perfil) -> dict[str, Any] | None:
    """Próxima pergunta a fazer, ou None quando o perfil está completo.

    Reproduz getVis()/getCur() (pessoa física) e getCurCoop() (cooperativa).
    """
    perguntas = ruleset()["perguntas"]

    def pack(qid: str, chave: str) -> dict[str, Any]:
        q = perguntas[chave]
        return {"id": qid, "texto": q["texto"], "multipla": q["multipla"], "opcoes": q["opcoes"]}

    if p.tipo is None:
        return pack("tipo", "tipo")
    if p.tipo == "cooperativa":
        if p.coop_perfil is None:
            return pack("coop_perfil", "coop_perfil")
        if not p.finalidade:
            return pack("finalidade", "finalidade_coop")
        if p.regiao is None:
            return pack("regiao", "regiao")
        return None
    if p.renda is None:
        return pack("renda", "renda")
    if not p.perfil:
        return pack("perfil", "perfil")
    if not p.finalidade:
        return pack("finalidade", "finalidade_pf")
    if "custeio" in p.finalidade and p.organico is None:
        return pack("organico", "organico")
    if p.regiao is None:
        return pack("regiao", "regiao")
    return None


def _norm(x: str) -> str:
    x = unicodedata.normalize("NFD", x)
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return " ".join(x.lower().split())


def municipio_sudene(uf: str, nome: str) -> bool:
    """True se o município integra a área da Sudene (só relevante em MG/ES)."""
    lista = ruleset()["municipios_sudene"].get(uf.lower(), [])
    return _norm(nome) in {_norm(m) for m in lista}


# --- entrada e saída em JSON ------------------------------------------------
#
# `recomendar()` é a superfície que o resto do sistema (e o tool call do Gemini)
# consome: um dicionário com as respostas entra, as linhas recomendadas saem.
# Ela é deliberadamente estrita. Um perfil com `renda: "60000"` ou
# `finalidade: ["trator"]` não é um perfil incompleto — é um perfil errado, e
# devolver linhas para ele seria pior do que falhar, porque o número sai com
# cara de resposta oficial. Todo valor é conferido contra o vocabulário do
# ruleset antes de qualquer avaliação.


class PerfilInvalido(ValueError):
    """Respostas que não descrevem um perfil avaliável."""


def _vocabulario(chave: str) -> list[str]:
    return [o["v"] for o in ruleset()["perguntas"][chave]["opcoes"]]


_CAMPOS_ACEITOS = {
    "tipo", "renda", "perfil", "finalidade", "organico", "regiao",
    "coop_perfil", "municipio", "sudene_municipio_ok",
}


def _exigir_escolha(valor: Any, campo: str, vocab: list[str]) -> str:
    if valor is None:
        raise PerfilInvalido(f"'{campo}' é obrigatório. Valores aceitos: {', '.join(vocab)}.")
    if valor not in vocab:
        raise PerfilInvalido(
            f"'{campo}' recebeu {valor!r}, que não é uma opção. "
            f"Valores aceitos: {', '.join(vocab)}."
        )
    return valor


def _exigir_lista(valor: Any, campo: str, vocab: list[str]) -> list[str]:
    if isinstance(valor, str):
        raise PerfilInvalido(f"'{campo}' é múltipla escolha: use uma lista, não {valor!r}.")
    if not valor:
        raise PerfilInvalido(
            f"'{campo}' precisa de ao menos uma opção. Valores aceitos: {', '.join(vocab)}."
        )
    invalidos = [v for v in valor if v not in vocab]
    if invalidos:
        raise PerfilInvalido(
            f"'{campo}' recebeu {', '.join(map(repr, invalidos))}, que não "
            f"{'são opções' if len(invalidos) > 1 else 'é uma opção'}. "
            f"Valores aceitos: {', '.join(vocab)}."
        )
    # Preserva a ordem do questionário; a avaliação usa pertinência, não ordem.
    return [v for v in vocab if v in valor]


def _perfil_de(respostas: dict[str, Any]) -> Perfil:
    desconhecidos = set(respostas) - _CAMPOS_ACEITOS
    if desconhecidos:
        raise PerfilInvalido(
            f"campos não reconhecidos: {', '.join(sorted(desconhecidos))}. "
            f"Campos aceitos: {', '.join(sorted(_CAMPOS_ACEITOS))}."
        )

    tipo = _exigir_escolha(respostas.get("tipo"), "tipo", _vocabulario("tipo"))
    regiao = _exigir_escolha(respostas.get("regiao"), "regiao", _vocabulario("regiao"))

    if tipo == "cooperativa":
        return Perfil(
            tipo=tipo,
            coop_perfil=_exigir_escolha(
                respostas.get("coop_perfil"), "coop_perfil", _vocabulario("coop_perfil")
            ),
            finalidade=_exigir_lista(
                respostas.get("finalidade"), "finalidade", _vocabulario("finalidade_coop")
            ),
            regiao=regiao,
        )

    finalidade = _exigir_lista(
        respostas.get("finalidade"), "finalidade", _vocabulario("finalidade_pf")
    )
    organico = respostas.get("organico")
    if "custeio" in finalidade:
        organico = _exigir_escolha(organico, "organico", _vocabulario("organico"))
    elif organico is not None:
        # Sem custeio a pergunta nem é feita; aceitar o valor mascararia um
        # perfil montado errado.
        raise PerfilInvalido("'organico' só se aplica quando 'finalidade' inclui 'custeio'.")

    return Perfil(
        tipo=tipo,
        renda=_exigir_escolha(respostas.get("renda"), "renda", _vocabulario("renda")),
        perfil=_exigir_lista(respostas.get("perfil"), "perfil", _vocabulario("perfil")),
        finalidade=finalidade,
        organico=organico,
        regiao=regiao,
        sudene_municipio_ok=_sudene_de(respostas, regiao),
    )


def _sudene_de(respostas: dict[str, Any], regiao: str | None) -> bool:
    """Resolve a checagem de município da Sudene, que só existe no Sudeste.

    As linhas do Semiárido valem no Nordeste inteiro, mas no Sudeste dependem do
    município estar na área da Sudene (norte de MG e ES). Aceita a flag pronta
    ou `{"uf": "mg", "nome": "Montes Claros"}` para resolver aqui.
    """
    if "sudene_municipio_ok" in respostas:
        return bool(respostas["sudene_municipio_ok"])
    municipio = respostas.get("municipio")
    if not municipio:
        return False
    if not isinstance(municipio, dict) or "uf" not in municipio or "nome" not in municipio:
        raise PerfilInvalido("'municipio' deve ser {'uf': 'mg'|'es', 'nome': '<município>'}.")
    if regiao != "se":
        return False
    return municipio_sudene(str(municipio["uf"]), str(municipio["nome"]))


def recomendar(respostas: dict[str, Any]) -> dict[str, Any]:
    """Recebe as respostas do questionário e devolve as linhas recomendadas.

    Levanta `PerfilInvalido` se as respostas não formarem um perfil avaliável —
    quem chama decide se converte isso em nova pergunta ao usuário.
    """
    p = _perfil_de(respostas)
    rs = ruleset()
    nomes = rs["bancos"]["nomes"]
    obs_banco = rs["bancos"]["observacoes"]

    def banco(sigla: str) -> dict[str, Any]:
        # BNB_SE é o mesmo Banco do Nordeste, restrito à faixa Sudene do Sudeste.
        base = nomes.get(sigla) or nomes.get(sigla.split("_")[0]) or sigla
        return {"sigla": sigla, "nome": base, "observacao": obs_banco.get(sigla)}

    linhas = [
        {
            "id": l.id,
            "nome": l.nome,
            "grupo_pronaf": l.grupo_pronaf,
            "finalidade": l.grupo_finalidade,
            "limite": l.limite,
            "limite_mil_reais": l.limite_mil_reais,
            "juros_aa_pct": l.juros_aa_pct,
            "prazo": l.prazo_texto,
            "prazo_anos": l.prazo_anos,
            "carencia": l.carencia_texto,
            "carencia_anos": l.carencia_anos,
            "bonus_adimplencia": l.bonus_adimplencia,
            "observacao": l.observacao,
            "destaque": l.destaque,
            "bancos": [banco(s) for s in l.bancos],
        }
        for l in avaliar(p)
    ]

    return {
        "total": len(linhas),
        "linhas": linhas,
        "perfil_avaliado": p.as_state(),
        "fonte": rs["fonte"],
        "plano_safra": rs["plano_safra"],
    }

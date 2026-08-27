"""
Testes de `src/programs/`: o registro, os adaptadores e a triagem.

Tudo aqui roda offline — sem banco, sem rede, sem LLM. O que está em jogo é a
regra fundamental do projeto (nenhum número de crédito sai do LLM): o PRONAF
precisa terminar o questionário e devolver linhas resolvidas pelo engine; o
PRONAMP precisa nunca devolver uma linha, só consulta e seções do MCR; e a
triagem precisa separar os dois programas sem duplicar o vocabulário de renda
do ruleset do PRONAF.
"""

from __future__ import annotations

import pytest

import src.programs as programs
from src.programs import triagem
from src.programs.base import RespostasInvalidas
from src.programs.pronaf import engine

# --- triagem -----------------------------------------------------------


def test_triagem_incompleta_devolve_none() -> None:
    """Sem nenhuma resposta, a triagem não resolve programa nenhum."""
    assert triagem.resolver({}) is None
    assert triagem.proxima_pergunta({}).id == "renda"


@pytest.mark.parametrize("bucket", ["ate60k", "ate150k", "ate500k", "ate714k"])
def test_triagem_faixas_pronaf_resolvem_pronaf(bucket: str) -> None:
    """Toda faixa de renda do próprio ruleset do PRONAF resolve para 'pronaf'."""
    assert triagem.resolver({"renda": bucket}) == "pronaf"


@pytest.mark.parametrize("bucket", ["ate60k", "ate150k", "ate500k", "ate714k"])
def test_triagem_nao_pergunta_renda_da_atividade_para_faixas_pronaf(bucket: str) -> None:
    """`renda_da_atividade` só existe para a faixa 'ate3mi' — diverge do simulador oficial."""
    assert triagem.proxima_pergunta({"renda": bucket}) is None


def test_triagem_nao_oferece_nenhuma_das_opcoes_acima() -> None:
    """'nenhuma' é a saída de "passo do teto" DENTRO do questionário do PRONAF.

    Na triagem existem faixas acima dela, então ela seria uma segunda resposta
    para a mesma renda — e resolvê-la como PRONAF mandaria para o questionário
    do PRONAF exatamente quem disse não caber nele.
    """
    assert "nenhuma" not in {o.v for o in triagem.proxima_pergunta({}).opcoes}
    assert triagem.resolver({"renda": "nenhuma"}) != "pronaf"


def test_triagem_faixas_de_renda_nao_se_sobrepoem() -> None:
    """Nenhuma renda pode caber em duas opções: a 'ate3mi' começa onde a última
    faixa do PRONAF termina (R$ 714,5 mil), não em R$ 500 mil."""
    rotulos = {o.v: o.t for o in triagem.proxima_pergunta({}).opcoes}
    assert "714,5" in rotulos["ate3mi"]
    assert "500 mil" not in rotulos["ate3mi"]


def test_triagem_ate3mi_pergunta_renda_da_atividade() -> None:
    pergunta = triagem.proxima_pergunta({"renda": "ate3mi"})
    assert pergunta is not None
    assert pergunta.id == "renda_da_atividade"
    assert triagem.resolver({"renda": "ate3mi"}) is None  # incompleta até responder


def test_triagem_ate3mi_com_atividade_sim_resolve_pronamp() -> None:
    assert triagem.resolver({"renda": "ate3mi", "renda_da_atividade": "sim"}) == "pronamp"
    assert triagem.proxima_pergunta({"renda": "ate3mi", "renda_da_atividade": "sim"}) is None


def test_triagem_ate3mi_com_atividade_nao_resolve_outros() -> None:
    assert triagem.resolver({"renda": "ate3mi", "renda_da_atividade": "nao"}) == "outros"


def test_triagem_acima3mi_resolve_outros_sem_perguntar_atividade() -> None:
    assert triagem.resolver({"renda": "acima3mi"}) == "outros"
    assert triagem.proxima_pergunta({"renda": "acima3mi"}) is None


def test_triagem_renda_reaproveita_vocabulario_do_ruleset_pronaf() -> None:
    """Opções de renda da triagem = faixas do ruleset do PRONAF (menos a saída
    'nenhuma') + as 2 faixas acima do teto. Lidas do ruleset, nunca copiadas."""
    valores_ruleset = {o["v"] for o in engine.ruleset()["perguntas"]["renda"]["opcoes"]}
    opcoes_triagem = {o.v for o in triagem.proxima_pergunta({}).opcoes}
    assert valores_ruleset - {"nenhuma"} <= opcoes_triagem
    assert opcoes_triagem - valores_ruleset == {"ate3mi", "acima3mi"}


# --- registro ------------------------------------------------------------


def test_registro_ids() -> None:
    assert set(programs.ids()) == {"pronaf", "pronamp"}


def test_registro_obter_devolve_adaptador_certo() -> None:
    assert programs.obter("pronaf").id == "pronaf"
    assert programs.obter("pronamp").id == "pronamp"


def test_registro_obter_erro_claro_para_id_desconhecido() -> None:
    with pytest.raises(KeyError, match="desconhecido-qualquer"):
        programs.obter("desconhecido-qualquer")


# --- ProgramaPronaf --------------------------------------------------------


def test_pronaf_vocabulario_bate_com_ruleset() -> None:
    """O vocabulário não é uma cópia à mão: cada valor existe no ruleset, e vice-versa."""
    vocab = programs.obter("pronaf").vocabulario()
    rs_perguntas = engine.ruleset()["perguntas"]

    assert set(vocab["tipo"]) == {o["v"] for o in rs_perguntas["tipo"]["opcoes"]}
    assert set(vocab["renda"]) == {o["v"] for o in rs_perguntas["renda"]["opcoes"]}
    assert set(vocab["regiao"]) == {o["v"] for o in rs_perguntas["regiao"]["opcoes"]}
    # finalidade funde as duas perguntas (PF e cooperativa) do ruleset.
    esperado_finalidade = {o["v"] for o in rs_perguntas["finalidade_pf"]["opcoes"]} | {
        o["v"] for o in rs_perguntas["finalidade_coop"]["opcoes"]
    }
    assert set(vocab["finalidade"]) == esperado_finalidade


def _responder_com_primeira_opcao(respostas: dict, pergunta) -> None:
    respostas[pergunta.id] = (
        [pergunta.opcoes[0].v] if pergunta.multipla else pergunta.opcoes[0].v
    )


@pytest.mark.parametrize("tipo_inicial", [None, "individual", "cooperativa"])
def test_pronaf_questionario_termina_e_recomenda(tipo_inicial: str | None) -> None:
    """Sempre respondendo a primeira opção, o questionário termina em poucos passos."""
    programa = programs.obter("pronaf")
    respostas: dict = {} if tipo_inicial is None else {"tipo": tipo_inicial}

    passos = 0
    while True:
        pergunta = programa.proxima_pergunta(respostas)
        if pergunta is None:
            break
        passos += 1
        assert passos <= 10, "questionário não terminou em número razoável de passos"
        _responder_com_primeira_opcao(respostas, pergunta)

    recomendacao = programa.recomendar(respostas)
    assert recomendacao.programa == "pronaf"
    assert len(recomendacao.linhas) > 0
    assert recomendacao.secoes_mcr == [
        {"capitulo_num": 10},
        {"capitulo_num": 7, "secao_label": "6"},
    ]


def test_pronaf_proxima_pergunta_ignora_respostas_parciais_e_desconhecidas() -> None:
    """Valor fora do vocabulário, ou slot ainda não respondido, não derruba o fluxo."""
    programa = programs.obter("pronaf")

    # Perfil totalmente vazio: pergunta o primeiro slot, sem levantar erro.
    assert programa.proxima_pergunta({}).id == "tipo"

    # Valor fora do vocabulário é ignorado, não vira exceção.
    pergunta = programa.proxima_pergunta({"tipo": "individual", "renda": "nao-e-uma-opcao"})
    assert pergunta.id == "renda"

    # Campo de outra ramificação (coop_perfil) presente não atrapalha o fluxo PF.
    pergunta = programa.proxima_pergunta(
        {"tipo": "individual", "renda": "ate60k", "coop_perfil": "coop_aac"}
    )
    assert pergunta.id == "perfil"


def test_pronaf_recomendar_com_respostas_invalidas_levanta_erro() -> None:
    """Só no fim (`recomendar`) um valor fora do vocabulário vira erro, não em `proxima_pergunta`."""
    programa = programs.obter("pronaf")
    respostas = {
        "tipo": "individual",
        "renda": "renda-inventada",
        "perfil": ["mulher"],
        "finalidade": ["custeio"],
        "organico": "sim",
        "regiao": "no",
    }
    with pytest.raises(RespostasInvalidas):
        programa.recomendar(respostas)


# --- ProgramaPronamp: a garantia de que nenhum número sai do LLM -----------


def test_pronamp_recomendar_nao_devolve_nenhum_numero_de_credito() -> None:
    """PRONAMP não tem ruleset: `linhas` é sempre [], e a fundamentação vem do MCR."""
    programa = programs.obter("pronamp")
    respostas = {"finalidade": ["custeio"], "atividade": "lavoura", "regiao": "su"}

    recomendacao = programa.recomendar(respostas)

    assert recomendacao.linhas == []
    assert recomendacao.secoes_mcr == [
        {"capitulo_num": 8},
        {"capitulo_num": 7, "secao_label": "4"},
    ]
    assert recomendacao.consulta_rag
    assert recomendacao.observacao is not None


def test_pronamp_questionario_termina() -> None:
    programa = programs.obter("pronamp")
    respostas: dict = {}
    passos = 0
    while True:
        pergunta = programa.proxima_pergunta(respostas)
        if pergunta is None:
            break
        passos += 1
        assert passos <= 10
        _responder_com_primeira_opcao(respostas, pergunta)
    assert programa.recomendar(respostas).linhas == []


def test_slots_declaram_multiplicidade_vinda_do_ruleset() -> None:
    """A multiplicidade de cada slot sai do ruleset, não de inspeção da árvore.

    O schema de extração do Agente Conselheiro precisa saber se um slot pede
    string ou lista. Descobrir isso percorrendo o questionário funcionaria, mas
    reconstruiria por força bruta um dado que o ruleset já declara — este teste
    trava a origem.
    """
    slots = programs.obter("pronaf").slots()
    perguntas = engine.ruleset()["perguntas"]

    assert slots["perfil"].multipla is perguntas["perfil"]["multipla"] is True
    assert slots["renda"].multipla is perguntas["renda"]["multipla"] is False
    assert slots["finalidade"].multipla is perguntas["finalidade_pf"]["multipla"] is True

    # `vocabulario()` deriva de `slots()` — não são duas fontes que podem divergir.
    assert programs.obter("pronaf").vocabulario() == {
        nome: slot.valores for nome, slot in slots.items()
    }


def test_triagem_expoe_slots_no_mesmo_formato_dos_programas() -> None:
    """O conselheiro monta o schema de extração igual nas duas fases."""
    slots = triagem.slots()
    assert set(slots) == {"renda", "renda_da_atividade"}
    assert all(not slot.multipla for slot in slots.values())
    assert {o.v for o in triagem.proxima_pergunta({}).opcoes} == set(slots["renda"].valores)

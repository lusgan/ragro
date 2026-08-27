"""
Testes do pipeline do Agente Q&A: filtro de metadados, busca com fallback,
reescrita de consulta, juiz de trechos e geração de resposta.

Totalmente offline — `gerar_json`/`gerar_texto` são substituídos por dublês
(ver `src/llm/client.py`); nenhum teste aqui fala com Vertex, Qdrant ou
Postgres. Os "trechos" recuperados são objetos falsos com um `.payload`
dict, no formato que `retriever.search` devolveria de verdade (`point.payload`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client.models import Filter

from src.llm import client as llm_client
from src.programs.base import Recomendacao
from src.rag import answer, judge, retriever, rewriter
from src.rag.retriever import SearchMode


@dataclass
class Trecho:
    """Duble de um `ScoredPoint` do Qdrant — só o que `answer`/`judge` usam."""

    payload: dict[str, Any]


def _trecho(texto: str, capitulo: int = 10, secao: str = "1") -> Trecho:
    return Trecho(
        payload={
            "capitulo_num": capitulo,
            "capitulo_text": "Pronaf",
            "secao_label": secao,
            "secao_text": "Disposições",
            "text": texto,
        }
    )


# --- filtro_de_secoes --------------------------------------------------------


def test_filtro_de_secoes_lista_vazia_devolve_none() -> None:
    assert retriever.filtro_de_secoes([]) is None


def test_filtro_de_secoes_entradas_sao_or_chaves_dentro_da_entrada_sao_and() -> None:
    filtro = retriever.filtro_de_secoes(
        [{"capitulo_num": 10}, {"capitulo_num": 7, "secao_label": "6"}]
    )

    assert isinstance(filtro, Filter)
    assert len(filtro.should) == 2  # as duas entradas viram um OR

    primeira, segunda = filtro.should
    assert len(primeira.must) == 1  # só uma chave -> um AND de um termo só
    assert primeira.must[0].key == "capitulo_num"
    assert primeira.must[0].match.value == 10

    assert len(segunda.must) == 2  # duas chaves na mesma entrada -> AND das duas
    chaves = {c.key for c in segunda.must}
    assert chaves == {"capitulo_num", "secao_label"}


def test_filtro_de_secoes_ignora_chave_nao_suportada_sem_descartar_a_entrada() -> None:
    filtro = retriever.filtro_de_secoes([{"capitulo_num": 10, "chave_desconhecida": "x"}])

    assert isinstance(filtro, Filter)
    assert len(filtro.should) == 1
    assert len(filtro.should[0].must) == 1  # só a chave suportada sobra
    assert filtro.should[0].must[0].key == "capitulo_num"


def test_filtro_de_secoes_entrada_só_com_chave_desconhecida_e_descartada() -> None:
    filtro = retriever.filtro_de_secoes([{"chave_desconhecida": "x"}])
    assert filtro is None


# --- buscar_com_fallback ------------------------------------------------------


def test_buscar_com_fallback_refaz_sem_filtro_quando_busca_filtrada_devolve_vazio(
    monkeypatch,
) -> None:
    """Um filtro inferido é só um palpite: se ele zerar a busca, o fallback
    tem que repetir a busca sem filtro e sinalizar `filtro_aplicado=False`."""
    chamadas = []

    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        chamadas.append(filtro)
        return [] if filtro is not None else ["resultado-sem-filtro"]

    monkeypatch.setattr(retriever, "search", fake_search)

    resultados, filtro_aplicado = retriever.buscar_com_fallback(
        "pergunta qualquer",
        client=None,
        bm25_model=None,
        mode=SearchMode.HYBRID,
        secoes=[{"capitulo_num": 10}],
    )

    assert resultados == ["resultado-sem-filtro"]
    assert filtro_aplicado is False
    assert len(chamadas) == 2  # buscou filtrado, depois sem filtro


def test_buscar_com_fallback_mantem_filtro_quando_a_busca_filtrada_acha_algo(
    monkeypatch,
) -> None:
    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        return ["resultado-com-filtro"] if filtro is not None else ["resultado-sem-filtro"]

    monkeypatch.setattr(retriever, "search", fake_search)

    resultados, filtro_aplicado = retriever.buscar_com_fallback(
        "pergunta qualquer",
        client=None,
        bm25_model=None,
        mode=SearchMode.HYBRID,
        secoes=[{"capitulo_num": 10}],
    )

    assert resultados == ["resultado-com-filtro"]
    assert filtro_aplicado is True


def test_buscar_com_fallback_sem_secoes_busca_direto_sem_filtro(monkeypatch) -> None:
    chamadas = []

    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        chamadas.append(filtro)
        return ["resultado"]

    monkeypatch.setattr(retriever, "search", fake_search)

    resultados, filtro_aplicado = retriever.buscar_com_fallback(
        "pergunta qualquer", client=None, bm25_model=None, mode=SearchMode.HYBRID, secoes=[]
    )

    assert resultados == ["resultado"]
    assert filtro_aplicado is False
    assert chamadas == [None]  # uma única busca, sem filtro nenhum


# --- reescrever ---------------------------------------------------------------


def test_reescrever_cai_para_pergunta_original_quando_gerar_json_devolve_none(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: None)

    reescrita = rewriter.reescrever(
        "e para cooperativa?", historico=[{"role": "user", "content": "o que é o pronaf?"}]
    )

    assert reescrita.consulta == "e para cooperativa?"
    assert reescrita.secoes_mcr == []


def test_reescrever_descarta_capitulo_fora_do_indice_conhecido(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        lambda *a, **k: {
            "consulta": "quais as regras do capitulo 99?",
            "secoes_mcr": [{"capitulo_num": 99}, {"capitulo_num": 10}],
        },
    )

    reescrita = rewriter.reescrever("quais as regras do capitulo 99?")

    assert reescrita.secoes_mcr == [{"capitulo_num": 10}]  # só o capítulo válido sobrevive


# --- avaliar (LLM-as-a-judge) --------------------------------------------------


def test_avaliar_mantem_todos_os_trechos_quando_o_juiz_fica_indisponivel(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: None)

    trechos = [_trecho("a"), _trecho("b"), _trecho("c")]
    julgamento = judge.avaliar("pergunta qualquer", trechos)

    assert julgamento.relevantes == [0, 1, 2]
    assert julgamento.suficiente is True
    assert julgamento.consulta_extra is None


def test_avaliar_descarta_indices_fora_do_intervalo_sem_jogar_fora_o_julgamento_usavel(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        lambda *a, **k: {
            "relevantes": [0, 5],  # 5 não existe: só 2 trechos (índices 0 e 1)
            "suficiente": False,
            "consulta_extra": "encargos financeiros do pronaf",
        },
    )

    trechos = [_trecho("a"), _trecho("b")]
    julgamento = judge.avaliar("pergunta qualquer", trechos)

    assert julgamento.relevantes == [0]  # índice inválido descartado, o válido fica
    assert julgamento.suficiente is False  # resto do julgamento é preservado
    assert julgamento.consulta_extra == "encargos financeiros do pronaf"


# --- gerar_resposta (com_cta) --------------------------------------------------


def test_gerar_resposta_com_cta_inclui_convite_e_sem_cta_nao_inclui(monkeypatch) -> None:
    prompts = []

    def fake_gerar_texto(prompt, *, modelo):
        prompts.append(prompt)
        return "resposta"

    monkeypatch.setattr(llm_client, "gerar_texto", fake_gerar_texto)

    trechos = [_trecho("texto do trecho")]

    answer.gerar_resposta("qual a taxa de juros do pronaf?", trechos, com_cta=True)
    answer.gerar_resposta("qual a taxa de juros do pronaf?", trechos, com_cta=False)

    assert len(prompts) == 2
    assert "faixa de renda" in prompts[0]  # marca do CTA presente
    assert "faixa de renda" not in prompts[1]  # ausente sem com_cta


# --- gerar_recomendacao --------------------------------------------------------


def test_gerar_recomendacao_poe_os_valores_exatos_de_linhas_no_prompt(monkeypatch) -> None:
    """Guarda-chuva da regra 'nenhum número sai do LLM': os valores que chegam
    ao prompt são exatamente os de `linhas`, para o modelo copiar, não calcular."""
    prompts = []

    def fake_gerar_texto(prompt, *, modelo):
        prompts.append(prompt)
        return "resposta"

    monkeypatch.setattr(llm_client, "gerar_texto", fake_gerar_texto)

    recomendacao = Recomendacao(
        programa="pronaf",
        linhas=[
            {
                "nome": "Pronaf Custeio",
                "limite_mil_reais": 41.5,
                "juros_aa_pct": 3.5,
                "prazo": "2 anos",
                "carencia": "1 ano",
                "bancos": ["BB", "CEF"],
            }
        ],
        consulta_rag="pronaf custeio mulher",
        secoes_mcr=[{"capitulo_num": 10}],
        perfil={"tipo": "individual", "renda": "ate60k"},
        fonte="ruleset.json (Plano Safra 2026/2027)",
        observacao=None,
    )

    answer.gerar_recomendacao(recomendacao, trechos=[_trecho("texto do mcr")])

    assert len(prompts) == 1
    prompt = prompts[0]
    assert "41.5" in prompt
    assert "3.5" in prompt
    assert "2 anos" in prompt
    assert "1 ano" in prompt
    assert "BB" in prompt and "CEF" in prompt


def test_gerar_recomendacao_pronamp_com_linhas_vazias_avisa_que_nao_ha_tabela_offline(
    monkeypatch,
) -> None:
    prompts = []

    def fake_gerar_texto(prompt, *, modelo):
        prompts.append(prompt)
        return "resposta"

    monkeypatch.setattr(llm_client, "gerar_texto", fake_gerar_texto)

    recomendacao = Recomendacao(
        programa="pronamp",
        linhas=[],
        consulta_rag="PRONAMP — renda: ate3mi",
        secoes_mcr=[{"capitulo_num": 8}, {"capitulo_num": 7, "secao_label": "4"}],
        perfil={"renda": "ate3mi"},
        fonte="MCR 8-1 e 7-4",
        observacao="O PRONAMP não tem ruleset offline.",
    )

    answer.gerar_recomendacao(recomendacao, trechos=[_trecho("texto do mcr", capitulo=8)])

    prompt = prompts[0]
    assert "não existe tabela offline" in prompt
    assert "MCR 8-1 e 7-4" in prompt

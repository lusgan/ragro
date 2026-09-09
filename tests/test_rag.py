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
from types import SimpleNamespace
from typing import Any

import pytest

from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Filter

from src.llm import client as llm_client
from src.programs.base import Recomendacao
from src.rag import answer, judge, qdrant, retriever, rewriter
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


def test_buscar_com_fallback_complementar_mescla_filtrado_e_sem_filtro(monkeypatch) -> None:
    """`complementar=True`: mesmo com a busca filtrada achando resultado, o
    capítulo inferido pode não ser o único relevante — mescla com a busca sem
    filtro em vez de devolver só o filtrado."""
    filtrado = SimpleNamespace(id="cap-1")
    repetido = SimpleNamespace(id="cap-3-a")  # aparece nas duas buscas
    novo = SimpleNamespace(id="cap-3-b")

    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        if filtro is not None:
            return [filtrado, repetido]
        return [repetido, novo]

    monkeypatch.setattr(retriever, "search", fake_search)

    resultados, filtro_aplicado = retriever.buscar_com_fallback(
        "pergunta qualquer",
        client=None,
        bm25_model=None,
        mode=SearchMode.HYBRID,
        secoes=[{"capitulo_num": 1}],
        complementar=True,
    )

    assert filtro_aplicado is True
    assert resultados == [filtrado, repetido, novo]  # filtrado primeiro, sem duplicar id repetido


def test_buscar_com_fallback_complementar_nao_muda_o_fallback_quando_filtro_zera(
    monkeypatch,
) -> None:
    """`complementar=True` só entra em jogo quando o filtro acha algo — se ele
    zera, o caminho continua sendo o fallback de sempre (uma única busca extra,
    não duas)."""
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
        secoes=[{"capitulo_num": 1}],
        complementar=True,
    )

    assert resultados == ["resultado-sem-filtro"]
    assert filtro_aplicado is False
    assert len(chamadas) == 2


# --- dedup_por_id -------------------------------------------------------------


def test_dedup_por_id_mantem_prioridade_e_descarta_repetidos() -> None:
    a = SimpleNamespace(id="a")
    b = SimpleNamespace(id="b")
    b_repetido = SimpleNamespace(id="b")
    c = SimpleNamespace(id="c")

    resultado = retriever.dedup_por_id([a, b], [b_repetido, c])

    assert resultado == [a, b, c]


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


def test_buscar_com_fallback_refaz_sem_filtro_quando_o_qdrant_recusa_o_filtro(
    monkeypatch,
) -> None:
    """Filtro recusado pelo servidor tem o mesmo destino de filtro que zera a busca.

    O caso real: `capitulo_num` não tinha índice de payload na coleção, e o
    Qdrant respondeu 400 em vez de devolver zero resultados — a pergunta inteira
    morria por causa de um refinamento opcional. O filtro é descartável em
    qualquer modo de falha, não só no vazio.
    """
    chamadas = []

    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        chamadas.append(filtro)
        if filtro is not None:
            raise UnexpectedResponse(
                status_code=400,
                reason_phrase="Bad Request",
                content=b'{"status":{"error":"Index required but not found"}}',
                headers=None,
            )
        return ["resultado-sem-filtro"]

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
    assert len(chamadas) == 2


def test_buscar_com_fallback_propaga_erro_que_nao_vem_do_filtro(monkeypatch) -> None:
    """Engolir o 400 do filtro não pode virar engolir Qdrant fora do ar.

    A busca sem filtro é a segunda tentativa, não um `except` que silencia: um
    erro que não vem do filtro reaparece nela e sobe.
    """

    def fake_search(query_text, client, bm25_model, mode=SearchMode.HYBRID, filtro=None):
        raise UnexpectedResponse(
            status_code=503,
            reason_phrase="Service Unavailable",
            content=b"",
            headers=None,
        )

    monkeypatch.setattr(retriever, "search", fake_search)

    try:
        retriever.buscar_com_fallback(
            "pergunta qualquer",
            client=None,
            bm25_model=None,
            mode=SearchMode.HYBRID,
            secoes=[{"capitulo_num": 10}],
        )
    except UnexpectedResponse as e:
        assert e.status_code == 503
    else:
        raise AssertionError("erro alheio ao filtro foi engolido pelo fallback")


# --- índices de payload -------------------------------------------------------
#
# O filtro e a coleção precisam concordar sobre quais campos são filtráveis. Um
# campo aceito pelo filtro sem índice na coleção não devolve busca vazia: o
# Qdrant recusa a consulta com 400.


def test_todo_campo_filtravel_tem_indice_declarado() -> None:
    """`_CAMPOS_FILTRO` deriva de `CAMPOS_FILTRAVEIS` — não é uma segunda lista."""
    assert set(retriever._CAMPOS_FILTRO) == set(qdrant.CAMPOS_FILTRAVEIS)
    assert retriever._CAMPOS_FILTRO["capitulo_num"] is int
    assert retriever._CAMPOS_FILTRO["secao_label"] is str


def test_secoes_pedidas_pelos_programas_sao_todas_filtraveis() -> None:
    """Nenhum programa pode pedir um campo que a coleção não indexa.

    As `secoes_mcr` de cada `Recomendacao` vão direto para `filtro_de_secoes`.
    Um campo novo ali sem índice correspondente é o bug de produção de volta —
    e ele não aparece como busca pior, aparece como resposta que não sai.
    """
    import src.programs as programs

    for pid in programs.ids():
        programa = programs.obter(pid)
        respostas: dict = {}
        while (pergunta := programa.proxima_pergunta(respostas)) is not None:
            respostas[pergunta.id] = (
                [pergunta.opcoes[0].v] if pergunta.multipla else pergunta.opcoes[0].v
            )
        chaves = {c for secao in programa.recomendar(respostas).secoes_mcr for c in secao}
        assert chaves, f"{pid} não declara seção nenhuma"
        assert chaves <= set(qdrant.CAMPOS_FILTRAVEIS), f"{pid} filtra por campo sem índice"


class _ClientFalso:
    """Duble do QdrantClient só para `garantir_indices` — sem rede."""

    def __init__(self, schema: dict) -> None:
        self._schema = dict(schema)
        self.criados: list[tuple[str, object]] = []

    def get_collection(self, collection_name):  # noqa: ARG002
        return type("Info", (), {"payload_schema": self._schema})()

    def create_payload_index(self, *, collection_name, field_name, field_schema, wait):  # noqa: ARG002
        self.criados.append((field_name, field_schema))
        self._schema[field_name] = field_schema


def test_garantir_indices_cria_os_que_faltam() -> None:
    client = _ClientFalso({})
    criados = qdrant.garantir_indices(client)

    assert set(criados) == set(qdrant.CAMPOS_FILTRAVEIS)
    assert dict(client.criados) == qdrant.CAMPOS_FILTRAVEIS


def test_garantir_indices_e_idempotente() -> None:
    """Roda em toda inicialização — não pode reescrever índice que já existe."""
    client = _ClientFalso({})
    qdrant.garantir_indices(client)
    client.criados.clear()

    assert qdrant.garantir_indices(client) == []
    assert client.criados == []


def test_garantir_indices_cria_so_o_que_falta() -> None:
    client = _ClientFalso({"capitulo_num": qdrant.PayloadSchemaType.INTEGER})

    assert qdrant.garantir_indices(client) == ["secao_label"]


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


def test_reescrever_derruba_secao_label_invalido_mas_mantem_o_capitulo(monkeypatch) -> None:
    """O caso observado em produção, 6 vezes em 6 perguntas.

    O prompt do rewriter pede capítulos e nunca explica `secao_label`, mas o
    schema o expõe como string livre — o modelo preenchia com o nome do
    capítulo (o `capitulo_text` do payload, literalmente). O filtro virava
    "capítulo 10 E seção chamada 'Pronaf'", casava com zero e era descartado
    inteiro, levando junto a parte do capítulo, que estava certa.
    """
    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        lambda *a, **k: {
            "consulta": "quem são os beneficiários do pronaf?",
            "secoes_mcr": [
                {
                    "capitulo_num": 10,
                    "secao_label": "Programa Nacional de Fortalecimento da "
                    "Agricultura Familiar (Pronaf)",
                }
            ],
        },
    )

    reescrita = rewriter.reescrever("quem são os beneficiários do pronaf?")

    assert reescrita.secoes_mcr == [{"capitulo_num": 10}]


@pytest.mark.parametrize("label", ["1", "18", "4-A", "10"])
def test_reescrever_preserva_secao_label_bem_formado(label: str) -> None:
    """Formatos que existem de verdade no payload passam intactos."""
    assert rewriter._secoes_validas([{"capitulo_num": 7, "secao_label": label}]) == [
        {"capitulo_num": 7, "secao_label": label}
    ]


@pytest.mark.parametrize(
    "label", ["Encargos Financeiros", "seção 6", "", "6.1.2", "Cap. 7"]
)
def test_reescrever_derruba_labels_que_nao_sao_numero_de_secao(label: str) -> None:
    assert rewriter._secoes_validas([{"capitulo_num": 7, "secao_label": label}]) == [
        {"capitulo_num": 7}
    ]


def test_reescrever_descarta_entrada_que_so_tinha_secao_label_invalido() -> None:
    """Sem capítulo e sem label utilizável não sobra nada que estreite a busca."""
    assert rewriter._secoes_validas([{"secao_label": "Condições Básicas"}]) == []


def test_reescrever_label_bem_formado_inexistente_e_problema_do_fallback() -> None:
    """A checagem aqui é de formato, não de existência.

    Uma seção "99" passa e zera a busca — e é `buscar_com_fallback` quem cobre
    isso, como cobre qualquer outro palpite errado do filtro. Validar
    existência exigiria replicar o corpus num índice estático que envelheceria
    a cada reindexação.
    """
    assert rewriter._secoes_validas([{"capitulo_num": 7, "secao_label": "99"}]) == [
        {"capitulo_num": 7, "secao_label": "99"}
    ]


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

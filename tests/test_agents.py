"""
Testes do orquestrador e dos agentes (`src/agents/`): totalmente offline, sem
Vertex, Qdrant ou Postgres — como manda `docs/arquitetura-agentes.md`.

Onde cada dublê é aplicado importa: `gerar_json`/`gerar_texto` são chamados
por referência de módulo (`llm_client.gerar_json(...)`) em todo `src/agents/`
e `src/rag/`, então substituí-los em `src.llm.client` basta. O mesmo vale
para `judge.avaliar`, `rewriter.reescrever` e `answer.gerar_recomendacao`
— `qa.py`/`advisor.py` guardam referência ao módulo (`judge`, `rewriter`,
`answer`), não à função isolada. Já `buscar_com_fallback` foi importado por
nome (`from src.rag.retriever import buscar_com_fallback`) dentro de `qa.py`
e `advisor.py`, então o dublê tem que ser aplicado nesses módulos, não em
`src.rag.retriever`.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import src.programs as programs
from src.agents import advisor, orchestrator, qa
from src.llm import client as llm_client
from src.rag import answer, judge, rewriter
from src.rag.judge import Julgamento
from src.rag.rewriter import Reescrita

# --- helpers de teste ------------------------------------------------------


def _payload(**over) -> dict:
    base = {
        "capitulo_num": 10,
        "capitulo_text": "PRONAF",
        "secao_num": "1",
        "secao_label": None,
        "secao_text": "Texto",
        "chunk_index": 0,
        "total_chunks": 1,
        "text": "conteúdo do trecho",
    }
    base.update(over)
    return base


def _ponto(id_: str, **over):
    return SimpleNamespace(id=id_, score=0.9, payload=_payload(**over))


def _estado(**over) -> dict:
    base = {
        "fase": "coleta",
        "programa": "pronaf",
        "triagem": {},
        "respostas": {},
        "slot_pendente": None,
        "esclarecimentos": {},
        "atualizado_em": "2026-01-01T00:00:00+00:00",
    }
    base.update(over)
    return base


def _make_gerar_json(*, extrair=None, conduzir=None):
    """Dublê de `gerar_json` que decide, pela forma do schema, se a chamada é
    de EXTRAIR ou de CONDUÇÃO: o schema de condução é sempre exatamente
    `{'acao', 'texto'}`; qualquer outra forma é tratada como EXTRAIR. Cada
    callback recebe `(prompt, schema)`.
    """

    def _fake(prompt, *, schema, modelo=None):
        eh_conducao = set(schema.get("properties", {})) == {"acao", "texto"}
        if eh_conducao:
            return conduzir(prompt, schema) if conduzir else None
        return extrair(prompt, schema) if extrair else {}

    return _fake


# --- orquestrador ------------------------------------------------------


def test_roteamento_sticky_mantem_conselheiro_para_resposta_de_slot(monkeypatch) -> None:
    """No meio do questionário, uma resposta de slot ('uns 80 mil por ano') não
    parece pedido de aconselhamento e vazaria para o Q&A sem o sticky routing."""
    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: {"mudou_assunto": False})
    rota = orchestrator.rotear("uns 80 mil por ano", historico=None, estado=_estado(fase="coleta"))
    assert rota.agente == "conselheiro"
    assert rota.fonte == "sticky"


def test_roteamento_sticky_mantem_conselheiro_quando_classificador_falha(monkeypatch) -> None:
    """`gerar_json` devolvendo `None` durante uma sessão aberta não pode vazar
    para o Q&A — a leitura conservadora é 'continua o questionário'."""
    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: None)
    rota = orchestrator.rotear("sim, sou mulher", historico=None, estado=_estado(fase="triagem"))
    assert rota.agente == "conselheiro"
    assert rota.fonte == "sticky"


def test_classificador_sem_sessao_aberta_cai_para_qa_quando_falha(monkeypatch) -> None:
    """Sem sessão aberta, uma falha do classificador cai para `qa` — o fluxo
    que já existe e sempre responde alguma coisa."""
    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: None)
    rota = orchestrator.rotear("qual o juro do pronaf?", historico=None, estado=None)
    assert rota.agente == "qa"
    assert rota.fonte == "fallback"


def test_mudanca_de_assunto_clara_rotea_para_qa_sem_orquestrador_limpar_estado(monkeypatch) -> None:
    """Uma mudança de assunto inequívoca muda a rota para `qa` — mas suspender
    a sessão do conselheiro é responsabilidade do `advisor`, não do
    orquestrador: `estado` sai intacto."""
    estado_original = _estado(fase="coleta", respostas={"tipo": "individual"})
    estado_copia = dict(estado_original)  # cópia rasa só para comparar depois

    monkeypatch.setattr(llm_client, "gerar_json", lambda *a, **k: {"mudou_assunto": True})
    rota = orchestrator.rotear(
        "na verdade, qual o telefone do Banco do Brasil?", historico=None, estado=estado_original
    )

    assert rota.agente == "qa"
    assert rota.fonte == "llm"
    assert estado_original == estado_copia


# --- Agente Q&A ----------------------------------------------------------


def test_qa_sem_resultados_devolve_mensagem_padrao_sem_estado(monkeypatch) -> None:
    monkeypatch.setattr(
        rewriter, "reescrever", lambda pergunta, historico=None: Reescrita(consulta=pergunta, secoes_mcr=[])
    )
    monkeypatch.setattr(qa, "buscar_com_fallback", lambda *a, **k: ([], False))

    resposta = qa.responder("existe linha para pesca?", None, None, None)

    assert resposta.texto == qa.SEM_RESULTADOS
    assert resposta.estado is None
    assert resposta.trechos == []
    assert resposta.pergunta is None


def test_qa_judge_sem_relevantes_usa_todos_os_trechos(monkeypatch) -> None:
    """Guarda contra um juiz rigoroso demais: sem isso, um julgamento que
    descarta tudo devolveria contexto vazio ao gerador para uma pergunta que o
    corpus respondia."""
    pontos = [_ponto("a"), _ponto("b")]
    monkeypatch.setattr(
        rewriter, "reescrever", lambda pergunta, historico=None: Reescrita(consulta=pergunta, secoes_mcr=[])
    )
    monkeypatch.setattr(qa, "buscar_com_fallback", lambda *a, **k: (pontos, False))
    monkeypatch.setattr(
        judge, "avaliar", lambda pergunta, trechos: Julgamento(relevantes=[], suficiente=False, consulta_extra=None)
    )
    monkeypatch.setattr(llm_client, "gerar_texto", lambda prompt, *, modelo=None: "resposta gerada")

    resposta = qa.responder("pergunta qualquer", None, None, None)

    assert len(resposta.trechos) == 2


# --- Agente Conselheiro: extração -----------------------------------------


def test_extracao_descarta_valor_fora_do_vocabulario_e_mantem_slot_pendente(monkeypatch) -> None:
    """Um valor aproximado é pior do que uma pergunta refeita: `tipo` fora do
    vocabulário é descartado, não vira o perfil do usuário."""
    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        _make_gerar_json(extrair=lambda p, s: {"renda": "nao-existe-essa-faixa"}),
    )
    estado = _estado(respostas={"tipo": "individual"})

    resposta = advisor.responder("umas 3 chácaras", None, estado, None, None)

    assert "renda" not in resposta.estado["respostas"]
    assert resposta.pergunta is not None
    assert resposta.pergunta.id == "renda"
    assert resposta.estado["slot_pendente"] == "renda"


def test_extracao_preenche_varios_slots_no_mesmo_turno(monkeypatch) -> None:
    """'sou mulher, planto orgânico, uns 50 mil por ano' precisa preencher
    renda, perfil e organico juntos, em vez de três perguntas separadas."""
    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        _make_gerar_json(
            extrair=lambda p, s: {"renda": "ate150k", "perfil": ["mulher"], "organico": "sim"}
        ),
    )
    estado = _estado(respostas={"tipo": "individual"})

    resposta = advisor.responder(
        "sou mulher, planto orgânico, uns 50 mil por ano", None, estado, None, None
    )

    assert resposta.estado["respostas"]["renda"] == "ate150k"
    assert resposta.estado["respostas"]["perfil"] == ["mulher"]
    assert resposta.estado["respostas"]["organico"] == "sim"
    # 'finalidade' ainda não foi informado — é o próximo slot pendente do engine.
    assert resposta.pergunta is not None
    assert resposta.pergunta.id == "finalidade"


# --- Agente Conselheiro: triagem -------------------------------------------


def test_triagem_seeda_renda_do_pronaf_para_nao_perguntar_duas_vezes(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_client, "gerar_json", _make_gerar_json(extrair=lambda p, s: {"renda": "ate60k"})
    )

    resposta = advisor.responder("minha renda é uns 50 mil por ano", None, None, None, None)

    assert resposta.estado["programa"] == "pronaf"
    assert resposta.estado["fase"] == "coleta"
    assert resposta.estado["respostas"]["renda"] == "ate60k"
    # A pergunta seguinte não pode ser 'renda' de novo.
    assert resposta.pergunta is not None
    assert resposta.pergunta.id != "renda"


def test_triagem_outros_produz_explicacao_sem_recomendacao(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_client, "gerar_json", _make_gerar_json(extrair=lambda p, s: {"renda": "acima3mi"})
    )

    resposta = advisor.responder("faturo uns 5 milhões por ano", None, None, None, None)

    assert resposta.estado["fase"] == "concluido"
    assert resposta.estado["programa"] == "outros"
    assert resposta.texto == advisor.MSG_OUTROS
    assert resposta.trechos == []
    assert resposta.pergunta is None


# --- Agente Conselheiro: terminação ------------------------------------


def test_questionario_pronaf_termina_mesmo_com_conducao_sempre_pedindo_esclarecimento(
    monkeypatch,
) -> None:
    """Mesmo que a condução tente 'esclarecer' em todo turno elegível, o
    limite de `MAX_ESCLARECIMENTOS_POR_SLOT` (1) garante que o questionário
    termina em número finito de turnos: sem essa trava, nada impede o LLM de
    girar em torno do mesmo slot para sempre.
    """

    def _extrator_regex(prompt: str, schema: dict) -> dict:
        m = re.search(r"RESPOSTA:(\w+)=([\w,]+)", prompt)
        if not m:
            return {}
        slot, valor = m.group(1), m.group(2)
        propriedades = schema.get("properties", {})
        if slot not in propriedades:
            return {}
        if propriedades[slot].get("type") == "array":
            return {slot: valor.split(",")}
        return {slot: valor}

    monkeypatch.setattr(
        llm_client,
        "gerar_json",
        _make_gerar_json(
            extrair=_extrator_regex,
            conduzir=lambda p, s: {"acao": "esclarecer", "texto": "pode detalhar melhor?"},
        ),
    )
    monkeypatch.setattr(advisor, "buscar_com_fallback", lambda *a, **k: ([], False))
    monkeypatch.setattr(judge, "avaliar", lambda *a, **k: Julgamento([], True, None))
    monkeypatch.setattr(answer, "gerar_recomendacao", lambda *a, **k: "recomendação final")

    estado = None
    LIMITE_TURNOS = 40
    turnos = 0

    # Primeiro slot: manda mensagem vaga duas vezes seguidas. A 1ª gasta o
    # único esclarecimento permitido; a 2ª já esgotou o limite — tem que
    # forçar 'seguir' com o texto literal do engine, sem chamar o LLM de novo.
    resposta = advisor.responder("quero simular um crédito", None, estado, None, None)
    turnos += 1
    estado = resposta.estado
    assert resposta.pergunta is not None
    primeiro_slot = resposta.pergunta.id
    assert resposta.texto == "pode detalhar melhor?"

    resposta = advisor.responder("continuo sem saber responder direito", None, estado, None, None)
    turnos += 1
    estado = resposta.estado
    assert resposta.pergunta.id == primeiro_slot
    assert resposta.texto == resposta.pergunta.texto  # esgotado: seguir forçado, verbatim

    # Dali em diante, responde corretamente a cada pergunta pendente — o
    # questionário inteiro (triagem + PRONAF) tem que terminar em poucos
    # turnos, mesmo que a condução volte a tentar 'esclarecer' a cada slot novo.
    while turnos < LIMITE_TURNOS:
        turnos += 1
        pergunta = resposta.pergunta
        if pergunta is None:
            break
        valor = pergunta.opcoes[0].v
        mensagem = f"RESPOSTA:{pergunta.id}={valor}"
        resposta = advisor.responder(mensagem, None, estado, None, None)
        estado = resposta.estado

    assert resposta.pergunta is None
    assert estado["fase"] == "concluido"
    assert estado["programa"] == "pronaf"
    assert turnos < LIMITE_TURNOS


# --- Agente Conselheiro: laço de re-busca da RECOMENDAR --------------------


def test_recomendar_laco_de_busca_para_em_max_rodadas(monkeypatch) -> None:
    respostas_completas = {
        "tipo": "individual",
        "renda": "ate60k",
        "perfil": ["mulher"],
        "finalidade": ["custeio"],
        "organico": "sim",
        "regiao": "no",
    }
    estado = _estado(respostas=respostas_completas)

    chamadas: list[str] = []

    def fake_busca(consulta, client, bm25_model, *, mode, secoes):
        chamadas.append(consulta)
        return [_ponto(f"p{len(chamadas)}")], True

    def fake_avaliar(consulta, trechos):
        # Nunca repete a consulta e nunca se declara suficiente — só o cap
        # de MAX_RODADAS_BUSCA pode parar este laço.
        return Julgamento(relevantes=[0], suficiente=False, consulta_extra=f"consulta extra {len(chamadas)}")

    monkeypatch.setattr(llm_client, "gerar_json", _make_gerar_json())
    monkeypatch.setattr(advisor, "buscar_com_fallback", fake_busca)
    monkeypatch.setattr(judge, "avaliar", fake_avaliar)
    monkeypatch.setattr(answer, "gerar_recomendacao", lambda *a, **k: "ok")

    resposta = advisor.responder("me dá a recomendação", None, estado, None, None)

    assert len(chamadas) == advisor.MAX_RODADAS_BUSCA
    assert resposta.estado["fase"] == "concluido"


def test_recomendar_laco_de_busca_para_cedo_quando_judge_repete_consulta(monkeypatch) -> None:
    respostas_completas = {
        "tipo": "individual",
        "renda": "ate60k",
        "perfil": ["mulher"],
        "finalidade": ["custeio"],
        "organico": "sim",
        "regiao": "no",
    }
    estado = _estado(respostas=respostas_completas)

    chamadas: list[str] = []

    def fake_busca(consulta, client, bm25_model, *, mode, secoes):
        chamadas.append(consulta)
        return [_ponto("p1")], True

    def fake_avaliar(consulta, trechos):
        # 'sem progresso é o mesmo que suficiente': repete a própria consulta.
        return Julgamento(relevantes=[0], suficiente=False, consulta_extra=consulta)

    monkeypatch.setattr(llm_client, "gerar_json", _make_gerar_json())
    monkeypatch.setattr(advisor, "buscar_com_fallback", fake_busca)
    monkeypatch.setattr(judge, "avaliar", fake_avaliar)
    monkeypatch.setattr(answer, "gerar_recomendacao", lambda *a, **k: "ok")

    advisor.responder("me dá a recomendação", None, estado, None, None)

    assert len(chamadas) == 1


# --- Agente Conselheiro: procedência dos números ---------------------------


def test_prompt_da_recomendacao_final_so_contem_numeros_de_rec_linhas(monkeypatch) -> None:
    """Regra fundamental do projeto: nenhum número de crédito sai do LLM. O
    bloco LINHAS do prompt final tem que ser exatamente `rec.linhas`, nunca um
    valor calculado ou aproximado por quem redige."""
    respostas_completas = {
        "tipo": "individual",
        "renda": "ate60k",
        "perfil": ["mulher"],
        "finalidade": ["custeio"],
        "organico": "sim",
        "regiao": "no",
    }
    estado = _estado(respostas=respostas_completas)

    rec_esperada = programs.obter("pronaf").recomendar(respostas_completas)
    assert rec_esperada.linhas, "perfil de teste precisa render ao menos uma linha elegível"

    monkeypatch.setattr(llm_client, "gerar_json", _make_gerar_json())
    monkeypatch.setattr(advisor, "buscar_com_fallback", lambda *a, **k: ([], False))
    monkeypatch.setattr(judge, "avaliar", lambda *a, **k: Julgamento([], True, None))

    prompts_capturados: list[str] = []

    def fake_gerar_texto(prompt: str, *, modelo=None) -> str:
        prompts_capturados.append(prompt)
        return "resposta gerada"

    monkeypatch.setattr(llm_client, "gerar_texto", fake_gerar_texto)

    resposta = advisor.responder("me dá a recomendação", None, estado, None, None)

    assert len(prompts_capturados) == 1
    prompt = prompts_capturados[0]

    marcador = "LINHAS (fonte exclusiva de números — copie literalmente):\n"
    inicio = prompt.index(marcador) + len(marcador)
    fim = prompt.index("\n\nTRECHOS DO MCR", inicio)
    linhas_no_prompt = json.loads(prompt[inicio:fim])

    assert linhas_no_prompt == rec_esperada.linhas
    assert resposta.estado["fase"] == "concluido"


# --- Agente Conselheiro: retomada de sessão concluída ----------------------


def test_sessao_concluida_reinicia_coleta_mantendo_triagem_e_programa(monkeypatch) -> None:
    """A renda (via triagem) e o programa já resolvido não mudam entre duas
    perguntas — refazer a triagem inteira pareceria um chatbot quebrado."""
    estado_anterior = _estado(
        fase="concluido",
        programa="pronaf",
        triagem={"renda": "ate60k"},
        respostas={
            "tipo": "individual",
            "renda": "ate60k",
            "perfil": ["mulher"],
            "finalidade": ["custeio"],
            "organico": "sim",
            "regiao": "no",
        },
        slot_pendente=None,
        esclarecimentos={"regiao": 1},
    )
    estado_original_congelado = json.loads(json.dumps(estado_anterior))

    monkeypatch.setattr(llm_client, "gerar_json", _make_gerar_json())

    resposta = advisor.responder("quero simular de novo", None, estado_anterior, None, None)

    novo_estado = resposta.estado
    assert novo_estado["fase"] == "coleta"
    assert novo_estado["triagem"] == {"renda": "ate60k"}
    assert novo_estado["programa"] == "pronaf"
    assert novo_estado["respostas"] == {}
    assert novo_estado["esclarecimentos"] == {}
    assert resposta.pergunta is not None
    assert resposta.pergunta.id == "tipo"

    # `responder` não pode ter mutado o estado original que recebeu.
    assert estado_anterior == estado_original_congelado

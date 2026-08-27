# Arquitetura de agentes

Documento de referência do fluxo de inferência multiagente. Descreve o desenho
alvo — orquestrador, Agente Q&A e Agente Conselheiro — e as regras que separam
o que o LLM decide do que o código decide.

Base: `draws/diagrama_inferencia`. Onde este documento diverge do diagrama, a
divergência está marcada e justificada.

## Visão geral

```
usuário
  │
  ▼
Orquestrador ── qa ──────────► Agente Q&A
  (escolhe o agente)             query rewriting → busca híbrida + filtro
  │                              → LLM-as-a-judge → resposta + call-to-action
  │
  └────────── conselheiro ───► Agente Conselheiro
                                 extração de slots → triagem de programa
                                 → questionário conduzido pelo engine
                                 → recomendação + fundamentação via RAG
```

## Regra fundamental

**Nenhum número de crédito sai do LLM.** Limite, juros, prazo, carência, bônus
de adimplência e lista de bancos vêm sempre de `programs.pronaf.engine`, que
reproduz a árvore do simulador oficial do MDA e é validado contra 3000 estados
em `tests/fixtures/pronaf_golden.json`.

O LLM faz três coisas, e só essas três: **entender** (extrair slots da fala
livre), **conduzir** (formular a próxima pergunta em português natural) e
**redigir** (explicar o resultado já calculado, citando o MCR).

O PRONAMP não tem ruleset. Ele não devolve números próprios: devolve uma
consulta e um filtro de seções do MCR, e a resposta é gerada fundamentada no
texto recuperado, com citação de capítulo e seção.

## Orquestrador

`src/agents/orchestrator.py` — `rotear(pergunta, historico, estado) -> Rota`

Decide entre `qa` e `conselheiro`. Duas divergências em relação ao diagrama:

1. **Roteamento é sticky.** O diagrama roteia a cada turno olhando só a
   pergunta. Isso quebra o conselheiro: no meio do questionário, "uns 80 mil
   por ano" ou "sim, sou mulher" não parecem pedido de aconselhamento e cairiam
   no Q&A. Com um `advisor_state` aberto (`fase` em `triagem`/`coleta`), a rota
   é `conselheiro` por padrão; o LLM só é consultado para detectar **mudança de
   assunto** — e nesse caso a sessão do conselheiro é suspensa, não descartada.

2. **Falha do classificador cai para `qa`.** O Q&A é o fluxo que já existe e
   sempre responde alguma coisa. Uma indisponibilidade do classificador não
   pode derrubar a conversa.

Modelo: `gemini-2.5-flash` com saída JSON estruturada.

## Agente Q&A

`src/agents/qa.py` — o fluxo atual, com as técnicas do diagrama somadas.

1. **Query rewriting** (`rag/rewriter.py`) — uma chamada `flash` que faz duas
   coisas de uma vez: condensa a pergunta de acompanhamento em pergunta
   standalone (o que `generator.condense_query` já fazia) e infere um filtro de
   metadados quando o assunto é identificável (ex.: PRONAF → Cap. 10).
2. **Busca híbrida + filtro por metadados** (`rag/retriever.py`) — dense + BM25
   com fusão RRF, agora aceitando um `Filter` do Qdrant sobre o payload.
3. **LLM-as-a-judge** (`rag/judge.py`) — classifica cada trecho como relevante
   ou não e descarta os irrelevantes antes da geração.
4. **Resposta + call-to-action** (`rag/answer.py`) — ao final, um convite
   concreto para o conselheiro, gerado só quando o assunto tem a ver com linhas
   de crédito. O CTA não é enfeite: ele é o gancho de transferência para o
   Agente Conselheiro.

Sem laço de re-busca aqui — o laço existe só no conselheiro, como no diagrama.

## Agente Conselheiro

`src/agents/advisor.py` — `responder(pergunta, historico, estado, ...) -> Resposta`

### Estado

Persistido em `conversations.advisor_state` (JSONB), uma sessão por conversa:

```json
{
  "fase": "triagem | coleta | concluido",
  "programa": "pronaf | pronamp | outros | null",
  "triagem": {"renda": "...", "renda_da_atividade": "..."},
  "respostas": {"tipo": "individual", "renda": "ate60k", "perfil": ["mulher"]},
  "slot_pendente": "finalidade",
  "esclarecimentos": {"finalidade": 1},
  "atualizado_em": "2026-08-27T19:00:00Z"
}
```

### Turno

```
1. EXTRAIR  (flash, JSON schema derivado do vocabulário do programa)
   fala livre + slot pendente → {slot: valor, ...}
   Só preenche o que o usuário efetivamente disse. Valor fora do vocabulário
   é descartado, não aproximado.

2. TRIAGEM  (fase == "triagem")
   programs.triagem.resolver(estado["triagem"]) → pronaf | pronamp | outros | None
   None → próxima pergunta de triagem. Resolvido → fase = "coleta".

3. ENGINE   programa.proxima_pergunta(respostas)
   É o engine, não o LLM, que decide qual slot ainda falta.

4a. Se falta slot → CONDUZIR (flash)
    O LLM recebe a pergunta do engine e devolve uma de duas ações:
      seguir     — reformula a pergunta do engine em PT-BR natural
      esclarecer — insere uma pergunta de esclarecimento antes
    O slot pendente NÃO muda em nenhum dos casos. O LLM não pode pular um
    slot nem inventar valor para ele.

4b. Se não falta → RECOMENDAR
    programa.recomendar(respostas) → números exatos (PRONAF) ou consulta +
    seções do MCR (PRONAMP). Em seguida busca híbrida filtrada por essas
    seções, e o `pro` redige a explicação citando capítulo e seção.
```

### Por que o desvio é limitado a `esclarecer`

A opção escolhida foi a híbrida: o engine guia, o LLM pode desviar. O desvio
irrestrito tem dois custos que a restrição elimina.

- **Terminação.** Se o LLM pudesse pular ou reordenar slots, o questionário
  deixaria de ter garantia de fim. Com o slot pendente imutável, cada turno ou
  preenche o slot ou gasta um esclarecimento — e esclarecimentos são contados.
- **Testabilidade.** O caminho `seguir` é determinístico e coberto pelos testes
  existentes do engine. O `esclarecer` é o único ponto não determinístico, e é
  limitado a **um por slot** (`esclarecimentos[slot] < 1`); esgotado o limite, o
  turno seguinte é forçado a `seguir`.

## Programas

`src/programs/` — registry sobre um protocolo comum, para que o conselheiro não
conheça PRONAF nem PRONAMP diretamente.

```python
class Programa(Protocol):
    id: str
    nome: str
    def vocabulario(self) -> dict[str, list[str]]: ...
    def proxima_pergunta(self, respostas: dict) -> Pergunta | None: ...
    def recomendar(self, respostas: dict) -> Recomendacao: ...
```

| Programa | Fonte da verdade | O que `recomendar` devolve |
|---|---|---|
| `pronaf` | `ruleset.json`, extraído do simulador do MDA | linhas com limite, juros, prazo, carência, bancos |
| `pronamp` | MCR 8-1 e 7-4, via RAG | consulta + seções do MCR; nenhum número próprio |

### Triagem

Duas perguntas separam os programas, e reaproveitam o vocabulário de renda do
ruleset do PRONAF em vez de criar outro:

| renda bruta anual | renda da atividade ≥ 50% | programa |
|---|---|---|
| até R$ 500 mil (faixas do PRONAF) | — | `pronaf` |
| até R$ 3 milhões | sim | `pronamp` |
| até R$ 3 milhões | não | `outros` |
| acima de R$ 3 milhões | — | `outros` |

Os limiares são dado normativo e mudam a cada Plano Safra. Ficam em um único
arquivo, com o campo `fonte` preenchido, para serem revalidados de uma vez.

## Estrutura de diretórios

```
src/
  config.py              env, logging, BM25 sem acento, tokenizer, ids de chunk
  llm/client.py          cliente Vertex; gerar_texto() e gerar_json()
  rag/
    qdrant.py            conexão e criação da coleção
    retriever.py         busca dense / sparse / híbrida + filtro por metadados
    rewriter.py          condensação + inferência de filtro
    judge.py             LLM-as-a-judge sobre os trechos
    answer.py            montagem de contexto e geração da resposta
  agents/
    orchestrator.py      roteamento
    qa.py                Agente Q&A
    advisor.py           Agente Conselheiro
    prompts.py           todos os templates de prompt
    types.py             Rota, Resposta, Pergunta
  programs/
    base.py              protocolo Programa
    triagem.py           resolução de programa
    pronaf/              engine.py + ruleset.json + program.py
    pronamp/             program.py + perguntas.json
  ingestion/             chunker.py, indexer.py, extraction/
  storage/
    db.py, auth.py, chat_history.py, advisor_state.py
    migrations/*.sql     fonte da verdade do schema
frontend/
  app.py                 entrypoint fino
  state.py               session_state escopado por usuário
  views/                 auth.py, sidebar.py, chat.py
```

`frontend/` mantém o nome: o caminho `frontend/app.py` está configurado fora do
repositório (dashboard do Streamlit Cloud e `.devcontainer/devcontainer.json`).

## Testes

As chamadas de LLM passam todas por `llm/client.py`, em funções de módulo. Os
testes substituem essas funções por dubles e exercitam o fluxo inteiro offline
— sem Vertex, sem Qdrant e sem Postgres. O que precisa estar coberto:

- roteamento sticky: resposta de slot no meio do questionário não vaza para o Q&A;
- terminação: o questionário sempre chega a `recomendar`, mesmo com o LLM
  insistindo em esclarecer;
- procedência dos números: o texto final só contém valores presentes no retorno
  de `recomendar`;
- extração: valor fora do vocabulário é descartado, não aproximado;
- as suítes de isolamento por usuário que já existem continuam passando.

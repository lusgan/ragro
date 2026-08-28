# ragro

RAG sobre o Manual de Crédito Rural (MCR) com busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.

Para a interface web e o deploy, veja [frontend/README.md](frontend/README.md).

---

## Agentes

Além do Agente Q&A (pergunta e resposta sobre o MCR), o chat tem um Agente Conselheiro:
conduz uma triagem e um questionário curto e recomenda a linha de crédito rural (PRONAF/PRONAMP)
adequada ao perfil informado. Um orquestrador decide, a cada turno, qual dos dois responde.

Números de crédito (limite, juros, prazo, carência) nunca saem do LLM — vêm sempre de um motor de
regras determinístico. Fluxo completo, estado persistido e as garantias de terminação em
[docs/arquitetura-agentes.md](docs/arquitetura-agentes.md).

---

## Instalação

Requer Python 3.11+ e uma chave [Voyage AI](https://www.voyageai.com/).

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` na raiz:

```env
VOYAGE_API_KEY=sua_chave_voyage
QDRANT_URL=http://localhost:6333
```

Credenciais dos extratores (`ADOBE_CLIENT_ID`, `ADOBE_CLIENT_SECRET`,
`AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`, `AZURE_DOCUMENT_INTELLIGENCE_KEY`) só são
necessárias para re-extrair o MCR do PDF.

---

## Qdrant

Sempre como servidor HTTP, nunca embedded. Precisa estar acessível antes de qualquer
parte do pipeline.

### Local (Docker)

```bash
docker compose up -d          # dashboard em http://localhost:6333/dashboard
docker compose down           # para o container; o volume qdrant_db/ preserva os dados
```

### Qdrant Cloud

Necessário quando o app roda fora da sua máquina (ex.: Streamlit Cloud), que não alcança
`localhost:6333`. Crie um cluster em [cloud.qdrant.io](https://cloud.qdrant.io) (o free tier
de 1 GB acomoda o projeto), copie a Cluster URL e gere uma API Key:

```env
QDRANT_URL=https://xxxxx.cloud.qdrant.io:443
QDRANT_API_KEY=sua_api_key
```

> A porta `:443` é explícita de propósito: sem ela o `qdrant-client` assume `6333`, que
> funciona da sua máquina mas é bloqueada na saída de rede de hosts como o Streamlit Cloud.
> O cluster atende REST nas duas portas.

Depois reindexe apontando para o cluster com `python -m src.main` — o volume local não é
usado nesse modo. Para voltar ao servidor local, reverta `QDRANT_URL` e limpe a API key.

---

## Pipeline RAG

Os `.docx` do MCR já estão em `data/MCR - docx/`:

```powershell
python -m src.main
```

Na primeira execução lê os `.docx`, gera embeddings dense (`voyage-4-large`) + sparse (BM25)
e indexa no Qdrant — ~100 chunks, cerca de 30 s. Nas seguintes a coleção já existe e vai
direto para o loop de consulta:

```
Query: Quem se encaixa no PRONAF?

[1] Score: 0.8333
    Cap. 10 — Programa Nacional de Fortalecimento da Agricultura Familiar (Pronaf)
    Sec. 2 — Beneficiarios
```

Para reindexar do zero, remova `qdrant_db/` com o container parado e rode `python -m src.main`
novamente.

### Arquitetura

```
data/MCR - docx/
  └── 01 - MCR Normas/
        └── NN - Capítulo/
              └── N_-_Secao.docx
          │
          ▼
    src/ingestion/chunker.py → LangChain Documents (1 doc/seção, split se > 28k tokens)
          │
          ▼
    src/ingestion/indexer.py
      ├── voyage-4-large    → dense embeddings (1024-d, cosine)
      └── Qdrant/bm25       → sparse embeddings
          │
          ▼
    Qdrant server           → coleção "mcr_knowledge_base"
          │
     (query time)
          │
    src/rag/retriever.py
      ├── voyage-4-lite     → dense query embedding
      ├── Qdrant/bm25       → sparse query embedding
      └── RRF Fusion        → top-5 resultados híbridos
```

---

## Extração do PDF

Três extratores independentes geram artefatos a partir de `data/MCR.pdf`. Nenhum é necessário
para rodar o pipeline (os `.docx` já estão versionados). Todos são idempotentes — apague a
saída para forçar a re-extração.

| Módulo (`python -m ...`)              | Saída                  | Requer                        |
|---------------------------------------|------------------------|-------------------------------|
| `src.ingestion.extraction.opendataloader`       | `data/MCR.md`          | servidor `docling-fast` (ver abaixo) |
| `src.ingestion.extraction.adobe_pdfservices`    | `data/MCR_adobe.md`    | credenciais Adobe             |
| `src.ingestion.extraction.adobe_pdf_to_json`    | `data/MCR_adobe.json`  | credenciais Adobe             |

O OpenDataLoader precisa do servidor hybrid num terminal separado, com o venv ativado:

```powershell
opendataloader-pdf-hybrid --port 5002
```

Ele aplica OCR neural nas páginas com fontes CID sem mapeamento Unicode, e exige terminal
como Administrador (ou Modo Desenvolvedor ativo) para criar symlinks no cache de modelos.
Detalhes e o fallback para Java em [docs/extractor.md](docs/extractor.md).

O `adobe_pdf_to_json` produz JSON estruturado (~24 MB) com elementos tipados (H1–H6, P, LI,
Table/TR/TH/TD, Header, Footer), cada um com `Path`, `Page`, `Text`, `Bounds` e `Font`.

---

## Testes

Cobrem o isolamento entre usuários: ninguém lê nem escreve na conversa de outro, mesmo de
posse do `conversation_id`.

```bash
pip install -r requirements-dev.txt
docker compose --profile test up -d postgres-test

TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/ragro_test pytest
```

O serviço `postgres-test` fica atrás do profile `test` — um `docker compose up -d` comum (sem
`--profile test`) não o sobe.

Use o Postgres descartável do compose, **nunca** o Supabase: os testes truncam as tabelas.
Sem `TEST_DATABASE_URL` os testes de banco são pulados e só os de `session_state` e os de
`src/agents`/`src/programs` (offline, sem Vertex/Qdrant/Postgres) rodam.

`tests/schema.sql` é uma **réplica** do schema do Supabase, que foi criado à mão e não é
versionado — ao alterar as tabelas lá, atualize esse arquivo, senão os testes validam um
schema obsoleto.

---

## Estrutura

```
data/
  MCR - docx/            Arquivos .docx do MCR (fonte dos chunks)
docs/
  arquitetura-agentes.md   Fluxo do orquestrador e dos dois agentes
src/
  config.py              load_dotenv, tokenizer Voyage, make_chunk_id
  main.py                Orquestrador CLI
  llm/
    client.py              Único ponto de contato com o Vertex AI (gerar_texto/gerar_json)
  rag/
    qdrant.py              Qdrant client e inicialização da coleção
    retriever.py           Busca híbrida RRF + filtro por metadados
    rewriter.py            Condensação de pergunta + inferência de filtro
    judge.py               LLM-as-a-judge sobre os trechos recuperados
    answer.py              Geração de resposta (Q&A e recomendação do Conselheiro)
    snapshot.py            Formato leve de trechos, para persistir/exibir
  agents/
    types.py               Rota, Resposta — tipos compartilhados
    orchestrator.py        Roteamento entre Q&A e Conselheiro
    qa.py                  Agente Q&A
    advisor.py             Agente Conselheiro (extrai/conduz/recomenda)
  programs/
    base.py                Protocolo comum aos programas de crédito
    triagem.py             Resolve qual programa conduzir
    pronaf/                Engine de regras do PRONAF (ruleset.json)
    pronamp/               Perguntas do PRONAMP (recomendação via RAG)
  storage/
    db.py                  Engine SQLAlchemy para o Postgres (Supabase)
    auth.py                Login/cadastro (hash bcrypt, código de convite)
    chat_history.py        Conversas e mensagens, escopadas por user_id
    advisor_state.py       Sessão do Agente Conselheiro, uma por conversa
  ingestion/
    chunker.py             .docx → LangChain Documents
    indexer.py             Embeddings, upsert e chunk_stats
    extraction/            Extratores PDF (OpenDataLoader, Adobe, Azure)
frontend/
  app.py                 Entrypoint fino: config da página e orquestração de alto nível
  state.py               session_state escopado por usuário
  views/
    auth.py                Login, cadastro e require_login
    sidebar.py             Lista de conversas e configurações de busca
    chat.py                Histórico, chips de opção e o turno de chat
tests/                   Agentes/programas (offline), isolamento entre usuários, sessão
qdrant_db/               Storage do Qdrant via Docker volume (não versionado)
```

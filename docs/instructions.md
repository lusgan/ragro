# Blueprint: Pipeline de Ingestão de Dados e Retrieval (TCC 1)

> **Última atualização**: 2026-05-26 — alinhado com o plano de implementação vigente.

## 1. Visão Geral do Projeto
Este projeto consiste no desenvolvimento do pipeline de ingestão de dados (Data Pipeline) e recuperação (Retriever) para um sistema RAG focado em Crédito Rural. O objetivo desta etapa (TCC 1) não é gerar respostas finais com um LLM, mas sim provar que o sistema consegue ler o Manual de Crédito Rural (MCR), extrair seu conteúdo preservando tabelas, realizar um chunking hierárquico por seção, vetorizar o texto e recuperá-lo com precisão via Busca Híbrida (dense + sparse com RRF).

## 2. Requisitos do Sistema

### 2.1. Requisitos Funcionais (RF)
* **RF01:** O sistema deve ler o arquivo PDF do MCR (focado em Pronaf e Pronamp).
* **RF02:** O sistema deve extrair o texto e tabelas do PDF convertendo para Markdown via `opendataloader-pdf` (sem fallback — requer Java 11+). Tabelas são preservadas em formato Markdown.
* **RF03:** O sistema deve realizar *Chunking Semântico por Seção*. A quebra do texto respeita os limites de TÍTULO / CAPÍTULO / SEÇÃO extraídos dos cabeçalhos de página do MCR via Regex.
* **RF04:** O sistema deve enriquecer os *chunks* com metadados hierárquicos extraídos dos cabeçalhos de página:
  ```python
  {
      "titulo_num": "1", "titulo_text": "CRÉDITO RURAL",
      "capitulo_num": "2", "capitulo_text": "Condições Básicas",
      "secao_num": "1", "secao_text": "Disposições Gerais",
      "source": "MCR.pdf"
  }
  ```
* **RF05:** O sistema deve gerar embeddings densos com `voyage-4-large` (documentos) e `voyage-4-lite` (queries), ambos da série Voyage 4 — espaço vetorial compatível, dimensão 1024.
* **RF06:** O sistema deve inicializar um banco de dados **Qdrant Server** acessível em `http://localhost:6333` (configurável via `QDRANT_URL`), com storage persistido em `./qdrant_db` via Docker volume, coleção `mcr_knowledge_base` com dual vectors: dense (cosine, 1024-dim) + sparse BM25 (`Qdrant/bm25` via fastembed).
* **RF07:** O sistema deve armazenar embeddings densos, sparse BM25, metadados e texto no Qdrant via `PointStruct`.
* **RF08:** O sistema deve fornecer busca híbrida com RRF (Reciprocal Rank Fusion) nativo do Qdrant, combinando dense cosine e sparse BM25 via `Prefetch` + `Query.fusion(Fusion.RRF)`, retornando Top-5 chunks.
* **RF09:** O sistema deve persistir estatísticas de indexação em `reports/ragro.db` (SQLite), tabela `chunk_stats`, para análise e geração futura de gráficos.

### 2.2. Requisitos Não Funcionais (RNF)
* **RNF01:** Código modularizado em Python >= 3.10: `extractor.py`, `chunker.py`, `database.py`, `indexer.py`, `retriever.py`, `main.py`.
* **RNF02:** Uso do framework **LangChain** para representação de documentos (`Document`) e `RecursiveCharacterTextSplitter`.
* **RNF03:** Gestão de credenciais via `.env` (ex: `VOYAGE_API_KEY`); `.env.example` commitado como template.
* **RNF04:** O banco de dados deve salvar o estado localmente — `main.py` verifica existência antes de reprocessar.
* **RNF05:** Pré-requisito externo: **Java 11+** instalado na máquina (exigido pelo `opendataloader-pdf`).

---

## 3. Arquitetura e Stack Tecnológico

| Camada | Tecnologia |
|---|---|
| Linguagem | Python >= 3.10 |
| Extração de PDF | `opendataloader-pdf` → `data/MCR.md` |
| Representação de documentos | LangChain `Document` |
| Embeddings (documentos) | Voyage AI `voyage-4-large` (1024-dim, 32K tokens ctx) |
| Embeddings (queries) | Voyage AI `voyage-4-lite` (compatível com `voyage-4-large`) |
| Sparse vectors | FastEmbed `Qdrant/bm25` |
| Banco vetorial | Qdrant server (`qdrant-client[fastembed]`), `url="http://localhost:6333"`, storage em `./qdrant_db` via Docker volume |
| Busca híbrida | RRF nativo do Qdrant (`Prefetch` + `Fusion.RRF`) |
| Análise / relatórios | SQLite (`reports/ragro.db`), stdlib `sqlite3` |
| Credenciais | `python-dotenv` |

---

## 4. Passo a Passo de Implementação (Roadmap)

### Passo 1: Setup do Ambiente
1. Atualizar `requirements.txt` com: `langchain`, `langchain-qdrant`, `qdrant-client[fastembed]`, `voyageai`, `langchain-voyageai`, `python-dotenv`, `PyPDF2`, `opendataloader-pdf`, `fastembed`.
2. Criar/ativar ambiente virtual (`venv`) e instalar dependências.
3. Criar `.env` a partir de `.env.example` e preencher `VOYAGE_API_KEY`.

### Passo 2: Extração do PDF (`extractor.py`)
1. PDF do MCR já disponível em `data/MCR.pdf` (digital/text-selectable, sem necessidade de OCR).
2. Reescrever `src/extractor.py`: chamar `opendataloader_pdf.convert(input_path=["data/MCR.pdf"], output_dir="data/", format="markdown")` → gera `data/MCR.md`.
3. Se `data/MCR.md` já existir, pular a conversão (idempotente).
4. **Atenção**: inspecionar `MCR.md` gerado antes de finalizar os regex do chunker — os cabeçalhos podem usar formatação diferente da esperada.

### Passo 3: Chunking Inteligente por Seção (`chunker.py`)
1. Iterar `data/MCR.md` linha a linha; detectar cabeçalhos de página via Regex:
   ```python
   re.search(r"TÍTULO\s*:\s*(.+)", line)
   re.search(r"CAPÍTULO\s*:\s*(.+?)\s*-\s*(\d+)", line)
   re.search(r"SEÇÃO\s*:\s*(.+?)\s*-\s*(\d+)", line)
   ```
2. Acumular conteúdo entre um cabeçalho de SEÇÃO e o próximo como um único chunk; criar um `Document` LangChain por SEÇÃO com os 7 campos de metadados.
3. Todo chunk recebe `chunk_index` no metadata com a seguinte semântica: `chunk_index=0` = seção completa (não dividida); `chunk_index=1, 2, 3, …` = sub-chunks resultantes da divisão. Contar tokens via `voyageai.Client().tokenize()`. Se seção > **28.000 tokens**, aplicar `RecursiveCharacterTextSplitter(chunk_size=28000, chunk_overlap=200)` — sub-chunks começam no índice 1 e reiniciam a cada nova SEÇÃO.

### Passo 4: Inicialização do Qdrant Server (`database.py`)
1. Subir o servidor Qdrant via Docker: `docker run -d --name qdrant -p 6333:6333 -p 6334:6334 -v "${PWD}\qdrant_db:/qdrant/storage" qdrant/qdrant`
2. Instanciar `QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))`.
3. Criar coleção `mcr_knowledge_base` com:
   - Dense: `VectorParams(size=1024, distance=Distance.COSINE)`
   - Sparse: `SparseVectorParams()` nomeado `"sparse"` para BM25
3. Se coleção já existir, não recriar (idempotente).

### Passo 5: Vetorização e Indexação (`indexer.py`)
1. Instanciar `voyageai.Client()` — lê `VOYAGE_API_KEY` do `.env`.
2. **Batching dinâmico**: acumular chunks somando tokens; ao atingir 118K tokens (margem abaixo do limite de 120K da API), enviar batch e iniciar o próximo.
3. Chamar `vo.embed(batch_texts, model="voyage-4-large", input_type="document")` por batch.
4. Gerar sparse BM25 vectors via FastEmbed (`Qdrant/bm25`) — IDF computado sobre todo o corpus antes da indexação.
5. Inserir com `PointStruct(id=..., vector={"dense": emb, "sparse": sparse_emb}, payload=metadata + text)`.
6. Ao final, imprimir estatísticas (`statistics` stdlib) e persistir `chunk_stats` em `reports/ragro.db`:
   ```
   Batches enviados      : 8
   Seções por batch      : [14, 12, 15, 11, 13, 14, 12, 9]
   Média seções/batch    : 12.5
   Moda seções/batch     : 14
   Média tokens/seção    : 3 420
   ```
   Schema SQLite:
   ```sql
   CREATE TABLE IF NOT EXISTS chunk_stats (
       id             INTEGER PRIMARY KEY,
       tokens         INTEGER,
       titulo         TEXT,
       capitulo       TEXT,
       secao          TEXT,
       chunk_index    INTEGER,
       chunk_strategy TEXT   -- estratégia atual: 'full_section_32k'
   );
   ```

### Passo 6: Retriever e Busca Híbrida (`retriever.py`)
1. Embeddar query com `vo.embed([query], model="voyage-4-lite", input_type="query")` — compatível com `voyage-4-large` (mesmo espaço vetorial série 4); menor custo e latência.
2. Gerar sparse BM25 vector da query com FastEmbed (`Qdrant/bm25`).
3. Executar `qdrant_client.query_points()` com dois `Prefetch` (dense cosine + sparse BM25) + `Query.fusion(Fusion.RRF)`.
4. Retornar Top-5 chunks com metadados e score.

### Passo 7: Validação e Teste CLI (`main.py`)
1. Verificar se `./qdrant_db` e a coleção existem. Se não, executar pipeline completo: Extrator → Chunker → Indexer.
2. Se existir, abrir loop de input no terminal.
3. Imprimir resultados formatados: metadados (titulo / capitulo / secao) + conteúdo do chunk + score RRF.

---

## 5. Estrutura de Arquivos

| Arquivo / Pasta | Descrição |
|---|---|
| `src/extractor.py` | Conversão MCR.pdf → MCR.md via opendataloader-pdf |
| `src/ingestion/chunker.py` | Parsing Markdown + chunking por seção + sub-chunking |
| `src/rag/qdrant.py` | Qdrant client + criação idempotente da coleção |
| `src/ingestion/indexer.py` | Batching dinâmico + voyage-4-large + BM25 + insert + stats |
| `src/rag/retriever.py` | Busca híbrida RRF (dense + sparse) |
| `src/main.py` | CLI orchestrator — idempotência + loop de queries |
| `requirements.txt` | Dependências Python |
| `.env.example` | Template de credenciais (commitado) |
| `.gitignore` | Ignora `data/MCR.md`, `reports/ragro.db`, `qdrant_db/`, `.env` |
| `data/MCR.pdf` | PDF fonte (não gerado) |
| `data/MCR.md` | Gerado pelo extractor (não commitado) |
| `reports/ragro.db` | SQLite de análise gerado pelo indexer (não commitado) |
| `docs/future-chunk-experiments.md` | Plano de experimentos futuros (Chunk Size vs. Retrieval Accuracy) |
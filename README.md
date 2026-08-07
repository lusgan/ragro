# ragro

RAG sobre o Manual de Crédito Rural (MCR) com busca híbrida (dense + BM25 + RRF) via Voyage AI e Qdrant.

---

## Pré-requisitos

- Python 3.11+
- Chave de API [Voyage AI](https://www.voyageai.com/) (`VOYAGE_API_KEY`)

---

## Instalação

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crie o arquivo `.env` na raiz do projeto:

```env
VOYAGE_API_KEY=sua_chave_voyage
QDRANT_URL=http://localhost:6333
```

Opcionalmente, adicione as credenciais dos extratores (necessárias apenas para re-extrair o MCR):

```env
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=...
AZURE_DOCUMENT_INTELLIGENCE_KEY=...
ADOBE_CLIENT_ID=...
ADOBE_CLIENT_SECRET=...
```

---

## Ferramentas de Extração

O projeto disponibiliza três extratores, cada um gerando um artefato diferente a partir do `data/MCR.pdf`.

---

### Extrator 1 — OpenDataLoader (PDF → Markdown)

**Arquivo:** `src/extraction/opendataloader.py`  
**Saída:** `data/MCR.md`  
**Dependências extras:** servidor `docling-fast` em execução (veja abaixo)

#### Passo a passo

**1. Abrir terminal como Administrador (ou ativar Modo Desenvolvedor)**

> Necessário para que o servidor `docling-fast` crie symlinks no cache de modelos.  
> Alternativa sem admin: `Configurações → Sistema → Para Desenvolvedores → Modo Desenvolvedor → Ativar`.

**2. Ativar o ambiente virtual**

```powershell
.\venv\Scripts\Activate.ps1
```

**3. Subir o servidor hybrid (terminal separado)**

Abra um **segundo terminal** (com o venv ativado) e execute:

```powershell
opendataloader-pdf-hybrid --port 5002
```

Aguarde a mensagem indicando que o servidor está pronto. Mantenha este terminal aberto.

> O servidor aplica OCR neural (`docling-fast`) nas páginas com fontes CID sem mapeamento Unicode.
> Fallback automático para Java garante que o arquivo seja gerado mesmo em caso de falta de RAM.
> Consulte [docs/extractor.md](docs/extractor.md) para detalhes.

**4. Executar a extração**

No terminal principal:

```powershell
python -m src.extraction.opendataloader
```

O arquivo `data/MCR.md` será gerado. A extração é **idempotente** — rodar novamente não reprocessa.  
Para forçar re-extração: `Remove-Item data\MCR.md`.

---

### Extrator 2 — Adobe PDF to Markdown

**Arquivo:** `src/extraction/adobe_pdfservices.py`  
**Saída:** `data/MCR_adobe.md`  
**Dependências extras:** credenciais Adobe no `.env`

#### Passo a passo

**1. Ativar o ambiente virtual**

```powershell
.\venv\Scripts\Activate.ps1
```

**2. Executar a extração**

```powershell
python -m src.extraction.adobe_pdfservices
```

O arquivo `data/MCR_adobe.md` será gerado via Adobe PDF Services API (operação `pdftomarkdown`).
A extração é **idempotente**.  
Para forçar re-extração: `Remove-Item data\MCR_adobe.md`.

---

### Extrator 3 — Adobe PDF to JSON (Estruturado)

**Arquivo:** `src/extraction/adobe_pdf_to_json.py`  
**Saída:** `data/MCR_adobe.json`  
**Dependências extras:** credenciais Adobe no `.env`

Utiliza a operação `extractpdf` da Adobe PDF Services API para extrair o conteúdo do PDF em JSON
estruturado, com elementos tipados (H1–H6, P, LI, Table/TR/TH/TD, Header, Footer), número de
página e bounding box de cada elemento.

#### Estrutura do JSON gerado

| Chave          | Descrição                                                                 |
|----------------|---------------------------------------------------------------------------|
| `elements`     | Array com ~39 000 itens: parágrafos, títulos, células de tabela, etc.     |
| `artifacts`    | Array com ~1 700 itens: cabeçalhos e rodapés de página                    |
| `pages`        | Metadados de cada página (dimensões, número)                              |
| `version`      | Versão do schema Adobe Extract                                            |

Cada elemento possui os campos `Path` (tipo/posição XPath-like), `Page`, `Text`, `Bounds` e `Font`.

#### Passo a passo

**1. Ativar o ambiente virtual**

```powershell
.\venv\Scripts\Activate.ps1
```

**2. Executar a extração**

```powershell
python -m src.extraction.adobe_pdf_to_json
```

O arquivo `data/MCR_adobe.json` será gerado (~24 MB). A extração é **idempotente**.  
Para forçar re-extração: `Remove-Item data\MCR_adobe.json`.

---

## Qdrant (servidor local)

O projeto usa o Qdrant como servidor HTTP local em vez do modo embedded. É necessário tê-lo rodando antes de executar qualquer parte do pipeline.

### Subir o Qdrant

```bash
docker compose up -d
```

Funciona em qualquer terminal (PowerShell, CMD, Git Bash). O volume `qdrant_db/` persiste os dados entre reinicializações. O dashboard web fica disponível em **http://localhost:6333/dashboard**.

### Comandos úteis

```bash
docker compose down        # parar e remover o container (dados preservados)
docker compose logs qdrant # ver logs do servidor
```

---

## Pipeline RAG (indexação + busca)

Os arquivos `.docx` do MCR já estão em `data/MCR - docx/`. Basta executar:

```powershell
python -m src.main
```

**Primeira execução:** lê os `.docx`, gera embeddings dense via `voyage-4-large` + sparse BM25, e indexa no Qdrant (`http://localhost:6333`). Em torno de 100 chunks, ~30 s.

**Execuções seguintes:** a coleção já existe — vai direto para o loop de consulta.

```
=== RAG MCR — Busca Híbrida (Ctrl+C para sair) ===

Query: Quem se encaixa no PRONAF?

[1] Score: 0.8333
    Cap. 10 — Programa Nacional de Fortalecimento da Agricultura Familiar (Pronaf)
    Sec. 2 — Beneficiarios
    ...
```

Para reindexar do zero:

```bash
docker compose down
Remove-Item -Recurse -Force qdrant_db   # PowerShell
# rm -rf qdrant_db                      # Git Bash / Linux
docker compose up -d
python -m src.main
```

---

## Arquitetura do pipeline

```
data/MCR - docx/
  └── 01 - MCR Normas/
        └── NN - Capítulo/
              └── N_-_Secao.docx
          │
          ▼
    src/chunker.py          → LangChain Documents (1 doc/seção, split se > 28k tokens)
          │
          ▼
    src/indexer.py
      ├── voyage-4-large    → dense embeddings (1024-d, cosine)
      └── Qdrant/bm25       → sparse embeddings
          │
          ▼
    Qdrant server           → coleção "mcr_knowledge_base" (http://localhost:6333)
          │
     (query time)
          │
    src/retriever.py
      ├── voyage-4-lite     → dense query embedding
      ├── Qdrant/bm25       → sparse query embedding
      └── RRF Fusion        → top-5 resultados híbridos
```

---

## Estrutura

```
data/
  MCR - docx/            Arquivos .docx do MCR (fonte dos chunks)
  MCR_images/            Imagens extraídas
docs/                    Documentação técnica
src/
  config.py              load_dotenv, tokenizer Voyage, make_chunk_id
  chunker.py             .docx → LangChain Documents
  database.py            Qdrant client e inicialização da coleção
  db.py                  Engine SQLAlchemy para o Postgres (Supabase)
  auth.py                Login/cadastro (hash bcrypt, código de convite)
  indexer.py             Embeddings (voyage-4-large + BM25), upsert e chunk_stats (Postgres)
  retriever.py           Busca híbrida RRF (voyage-4-lite + BM25)
  main.py                Orquestrador CLI
  extraction/
    opendataloader.py    PDF → Markdown (OpenDataLoader + docling)
    adobe_pdfservices.py PDF → Markdown (Adobe PDF Services)
    adobe_pdf_to_json.py PDF → JSON estruturado (Adobe Extract)
    azure_di.py          PDF → Markdown (Azure Document Intelligence)
qdrant_db/               Storage do Qdrant montado via Docker volume (não versionado)
```


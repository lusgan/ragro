# ragro

RAG sobre o Manual de Crédito Rural (MCR).

---

## Pré-requisitos

- Python 3.11+
- Java 11+ instalado e no `PATH`
- terminal rodando como Administrador (necessário para symlinks do HuggingFace cache)

---

## Instalação

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copie o arquivo de variáveis de ambiente e preencha as chaves:

```powershell
Copy-Item .env.example .env
# Edite .env e preencha:
#   VOYAGE_API_KEY=sua_chave
#   ADOBE_CLIENT_ID=seu_client_id
#   ADOBE_CLIENT_SECRET=seu_client_secret
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

## Pipeline RAG (indexação + busca)

Após gerar `data/MCR.md` com o Extrator 1:

```powershell
python -m src.main
```

Na primeira execução, o pipeline indexa o MCR.md no Qdrant. Nas execuções seguintes, vai direto
para o loop de consulta.

---

## Estrutura

```
data/                    PDFs, Markdowns e JSONs (não versionados)
docs/                    Documentação técnica
docs/proximos_passos/    Plano de evolução do pipeline
reports/                 Banco SQLite com estatísticas de chunks
src/
  config.py              Configuração central, tokenizer, ChunkStrategy
  chunker.py             Markdown → LangChain Documents
  database.py            Qdrant client e inicialização da coleção
  indexer.py             Embeddings (Voyage + BM25) e indexação
  retriever.py           Busca híbrida RRF
  main.py                Orquestrador CLI
  extraction/
    opendataloader.py    PDF → Markdown (OpenDataLoader + docling)
    adobe_pdfservices.py PDF → Markdown (Adobe PDF Services)
    adobe_pdf_to_json.py PDF → JSON estruturado (Adobe Extract)
qdrant_db/               Índice vetorial local (não versionado)
```


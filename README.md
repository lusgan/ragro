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

Copie o arquivo de variáveis de ambiente e preencha sua chave:

```powershell
Copy-Item .env.example .env
# Edite .env e insira VOYAGE_API_KEY=sua_chave
```

---

## Execução

### 1. Abrir terminal como Administrador (ou ativar Modo Desenvolvedor)

> Necessário para que o servidor `docling-fast` crie symlinks no cache de modelos.
> Alternativa sem admin: `Configurações → Sistema → Para Desenvolvedores → Modo Desenvolvedor → Ativar`.

### 2. Ativar o ambiente virtual

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Subir o servidor hybrid (terminal separado)

Abra um **segundo terminal** (também com o venv ativado) e execute:

```powershell
opendataloader-pdf-hybrid --port 5002
```

Aguarde a mensagem indicando que o servidor está pronto. Mantenha este terminal aberto durante toda
a extração.

> O servidor aplica OCR neural (`docling-fast`) nas páginas do PDF com fontes CID sem mapeamento
> Unicode. Se falhar por falta de RAM, o fallback automático para Java garante que o arquivo seja
> gerado mesmo assim. Consulte [docs/extractor.md](docs/extractor.md) para detalhes e limitações.

### 4. Extrair o PDF

No terminal principal (com venv ativo):

```powershell
python -c "from src.extractor import extract; extract(use_hybrid=True)"
```

O arquivo `data/MCR.md` será gerado. A extração é idempotente — rodar novamente não reprocessa.
Para forçar re-extração: `Remove-Item data\MCR.md`.

### 5. Rodar o pipeline completo (indexação + busca)

```powershell
python -m src.main
```

Na primeira execução, o pipeline indexa o MCR.md no Qdrant. Nas execuções seguintes, vai direto
para o loop de consulta.

---

## Estrutura

```
data/          PDFs e Markdowns (não versionados)
docs/          Documentação técnica
reports/       Banco SQLite com estatísticas de chunks
src/
  config.py    Configuração central, tokenizer, ChunkStrategy
  extractor.py PDF → Markdown
  chunker.py   Markdown → LangChain Documents
  database.py  Qdrant client e inicialização da coleção
  indexer.py   Embeddings (Voyage + BM25) e indexação
  retriever.py Busca híbrida RRF
  main.py      Orquestrador CLI
qdrant_db/     Índice vetorial local (não versionado)
```


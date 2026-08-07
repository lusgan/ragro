# frontend

Interface web (Streamlit) para o RAG do MCR. Faz a mesma consulta híbrida (dense + BM25 + RRF)
executada por `python -m src.main`, porém com tela em vez de terminal.

Não é um serviço separado: roda no mesmo ambiente virtual do `ragro` e importa `src/` diretamente
(sem API HTTP intermediária).

---

## Pré-requisitos

- Ambiente do projeto raiz já configurado (`venv`, `requirements.txt`, `.env` com `VOYAGE_API_KEY`)
- Qdrant rodando: `docker compose up -d` (na raiz do projeto)

## Executar

Na raiz do projeto, com o venv ativado:

```powershell
streamlit run frontend/app.py
```

Abre em `http://localhost:8501`.

- Se a coleção `mcr_knowledge_base` ainda não existir no Qdrant, a tela mostra um botão
  **"Indexar agora"** que roda o mesmo pipeline de indexação do `src/main.py`.
- O modo de busca (Híbrida / Dense / Sparse) fica na barra lateral, equivalente ao comando
  `:modo` do CLI.

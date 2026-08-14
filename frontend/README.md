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

- O app **só consulta** — não indexa. A indexação é um passo offline (`python -m src.main`), que
  depende dos `.docx` do MCR, e esses são `.gitignore`d. Se a coleção `mcr_knowledge_base` não
  existir no cluster apontado por `QDRANT_URL`, o app para com erro em vez de tentar indexar.
- O modo de busca (Híbrida / Dense / Sparse) fica na barra lateral, equivalente ao comando
  `:modo` do CLI.

---

## Deploy (Streamlit Community Cloud)

Pré-requisitos, todos fora do Streamlit:

- **Qdrant Cloud** com a coleção `mcr_knowledge_base` já indexada (`QDRANT_URL`/`QDRANT_API_KEY` —
  ver README da raiz). Indexe localmente apontando o `.env` para o cluster de produção.
- **Supabase** com as tabelas `users`, `invite_codes`, `conversations` e `messages` criadas.
- **Vertex AI** habilitado no projeto GCP, com uma service account com `roles/aiplatform.user`.

Passos:

1. Suba o repo pro GitHub (se ainda não estiver lá).
2. Em [share.streamlit.io](https://share.streamlit.io), "New app" → selecione o repo/branch e
   defina **Main file path**: `frontend/app.py`.
3. Em **Advanced settings**, escolha **Python 3.12** (mesma versão do venv local).
4. O Streamlit Cloud usa o arquivo de dependências mais próximo do entrypoint, ou seja
   `frontend/requirements.txt`, e não o `requirements.txt` da raiz — este traz as dependências
   pesadas da ingestão (`opendataloader-pdf[hybrid]`/docling, Azure, `transformers`,
   `python-docx`) que o app não usa. Nenhum módulo do pipeline de indexação é importado por
   `app.py`.
5. Ainda em **Advanced settings → Secrets**, cole (substituindo pelos valores reais do seu `.env`):

   ```toml
   VOYAGE_API_KEY = "..."
   QDRANT_URL = "https://xxxxx.cloud.qdrant.io"
   QDRANT_API_KEY = "..."
   DATABASE_URL = "postgresql+psycopg://postgres:...@...:5432/postgres"
   AUTH_COOKIE_KEY = "..."
   GOOGLE_CLOUD_PROJECT = "..."
   GOOGLE_CLOUD_LOCATION = "us-central1"
   GCLOUD_SA_BASE64 = "..."
   ```

   O Streamlit expõe cada chave de `secrets.toml` também via `os.environ`/`os.getenv`
   automaticamente, então nenhum código muda — é o mesmo `os.environ[...]` usado localmente com
   `.env`.
6. Deploy. O primeiro acesso é mais lento: o `fastembed` baixa o modelo `Qdrant/bm25` do
   HuggingFace na primeira chamada ao BM25 e o resultado fica em `st.cache_resource`.

### Depois do deploy

- Cadastro exige **código de convite** (tabela `invite_codes`). Insira códigos manualmente no
  Supabase para liberar novas contas — não há tela de admin.
- `DATABASE_URL` é uma credencial de banco com privilégio total (o RLS das tabelas não se aplica
  ao papel `postgres`). Vale criar um papel dedicado com permissão só nas quatro tabelas do app.
- `GCLOUD_SA_BASE64` é uma chave de service account guardada num host de terceiro. Mantenha o
  escopo mínimo (`roles/aiplatform.user`) e rotacione se o repo virar público.

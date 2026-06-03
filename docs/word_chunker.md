# Extração e Chunking de Documentos .docx do MCR

## Visão Geral

O MCR (Manual de Crédito Rural) é publicado pelo BCB (Banco Central do Brasil) como um conjunto de arquivos `.docx`, organizados em capítulos e seções. O módulo `src/word_chunker.py` é responsável por converter esses arquivos em `Document`s do LangChain, prontos para indexação no Qdrant.

---

## Estrutura de Diretórios Esperada

```
data/MCR - docx/
└── 01 - MCR Normas/
    ├── 01 - Disposições Preliminares/
    │   ├── 1_-_Autorizacao_para_Operar_em_Credito_Rural_e_Estrutura_Operativa.docx
    │   └── 2_-_Beneficiarios.docx
    ├── 02 - Condições Básicas/
    │   ├── 1_-_Disposicoes_Gerais.docx
    │   └── ...
    └── ...
```

- A pasta raiz contém `01 - MCR Normas/`.
- Cada subpasta representa um **capítulo** com nome no formato `NN - Título`.
- Cada `.docx` dentro da pasta de capítulo representa uma **seção**, com nome no formato `N_-_Titulo_da_Secao.docx`.
- O capítulo `00` (Índice) é ignorado automaticamente por não ser conteúdo normativo.

---

## Pipeline de Processamento

```
Pasta de capítulos
      │
      ▼
[1] Parsing de metadados          ← nomes de pasta/arquivo
      │
      ▼
[2] Extração de conteúdo docx     ← python-docx (parágrafos + tabelas)
      │
      ▼
[3] Serialização de tabelas       ← deduplicação de células mescladas
      │
      ▼
[4] Contagem de tokens            ← voyageai/voyage-4-large tokenizer
      │
      ├── ≤ TOKEN_LIMIT (28 000) → 1 Document por seção
      │
      └── > TOKEN_LIMIT          → subdivisão com RecursiveCharacterTextSplitter
```

---

## Etapas em Detalhe

### 1. Parsing de Metadados

**Função:** `_parse_cap_folder(name)` e `_parse_sec_file(stem)`

Os nomes de pasta e arquivo seguem um padrão numérico que é extraído via regex:

| Padrão de entrada | Saída |
|---|---|
| `01 - Disposições Preliminares` | `(1, "Disposições Preliminares")` |
| `1_-_Autorizacao_para_Operar...` | `(1, "Autorizacao para Operar...")` |
| `4-A_-_Metodologia...` | `(4, "Metodologia...")` |
| `10_-_Normas_Transitorias` | `(10, "Normas Transitorias")` |

Os sufixos alfabéticos (`4-A`) são suportados: o número inteiro é extraído normalmente.

---

### 2. Extração de Conteúdo do .docx

**Função:** `_extract_content(docx_path)`

A extração percorre o XML do `body` do documento diretamente (em vez de usar `doc.paragraphs` e `doc.tables` separadamente), o que **preserva a ordem original** de parágrafos e tabelas intercalados.

Para cada nó filho do `body`:

- **`<w:p>` (parágrafo):**
  - Parágrafos com estilo `Header*` são descartados (são títulos do próprio documento, não conteúdo normativo).
  - Parágrafos vazios são descartados.
  - Os demais são adicionados como texto plano.

- **`<w:tbl>` (tabela):**
  - Serializados via `_table_to_text()` (descrito abaixo).
  - Tabelas que resultam em texto vazio são descartadas.

---

### 3. Serialização de Tabelas

**Função:** `_table_to_text(table)`

O `python-docx` repete o conteúdo de células mescladas para cada coluna dentro do span de merge. Sem tratamento, isso gera texto duplicado.

A solução usa **identidade do elemento XML** (`cell._tc`) para deduplicar células por linha:

```python
seen_tc: list = []
unique_cells = []
for cell in row.cells:
    if cell._tc not in seen_tc:
        seen_tc.append(cell._tc)
        unique_cells.append(cell)
```

Após a deduplicação, a linha é serializada conforme o número de células únicas não-vazias:

| Células únicas não-vazias | Resultado |
|---|---|
| 0 | linha ignorada |
| 1 | texto simples (ex: cabeçalho de seção da tabela) |
| N | `"val1 \| val2 \| val3"` |

---

### 4. Controle de Tokens e Subdivisão

**Função:** `_build_docs(content, meta)`

O tokenizador utilizado é o `voyageai/voyage-4-large` (carregado via `AutoTokenizer.from_pretrained()`), com limite de **28 000 tokens** por chunk (`TOKEN_LIMIT`).

- Se a seção **cabe no limite**: gera 1 `Document` com `chunk_index=0` e `total_chunks=1`.
- Se a seção **excede o limite**: divide com `RecursiveCharacterTextSplitter` configurado com `chunk_size=TOKEN_LIMIT` e `chunk_overlap=200`, usando `count_tokens` como `length_function`.

Na prática, com o MCR atual, apenas 2 seções são subdivididas:
- Cap. 2, Sec. 4 — *Metodologia de Cálculo das Taxas de Juros*
- Cap. 12, Sec. 10 — *Alíquotas Básicas do Adicional*

---

## Metadados por Document

Cada `Document` produzido contém os seguintes campos em `metadata`:

| Campo | Tipo | Descrição |
|---|---|---|
| `capitulo_num` | `int` | Número do capítulo |
| `capitulo_text` | `str` | Título do capítulo |
| `secao_num` | `int` | Número da seção |
| `secao_text` | `str` | Título da seção |
| `source` | `str` | Caminho relativo do `.docx` de origem |
| `chunk_index` | `int` | Índice do sub-chunk (0 se seção não foi dividida) |
| `total_chunks` | `int` | Total de sub-chunks desta seção |

---

## API Pública

```python
from src.word_chunker import get_all_chunks_from_docx

docs = get_all_chunks_from_docx("data/MCR - docx")
# → list[Document], ~100 Documents a partir de 98 seções
```

**Parâmetro:** caminho para a pasta raiz que contém `01 - MCR Normas/`. Se a pasta `01 - MCR Normas` não for encontrada, o caminho passado é usado diretamente como fallback.

**Retorno:** lista de `Document`s ordenada por `(capitulo_num, secao_num, chunk_index)`.

---

## Resultados com o MCR Atual

| Métrica | Valor |
|---|---|
| Arquivos `.docx` processados | 98 |
| Documents gerados | 100 |
| Seções subdivididas | 2 |
| Tokens por seção — mínimo | 134 |
| Tokens por seção — máximo | 48 226 |
| Tokens por seção — média | 2 988 |
| Tokens por seção — mediana | 1 732 |

---

## Dependências Relevantes

| Biblioteca | Uso |
|---|---|
| `python-docx` | Leitura de `.docx` e acesso ao XML interno |
| `langchain-core` | Tipo `Document` |
| `langchain-text-splitters` | `RecursiveCharacterTextSplitter` |
| `transformers` | Tokenizador `voyageai/voyage-4-large` |

# Próximos Passos — Estratégia de Chunking com JSON Estruturado

## Contexto

O arquivo `data/MCR_adobe.json` contém o conteúdo do MCR extraído via Adobe Extract PDF em formato
estruturado (~39 000 elementos tipados). Essa riqueza estrutural permite construir um pipeline de
chunking superior ao baseado apenas em markdown, pois combina:

- **Texto limpo para embedding** — gerado via conversão JSON → Markdown controlada
- **Metadados ricos para filtragem** — extraídos diretamente da estrutura hierárquica do JSON

---

## Fase 1 — JSON → Markdown controlado

### Objetivo

Gerar um arquivo `data/MCR_json.md` a partir do `MCR_adobe.json`, com controle total sobre a
formatação de cabeçalhos e tabelas. Isso resolve os problemas dos markdowns existentes:

| Problema                        | MCR.md (OpenDataLoader) | MCR_adobe.md (Adobe PDF→MD) | MCR_json.md (novo) |
|---------------------------------|-------------------------|-----------------------------|--------------------|
| Cabeçalhos de página ausentes   | ✗ (sem `include_header_footer`) | parcial | ✓ via `artifacts` |
| Tabelas malformadas             | frequente               | inconsistente               | ✓ serialização controlada |
| Hierarquia H1–H6 preservada     | parcial                 | inconsistente               | ✓ via `Path`       |

### Lógica de conversão

1. **Construir dicionário de cabeçalhos por página** a partir de `artifacts[]`:
   - Filtrar itens com `Path` iniciando em `//Document/Header`
   - Mapear `Page → Text` para uso como contexto de seção nos chunks

2. **Mapear `Path` para sintaxe Markdown**:
   ```
   //Document/H1[N]        →  # Texto
   //Document/H2[N]        →  ## Texto
   //Document/H3[N]        →  ### Texto
   //Document/P[N]         →  Texto\n
   //Document/LI[N]        →  - Texto
   //Document/Table[N]/... →  tabela serializada (ver abaixo)
   ```

3. **Serialização de tabelas**:
   - Agrupar elementos por `Table[N]` → `TR[N]` em ordem de `Path`
   - Montar tabela Markdown padrão com `TH` como cabeçalho e `TD` como dados
   - Para tabelas com células mescladas (detectáveis por lacunas no índice de `TR`/`TD`):
     usar os CSVs do `resource.downloadUri` do Adobe Extract como fallback
   - Exemplo de saída:
     ```markdown
     | Modalidade | Taxa | Prazo |
     |------------|------|-------|
     | Custeio    | 7%   | 1 ano |
     ```

4. **Preservar números de página** como comentários HTML para rastreabilidade:
   ```markdown
   <!-- page: 42 -->
   ```

---

## Fase 2 — Chunking híbrido (JSON + Markdown)

### Objetivo

Construir um novo `src/chunker.py` que use o `MCR_json.md` como fonte de texto para embedding
e o `MCR_adobe.json` como fonte de metadados.

### Estratégia de metadados

Os cabeçalhos de página nos `artifacts[]` seguem o padrão:

```
"MANUAL DE CRÉDITO RURAL (MCR)\nCapítulo 3 — Título X\nSeção 3-1 — Crédito de Custeio"
```

A partir desse texto, extrair via regex:

| Metadado        | Regex (exemplo)                        | Exemplo de valor     |
|-----------------|----------------------------------------|----------------------|
| `titulo_num`    | `Título\s+(\d+)`                       | `3`                  |
| `capitulo_num`  | `Capítulo\s+([\d\-]+)`                 | `3`                  |
| `secao_num`     | `Seção\s+([\d\-]+)`                    | `3-1`                |
| `page_start`    | campo `Page` do primeiro elemento      | `42`                 |

### Estratégia de chunking

- **Unidade de chunk**: seção semântica delimitada por cabeçalhos H2/H3 do JSON
- **Tamanho alvo**: ~512 tokens (configurável via `src/config.py`)
- **Overlap**: ~64 tokens entre chunks consecutivos de mesma seção
- **Tabelas**: cada tabela serializada é mantida inteira em um único chunk (não dividida)
  com metadado adicional `contains_table: true`
- **Metadados por chunk** (armazenados no Qdrant payload):
  ```python
  {
      "titulo_num": int,
      "capitulo_num": str,
      "secao_num": str,
      "page_start": int,
      "contains_table": bool,
      "source": "MCR_adobe.json"
  }
  ```

---

## Diagrama do fluxo

```
MCR.pdf
  ├─→ [adobe_pdf_to_json.py]  →  data/MCR_adobe.json  (estrutura + metadados)
  │                                       │
  │                             [json_to_markdown.py]  (a implementar)
  │                                       │
  │                               data/MCR_json.md     (texto limpo)
  │                                       │
  └──────────────────────────────→ [chunker.py]  →  LangChain Documents
                                          │           (texto + metadados)
                                          │
                                    [indexer.py]  →  Qdrant (Voyage + BM25)
```

---

## Arquivos a criar/modificar

| Arquivo                              | Ação        | Descrição                                      |
|--------------------------------------|-------------|------------------------------------------------|
| `src/extraction/json_to_markdown.py` | **Criar**   | Converte MCR_adobe.json → MCR_json.md          |
| `src/chunker.py`                     | **Refatorar** | Usar MCR_json.md + metadados do JSON          |
| `src/config.py`                      | Ajustar     | Apontar para nova fonte de markdown            |
| `data/MCR_json.md`                   | Gerado      | Markdown controlado (não versionado)           |

---

## Ordem de execução recomendada

```powershell
# 1. Garantir que o JSON existe (já gerado)
#    data/MCR_adobe.json ✓

# 2. Gerar o markdown a partir do JSON
python -m src.extraction.json_to_markdown

# 3. Rodar o pipeline
python -m src.main
```

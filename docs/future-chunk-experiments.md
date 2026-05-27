# Experimentos Futuros: Chunk Size vs. Retrieval Accuracy

> **Status**: planejado para TCC 2 — não implementado.
> Depende da pipeline base estar funcional (`main.py` + coleção `mcr_full_section`).

---

## Objetivo

Determinar o tamanho de chunk que maximiza a qualidade de recuperação no corpus MCR,
medido por **Hit Rate** e **MRR (Mean Reciprocal Rank)** sobre um ground truth anotado.

---

## Estratégias a comparar

| ID da estratégia (`chunk_strategy`) | Coleção Qdrant | Descrição |
|---|---|---|
| `fixed_500` | `mcr_500` | Chunks fixos de 500 tokens, overlap 50 |
| `fixed_1000` | `mcr_1000` | Chunks fixos de 1000 tokens, overlap 100 |
| `fixed_4000` | `mcr_4000` | Chunks fixos de 4000 tokens, overlap 200 |
| `full_section_32k` | `mcr_full_section` | Seção inteira (estratégia atual do TCC 1), sub-chunked apenas se > 28K tokens |

Cada estratégia gera uma **coleção Qdrant separada** com o mesmo schema de vetores
(dense `voyage-4-large` 1024-dim + sparse BM25), diferenciadas apenas pelo nome.

---

## Ground Truth

- Anotar manualmente **N perguntas** (sugestão: 50–100) cobrindo Pronaf, Pronamp e condições gerais do MCR
- Para cada pergunta, identificar o(s) chunk(s) corretos (IDs Qdrant) — pode ser mais de um
- Salvar em `reports/ground_truth.json`:
  ```json
  [
    {
      "query": "Qual a renda bruta máxima para o Pronaf?",
      "relevant_ids": [42, 43]
    }
  ]
  ```

---

## Métricas

### Hit Rate (Recall@K)
Proporção de queries em que pelo menos um chunk relevante aparece no Top-K:

$$\text{Hit Rate} = \frac{|\{q : \text{relevant} \cap \text{Top-K}(q) \neq \emptyset\}|}{|Q|}$$

### MRR (Mean Reciprocal Rank)
Posição média do primeiro resultado relevante:

$$\text{MRR} = \frac{1}{|Q|} \sum_{q=1}^{|Q|} \frac{1}{\text{rank}_q}$$

Avaliar com **K = 1, 3, 5**.

---

## Implementação sugerida

1. Criar `src/evaluator.py`:
   - Carregar `reports/ground_truth.json`
   - Para cada query, executar busca híbrida RRF em cada coleção (reutilizar `retriever.py`)
   - Calcular Hit Rate@K e MRR para cada estratégia
   - Salvar resultados em `reports/ragro.db`, tabela `eval_results`:
     ```sql
     CREATE TABLE IF NOT EXISTS eval_results (
         strategy     TEXT,
         k            INTEGER,
         hit_rate     REAL,
         mrr          REAL,
         evaluated_at TEXT   -- ISO datetime
     );
     ```

2. Criar `reports/chunk_comparison.ipynb` (notebook):
   - Carregar `eval_results` do SQLite
   - Gerar gráficos: Hit Rate@K por estratégia, MRR por estratégia, distribuição de tokens por coleção
   - Usar `matplotlib` / `seaborn`

---

## Dependências adicionais (TCC 2)

```
pandas
matplotlib
seaborn
jupyter
```

---

## Referência

- Lewis et al. (2020) — *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*
- Voyage AI docs — recomendações de chunk size por domínio

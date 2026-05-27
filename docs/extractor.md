# Extractor — Conversão de PDF para Markdown

## Visão Geral

O módulo `src/extractor.py` converte o arquivo `data/MCR.pdf` em `data/MCR.md` utilizando o
[OpenDataLoader PDF](https://pypi.org/project/opendataloader-pdf/), uma biblioteca Java-based que
expõe uma API Python. A extração é **idempotente**: se `MCR.md` já existir, a função retorna
imediatamente sem reprocessar.

---

## Função `extract()`

```python
def extract(
    pdf_path: str = "data/MCR.pdf",
    md_path:  str = "data/MCR.md",
    use_hybrid: bool = False,
) -> str
```

### Parâmetros

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pdf_path` | `str` | `"data/MCR.pdf"` | Caminho para o PDF de entrada. |
| `md_path` | `str` | `"data/MCR.md"` | Caminho do arquivo Markdown de saída. |
| `use_hybrid` | `bool` | `False` | Ativa o backend OCR `docling-fast` para páginas com fontes CID sem mapeamento Unicode. Requer servidor rodando. |

### Retorno

Retorna o caminho `md_path` após extração bem-sucedida (ou imediatamente se o arquivo já existir).

### Exceções

| Exceção | Quando ocorre |
|---|---|
| `FileNotFoundError` | `pdf_path` não existe. |
| `RuntimeError` | `opendataloader-pdf` não instalado, Java ausente, ou `MCR.md` não foi gerado ao final. |

---

## Modo Padrão (sem hybrid)

```python
extract()                    # usa use_hybrid=False
```

O extrator Java analisa as fontes do PDF e extrai o texto diretamente. Funciona bem para a maioria
das páginas do MCR.

**Limitação:** páginas com fontes CID (codificação proprietária sem mapa Unicode) produzem
caracteres `U+FFFD` (símbolo de substituição). Exemplo de aviso no log:

```
WARNING: Page 248: 89% of characters are replacement characters (U+FFFD).
This PDF likely contains CID-keyed fonts without ToUnicode mappings.
```

Essas seções ficam com texto ilegível no Markdown resultante.

---

## Modo Hybrid (`use_hybrid=True`)

```python
extract(use_hybrid=True)
```

Ativa o backend `docling-fast`, que aplica OCR neural (baseado em [Docling](https://github.com/DS4SD/docling))
nas páginas identificadas pelo triage automático como problemáticas.

O fluxo interno é:

```
PDF → Triage (Java)
         ├── páginas normais → pipeline Java
         └── páginas CID/problemáticas → backend docling-fast (OCR)
                                               └── [falha] → fallback Java (hybrid_fallback=True)
```

O parâmetro `hybrid_fallback=True` (fixo no código) garante que, se o backend OCR falhar para
alguma página, o Java assume como fallback em vez de abortar toda a extração.

### Pré-requisitos

1. Instalar o extra: `pip install "opendataloader-pdf[hybrid]"`
2. Servidor `docling-fast` rodando **antes** de chamar `extract()`:
   ```powershell
   opendataloader-pdf-hybrid --port 5002
   ```

---

## Limitações Conhecidas

### 1. Memória RAM — `std::bad_alloc`

O servidor `docling-fast` é um processo Python/C++ com modelos de ML carregados em memória.
Ao processar batches grandes de páginas (ex.: 103 páginas de uma vez), pode ocorrer:

```
ERROR - Stage preprocess failed for run 1, pages [140]: std::bad_alloc
WARNING: Backend chunk failed (pages 1-143): status 500
```

`std::bad_alloc` é um erro de alocação de memória em C++ — o servidor ficou sem RAM disponível.
Após o crash, as batches seguintes falham com `Failed to connect to localhost:5002` pois o processo
morreu.

**Comportamento com `hybrid_fallback=True`:** as páginas que falharam no OCR são processadas pelo
Java (com possível degradação de qualidade nas fontes CID), mas a extração **não é abortada** e o
`MCR.md` é gerado normalmente.

**Mitigações possíveis:**
- Fechar outros processos pesados antes de rodar o servidor hybrid
- Aguardar o servidor ter mais RAM disponível (não há parâmetro de batch size acessível pelo cliente)
- Aceitar a qualidade mista: páginas normais com texto limpo, páginas CID com Java fallback

### 2. Symlinks no Windows — Permissão

O HuggingFace Hub (usado pelo `docling-fast` para cache de modelos) tenta criar symlinks no
Windows. Sem permissão, o servidor pode falhar ao inicializar os modelos.

**Solução:** ativar o Modo Desenvolvedor do Windows (`Configurações → Sistema → Para Desenvolvedores
→ Modo Desenvolvedor`) ou rodar o terminal do servidor como Administrador.

### 3. Fontes CID Persistentes

Páginas com fontes CID que falharam no OCR (por RAM) continuarão com `U+FFFD` no Markdown.
Isso afeta as seções correspondentes no RAG — os chunks dessas páginas terão tokens de baixa
qualidade semântica.

### 4. Idempotência — Re-extração

Para forçar uma nova extração (ex.: após resolver problemas de RAM), é necessário deletar
manualmente o `MCR.md`:

```powershell
Remove-Item data\MCR.md
python -c "from src.extractor import extract; extract(use_hybrid=True)"
```

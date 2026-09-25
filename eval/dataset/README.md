# Conjunto-padrão — rascunho de candidatas

Etapa 2 do cronograma de avaliação (ver o protocolo completo): geração das
150–200 candidatas que, depois de filtradas e curadas, viram o conjunto-padrão
de 60–100 perguntas usado nas Camadas 1–2 (avaliação automática) e na sessão
com o Sicredi (Camada 3).

## Arquivos

- **`candidatas.jsonl`** — fonte de verdade. Uma pergunta por linha, campos
  descritos abaixo.
- **`candidatas.csv`** — mesma informação, gerada a partir do `.jsonl`, para
  curadoria em planilha (Excel/Sheets). UTF-8 com BOM, abre corretamente com
  acentuação no Excel.
- **`gerar_candidatas.py`** *(fica em runbook, não versionado aqui)* — script
  que gerou os arquivos acima; ver seção "Como foram geradas" abaixo caso
  precise reexecutar ou auditar a proveniência de alguma linha.

## Esquema (`candidatas.jsonl`)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | string | `C-<CAT>-<NNN>`, onde `CAT` ∈ `SIM, ELG, NUM, REF, CMP, ABS`. |
| `categoria` | string | Uma das 6 categorias da Seção 6.1 do protocolo (ver tabela abaixo). |
| `evolucao` | string | Tipo de evolução no estilo RAGAS: `simples`, `condicional`, `multi_contexto`, ou `fora_de_escopo` (só para `abstencao`, que não é um tipo RAGAS). |
| `pergunta` | string | O texto da pergunta candidata. |
| `capitulo` | int\|null | Capítulo do MCR de onde a pergunta foi ancorada (a fonte *principal*, quando há mais de uma). `null` para `abstencao`. |
| `secao` | string\|null | Rótulo da seção dentro do capítulo (`secao_label`, não o índice — corresponde ao metadado usado por `src/ingestion/chunker.py`). |
| `referencias_mcr` | string\|null | Todos os pontos do manual citados (ex.: `"MCR 7-4, MCR 8-1"`), incluindo os de `referencia_cruzada`/`comparacao_programas` que tocam mais de uma seção. |
| `trecho_fonte` | string\|null | Trecho literal (ou próximo disso) copiado das fichas de fatos que ancoram a pergunta — **ver ressalva de verificação abaixo**. `null` quando a pergunta é deliberadamente fora de escopo (`abstencao`) e não há trecho do MCR a citar. |
| `resposta_rascunho` | string | Rascunho de resposta, para orientar quem for revisar — **não é gabarito validado**; é isso que a Seção 7 (sessão com o Sicredi) e a curadoria humana da Seção 6.2 devem confirmar, corrigir ou reescrever. |

## Distribuição por categoria (180 candidatas, dentro da faixa 150–200 da Seção 6)

| Categoria | Código | N | % |
|---|---|---|---|
| Consulta factual simples | `consulta_simples` | 36 | 20% |
| Elegibilidade / exclusão | `elegibilidade` | 36 | 20% |
| Limites numéricos | `limites_numericos` | 27 | 15% |
| Referência cruzada | `referencia_cruzada` | 27 | 15% |
| Comparação entre programas | `comparacao_programas` | 27 | 15% |
| Fora de escopo (isca de abstenção) | `abstencao` | 27 | 15% |

A proporção replica exatamente a estratificação proposta na Seção 6.1 do
protocolo.

## Cobertura por capítulo do MCR

As candidatas cobrem os 12 capítulos do MCR, com ênfase proporcional maior em
Pronaf (Cap. 10), Pronamp (Cap. 8) e Proagro (Cap. 12) — que são também o foco
do Agente Conselheiro — mas sem excluir os demais capítulos (Condições
Básicas, Operações, Recursos, InvestAgro, Funcafé etc.), para que o conjunto
sirva também ao Agente Q&A em perguntas fora do escopo Pronaf/Pronamp.

## Como foram geradas (proveniência)

1. **Extração de fatos** — 4 agentes leram `reports/chunks_dump.txt` (dump de
   todos os 100 chunks indexados do MCR, gerado por
   `scripts/export_chunks.py`) em paralelo, cada um cobrindo uma faixa de
   capítulos, e produziram fichas de fatos (números-chave, regras de
   elegibilidade, jargão, referências cruzadas, trechos-fonte literais) por
   seção. Essas fichas **não foram versionadas** (ficaram no scratchpad da
   sessão) — se precisar reauditar a extração, releia
   `reports/chunks_dump.txt` diretamente.
2. **Composição das candidatas** — eu (Claude) escrevi as 180 perguntas e
   rascunhos de resposta com base nessas fichas, seguindo os tipos de
   evolução do RAGAS (simples/condicional/multi-contexto) como guia de
   variação de dificuldade, mencionado na Seção 6.2 do protocolo.
3. **Gerador ≠ respondedor** — as perguntas foram rascunhadas por um modelo
   de família diferente (Claude) do que o ragro usa para responder (Gemini),
   o que é a mitigação de viés de gerador mencionada nas Ameaças à Validade
   (Seção 11) do protocolo — mas a curadoria humana continua necessária.

## ⚠️ Ressalva importante antes de usar como gabarito

Os campos `trecho_fonte` foram copiados das fichas de fatos produzidas pelos
agentes de extração — a maioria é uma citação literal do MCR, mas algumas
são paráfrases próximas do texto original (quando o agente resumiu em vez de
citar). **Antes de promover qualquer candidata ao conjunto-padrão final,
revalide o `trecho_fonte` contra `data/MCR.md` (ou o chunk original em
`reports/chunks_dump.txt`)** — é exatamente o passo de "verificação
amostral" da Seção 6.2, item 4. O `resposta_rascunho` é ainda mais
provisório: serve como ponto de partida para a curadoria e para a sessão com
o Sicredi, não como gabarito.

## Próximos passos (fora desta etapa)

Conforme combinado, a filtragem determinística (dedup por similaridade
semântica ≥ 0,80, descarte de perguntas que citam número de seção
literalmente) e a curadoria final até 60–100 perguntas (Seção 6.2, passos 2–3)
ficam por conta do autor do TCC, usando o `candidatas.csv` como planilha de
trabalho.

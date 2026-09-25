# Avaliação automática do Agente Q&A

Implementa as Camadas 1 e 2 do protocolo de avaliação (recuperação e geração)
sobre o conjunto-padrão curado. A Camada 3 — sessão com os analistas do
Sicredi — continua sendo humana e não é coberta aqui.

## Por que a curadoria é pré-requisito

As 180 candidatas em `eval/dataset/candidatas.jsonl` foram geradas por LLM a
partir dos chunks indexados, e a referência que elas trazem aponta o capítulo
**do assunto** da pergunta — não necessariamente a seção onde a resposta está.
Um limite do Pronaf pode estar numa seção de limites, separada da seção
principal do programa. Usar essas referências como gabarito mediria o
retriever contra um alvo errado.

Por isso a fonte da avaliação é a planilha curada
(`data/Questions_to_eval/candidatas_curadas.csv`), onde cada linha revisada
recebe a marca `Questão Verificada` na primeira coluna e tem
`referencias_mcr` e `resposta_rascunho` conferidos contra o manual. Só as
linhas marcadas entram.

## Fluxo

```
   planilha curada
        │  eval/dataset.py  (filtra verificadas, parseia "MCR 10-2; MCR 8-1")
        ▼
   eval/runner.py  ──▶  eval/runs/<rodada>.jsonl
        │                    (pergunta, resposta, recuperados, trechos, latência)
        ├──▶ eval/metrics_retrieval.py   precisão / cobertura / F1     (sem LLM)
        ├──▶ eval/metrics_abstencao.py   taxa de abstenção             (flash)
        └──▶ eval/enriquecer.py ──▶ <rodada>.enriquecido.jsonl
                 ├──▶ eval/metrics_ragas.py   fidelidade / relevância  (flash + voyage)
                 ├──▶ eval/export_detalhe.py  uma linha por pergunta (CSV + JSON)
                 └──▶ eval/relatorio.py       página de resultados
```

## O que não é medido aqui

**Se a resposta está correta.** Julgar conteúdo do MCR é trabalho de quem
entende de crédito rural, e um rótulo automático nesse campo daria uma
confiança que ele não tem. O que a avaliação entrega é o material para esse
julgamento: `export_detalhe` põe resposta, referência curada e seções
recuperadas lado a lado, em CSV para revisar na planilha e na página de
resultados. É essa revisão que a sessão com os analistas do Sicredi realiza.

## O passo de enriquecimento, e por que ele existe

`eval/metrics_ragas.py` roda sobre o arquivo **enriquecido**, nunca sobre o
bruto. `eval/enriquecer.py` faz duas correções no que o juiz enxerga — sem
mexer no que o sistema respondeu:

- **Texto integral dos trechos.** `rag/snapshot.py` trunca em 1500 caracteres,
  porque foi escrito para persistir o histórico no Postgres. Os chunks do MCR
  têm em média 12,6 mil caracteres e chegam a 84 mil. O gerador recebe a seção
  inteira; pontuar fidelidade contra o texto cortado conta como alucinação
  tudo o que foi tirado do resto da seção. O texto volta do Qdrant pelo id do
  ponto, então não é preciso gerar as respostas de novo. (O `runner` já grava
  o texto integral desde a rodada 02; o enriquecimento conserta rodadas
  antigas e continua sendo quem remove o convite.)
- **Resposta sem o call-to-action.** O convite de handoff ("me conte sua renda,
  o que produz e a região") não afirma nada sobre o MCR e não tem trecho que o
  sustente. Medido junto, cobra da fidelidade um comportamento intencional do
  produto. O original fica em `resposta_original`.

Coleta e pontuação são etapas separadas porque a coleta é a cara (uma chamada
ao `gemini-2.5-pro` por pergunta, mais Voyage e Qdrant) e a pontuação é
barata. Gravado o JSONL, dá para recalcular métricas quantas vezes for
preciso, e comparar rodadas sem o risco de misturar números de execuções
diferentes do sistema.

## Como rodar

Um comando, da raiz do projeto:

```
avaliar
```

Executa a rodada inteira, pontua, gera a página e abre no navegador. Leva
cerca de uma hora — a geração das respostas é a parte lenta. A rodada é
numerada sozinha (`rodada03`, `rodada04`, …), então nenhuma medição anterior
é sobrescrita.

```
avaliar --limite 5           amostra rápida, para checar que está tudo de pé
avaliar --categoria elegibilidade
avaliar --pular-ragas        sem a pontuação de geração (a etapa lenta)
avaliar --retomar --saida eval/runs/rodada03.jsonl   continua uma rodada interrompida
avaliar --relatorio-de eval/runs/rodada03.jsonl      só refaz a página
avaliar --nao-abrir
```

O `avaliar.cmd` é um atalho para `venv/Scripts/python -m eval.avaliar`; em
bash ou noutro ambiente, chame o módulo direto.

Se uma pergunta falhar por cota do Vertex ou instabilidade, o comando refaz
sozinho as que falharam antes de seguir para a pontuação.

### Antes da primeira vez

- `.env` preenchido com `GOOGLE_CLOUD_PROJECT`, `GCLOUD_SA_BASE64`,
  `VOYAGE_API_KEY`, `QDRANT_URL` e `QDRANT_API_KEY`. O Qdrant pode ser o da
  nuvem (é o que o `.env` aponta) ou o local via `docker compose up -d`.
- `venv-eval`, o ambiente separado do RAGAS, criado uma vez só:

```bash
python -m venv venv-eval
venv-eval/Scripts/python -m pip install ragas "langchain-core<1" "langchain-community<0.4" \
    "langchain<1" "langchain-google-vertexai<3" "langchain-voyageai<0.2" \
    "langchain-openai<1" "langgraph<1" python-dotenv
```

As versões estão presas na linha 0.3 do LangChain de propósito: o RAGAS 0.4.3
importa um módulo que o LangChain 1.x removeu, e sem os pinos a instalação
quebra no `import ragas`.

## As etapas por dentro

O `avaliar` só encadeia os módulos abaixo, que continuam valendo sozinhos — é
o que se usa para repontuar uma rodada antiga ou comparar configurações sem
gerar respostas de novo. Todos rodam da raiz do projeto, com
`venv/Scripts/python` (o ambiente do app), e `<NN>` é o número da rodada.

### 1. Executar uma rodada

```bash
venv/Scripts/python -m eval.runner --saida eval/runs/rodada<NN>.jsonl
```

Roda o Agente Q&A nas 77 perguntas verificadas da planilha curada e grava uma
linha por pergunta. Leva de 40 a 60 minutos (uma chamada ao `gemini-2.5-pro`
por pergunta) e custa uma execução de Vertex, Voyage e Qdrant — é a etapa cara.

Enquanto desenvolve, use uma amostra:

```bash
venv/Scripts/python -m eval.runner --limite 5 --saida eval/runs/teste.jsonl
venv/Scripts/python -m eval.runner --categoria elegibilidade --saida eval/runs/teste.jsonl
```

Se a rodada for interrompida, ou se alguma pergunta falhar por cota do Vertex,
não recomece do zero:

```bash
# descarta as linhas com erro e refaz só elas
venv/Scripts/python -c "import json; p='eval/runs/rodada<NN>.jsonl'; \
  ls=[l for l in open(p,encoding='utf-8') if l.strip() and not json.loads(l).get('erro')]; \
  open(p,'w',encoding='utf-8',newline='\n').writelines(ls)"
venv/Scripts/python -m eval.runner --retomar --saida eval/runs/rodada<NN>.jsonl
```

`--retomar` pula os ids já presentes no arquivo. O runner grava em modo append
com `flush` a cada pergunta, então nada do que já respondeu se perde.

### 2. Gerar o relatório dessa rodada

Quatro comandos, nesta ordem. O primeiro prepara o arquivo que todos os
outros consomem:

```bash
venv/Scripts/python -m eval.enriquecer      eval/runs/rodada<NN>.jsonl
venv/Scripts/python -m eval.metrics_abstencao eval/runs/rodada<NN>.enriquecido.jsonl
venv-eval/Scripts/python -m eval.metrics_ragas eval/runs/rodada<NN>.enriquecido.jsonl
venv/Scripts/python -m eval.export_detalhe   eval/runs/rodada<NN>.enriquecido.jsonl

venv/Scripts/python -m eval.relatorio eval/runs/rodada<NN>.enriquecido.jsonl \
    --saida eval/runs/rodada<NN>.html
```

O que cada um deixa ao lado do JSONL:

| comando | escreve | leva |
|---|---|---|
| `enriquecer` | `.enriquecido.jsonl` — texto integral dos trechos, resposta sem o convite | segundos |
| `metrics_abstencao` | `.abstencao.json` — recusa × resposta nas 10 iscas | ~1 min |
| `metrics_ragas` | `.ragas.csv` — as 4 notas por pergunta | 10 a 20 min |
| `export_detalhe` | `.detalhe.csv` e `.detalhe.json` — uma linha por pergunta | segundos |
| `relatorio` | a página HTML, montada a partir de tudo acima | segundos |

`relatorio` funciona mesmo sem alguns deles: seções cujos dados não existem
são omitidas, em vez de aparecerem vazias. Rodar só `enriquecer` +
`export_detalhe` + `relatorio` já dá uma página com recuperação e o detalhe
pergunta a pergunta, sem as notas do RAGAS.

Para publicar a página como artifact, peça ao Claude Code — o HTML gerado é
um arquivo comum, e republicar no mesmo endereço mantém o link.

### Só os números, sem página

```bash
venv/Scripts/python -m eval.metrics_retrieval eval/runs/rodada<NN>.enriquecido.jsonl
venv/Scripts/python -m eval.metrics_retrieval eval/runs/rodada<NN>.enriquecido.jsonl --estagio trechos
venv/Scripts/python -m eval.metrics_retrieval eval/runs/rodada<NN>.enriquecido.jsonl --json
```

Sem `--estagio`, imprime as duas tabelas (busca crua e contexto pós-juiz).

### Comparar configurações do juiz sem refazer a rodada

```bash
venv/Scripts/python -m eval.judge_sweep eval/runs/rodada<NN>.enriquecido.jsonl \
    --variantes flash:1200 flash:20000 pro:20000 flash:inf
```

Reexecuta **só o julgamento** sobre os candidatos já salvos: todas as
variantes veem exatamente o mesmo conjunto de trechos, e cada uma custa uma
chamada por pergunta em vez de uma rodada inteira. `--apenas-afetadas` roda só
nas perguntas cuja cobertura pós-juiz ficou abaixo de 1,00 — mais barato para
iterar, mas cego para regressão, então confirme no conjunto inteiro antes de
concluir.

## Definição das métricas de recuperação

```
precisão  = trechos recuperados relevantes / trechos recuperados
cobertura = seções do gabarito recuperadas / seções do gabarito
```

Três decisões que mudam a leitura dos números:

1. **Sem `@k` fixo.** O `buscar_com_fallback` devolve de 1 a 5 trechos
   conforme o filtro de seção e o fallback. Dividir por um k fixo puniria uma
   busca que devolveu 2 trechos, os dois certos. O denominador é o que a busca
   de fato devolveu, e o número médio de trechos é reportado junto — é ele que
   dá contexto para ler a precisão.
2. **Dois estágios, medidos separadamente.** `recuperados` é a saída crua da
   busca; `trechos` é o que sobrou depois do `rag/judge.py` e é o que alimenta
   a geração. Sem essa separação, um trecho que a busca achou e o juiz
   descartou apareceria como falha do retriever.
3. **Relevância no nível da seção.** Um trecho conta como relevante quando o
   par (capítulo, seção) do payload está nas `referencias_mcr`. A comparação é
   exata porque, no índice atual, um chunk é uma seção inteira do manual —
   101 chunks para 99 pares capítulo-seção distintos.

As perguntas da categoria `abstencao` ficam fora dessas contas: não têm seção
de origem, porque a resposta certa é recusar. Elas são medidas por
`metrics_abstencao.py`.

## Limitações a declarar

- **Corpus pequeno.** Recuperar entre ~100 seções é bem mais fácil do que
  entre 100 mil chunks. Os números não se transferem para um corpus maior.
- **Juiz e gerador do mesmo fornecedor.** A resposta é gerada pelo
  `gemini-2.5-pro` e avaliada pelo `gemini-2.5-flash`; o viés de
  autopreferência documentado por Zheng et al. (MT-Bench) não é eliminado, só
  reduzido. É motivo para a calibração humana da Camada 3.
- **Gabarito de um autor só.** As referências foram conferidas pelo autor, não
  por especialista de crédito rural. É exatamente o que a sessão com o Sicredi
  deve calibrar, numa subamostra.
- **`resposta_rascunho` como referência.** Serve ao `context_recall` do RAGAS,
  mas foi escrita a partir dos próprios chunks indexados — não é uma resposta
  independente escrita por especialista.

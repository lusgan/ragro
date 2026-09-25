"""Renderização da página de resultados — o HTML, separado da leitura dos dados.

`eval/relatorio.py` reúne os números da rodada; aqui eles viram página. A
divisão existe porque as duas partes mudam por motivos diferentes: métrica
nova mexe no primeiro, ajuste de layout ou de redação mexe só neste.
"""

from __future__ import annotations

from collections import Counter

from eval.dataset import CATEGORIA_ABSTENCAO
from eval.relatorio import (
    BASELINE_TCC1,
    CAT_CURTA,
    CATEGORIA_DESCRICAO,
    Dados,
    e,
    milhar,
    n2,
)

ESTILO = """
  :root{
    color-scheme: light;
    --paper:#e9edee; --surface:#f8fafa; --surface-2:#dfe5e6;
    --ink:#11171a; --ink-soft:#3c474c; --muted:#69757b;
    --line:#cdd6d8; --line-strong:#aab6b9;
    --accent:#0f5c4a; --accent-ink:#0b4438; --accent-soft:#d5e7e0;
    --warn:#8a5a12; --warn-soft:#f2e6cd; --bad:#8c352b; --bad-soft:#f3ded9;
    --serif:'Spectral', Georgia, serif;
    --sans:'Source Sans 3', -apple-system, 'Segoe UI', sans-serif;
    --mono:'JetBrains Mono', ui-monospace, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme: dark;
      --paper:#0e1315; --surface:#151c1f; --surface-2:#1e272a;
      --ink:#e6ecec; --ink-soft:#bcc7c9; --muted:#8a989c;
      --line:#273236; --line-strong:#3a484c;
      --accent:#6fbfa4; --accent-ink:#9ad7c0; --accent-soft:#17312a;
      --warn:#d3a44a; --warn-soft:#332811; --bad:#e0897a; --bad-soft:#36211d;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --paper:#0e1315; --surface:#151c1f; --surface-2:#1e272a;
    --ink:#e6ecec; --ink-soft:#bcc7c9; --muted:#8a989c;
    --line:#273236; --line-strong:#3a484c;
    --accent:#6fbfa4; --accent-ink:#9ad7c0; --accent-soft:#17312a;
    --warn:#d3a44a; --warn-soft:#332811; --bad:#e0897a; --bad-soft:#36211d;
  }

  *{box-sizing:border-box}
  body{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans);
    font-size:16.5px; line-height:1.62; -webkit-font-smoothing:antialiased; }
  .wrap{ max-width:1100px; margin:0 auto; padding-inline:20px; padding-block:0 84px; }
  h1,h2,h3{ font-family:var(--serif); font-weight:600; margin:0; text-wrap:balance; }
  p{ margin:0 0 14px; color:var(--ink-soft); max-width:70ch; }
  strong{ color:var(--ink); font-weight:600; }
  code,.mono{ font-family:var(--mono); font-size:.88em; }
  a{ color:var(--accent-ink); }

  header.top{ padding-block:52px 30px; border-bottom:2px solid var(--line-strong); }
  .kicker{ font-family:var(--mono); font-size:12px; letter-spacing:.1em; text-transform:uppercase;
    color:var(--accent-ink); margin-bottom:14px; }
  h1{ font-size:clamp(30px,4.4vw,44px); line-height:1.1; max-width:20ch; }
  .standfirst{ font-size:18px; color:var(--ink-soft); max-width:62ch; margin-top:16px; }

  .ficha{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
    background:var(--line); border:1px solid var(--line); margin-top:28px; }
  .ficha div{ background:var(--surface); padding:12px 14px; }
  .ficha dt{ font-family:var(--mono); font-size:10.5px; letter-spacing:.07em; text-transform:uppercase; color:var(--muted); }
  .ficha dd{ margin:5px 0 0; font-size:15.5px; font-weight:600; font-variant-numeric:tabular-nums; }

  section{ padding-top:46px; }
  section + section{ margin-top:36px; border-top:1px solid var(--line); }
  h2{ font-size:25px; margin-bottom:8px; }
  h2 .num{ font-family:var(--mono); font-size:13px; color:var(--muted); margin-right:10px; font-weight:400; }
  .dek{ color:var(--muted); font-size:14.5px; margin:0 0 24px; max-width:64ch; }
  h3{ font-size:17.5px; margin:28px 0 10px; }

  .table-wrap{ overflow-x:auto; border:1px solid var(--line); background:var(--surface); margin:16px 0 22px; }
  table{ border-collapse:collapse; width:100%; min-width:540px; font-size:14.5px; }
  caption{ text-align:left; font-family:var(--mono); font-size:11.5px; color:var(--muted);
    padding:10px 14px; border-bottom:1px solid var(--line); }
  th,td{ padding:8px 14px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }
  thead th{ font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
    color:var(--muted); font-weight:500; background:var(--surface-2); }
  tbody tr:last-child td{ border-bottom:none; }
  tr.total td{ font-weight:700; background:var(--surface-2); }
  td.num,th.num{ font-family:var(--mono); font-variant-numeric:tabular-nums; text-align:right; }
  td.wrap,th.wrap{ white-space:normal; min-width:200px; }
  .up{ color:var(--accent-ink); font-weight:600; }
  .down{ color:var(--bad); font-weight:600; }

  .metric{ border:1px solid var(--line); background:var(--surface); padding:20px 22px; margin:16px 0; }
  .metric h3{ margin:0 0 4px; font-size:18px; }
  .metric .slug{ font-family:var(--mono); font-size:11.5px; color:var(--muted); letter-spacing:.04em; }
  .formula{ font-family:var(--mono); font-size:13.5px; background:var(--surface-2);
    border-left:3px solid var(--accent); padding:11px 14px; margin:14px 0; overflow-x:auto;
    white-space:pre; color:var(--ink); }
  .metric dl{ display:grid; grid-template-columns:auto 1fr; gap:6px 14px; margin:12px 0 0; font-size:14.5px; }
  .metric dt{ font-family:var(--mono); font-size:11px; letter-spacing:.06em; text-transform:uppercase;
    color:var(--muted); padding-top:4px; }
  .metric dd{ margin:0; color:var(--ink-soft); }
  .score{ float:right; font-family:var(--mono); font-size:26px; font-weight:600;
    color:var(--accent-ink); font-variant-numeric:tabular-nums; }

  .nota{ border:1px solid var(--line-strong); border-left:3px solid var(--accent);
    background:var(--surface); padding:16px 20px; margin:20px 0; max-width:72ch; }
  .nota.warn{ border-left-color:var(--warn); }
  .nota.bad{ border-left-color:var(--bad); }
  .nota .rot{ font-family:var(--mono); font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
    color:var(--accent-ink); display:block; margin-bottom:7px; }
  .nota.warn .rot{ color:var(--warn); }
  .nota.bad .rot{ color:var(--bad); }
  .nota p:last-child{ margin-bottom:0; }

  ul{ padding-left:1.25em; color:var(--ink-soft); max-width:68ch; }
  li{ margin-bottom:7px; }
  li::marker{ color:var(--muted); }

  .fluxo{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin:20px 0 6px; }
  .etapa{ border:1px solid var(--line); background:var(--surface); padding:14px 16px; }
  .etapa .et-rot{ font-family:var(--mono); font-size:10.5px; letter-spacing:.07em; text-transform:uppercase; color:var(--muted); }
  .etapa .et-nome{ font-family:var(--serif); font-size:17px; font-weight:600; margin:4px 0 8px; }
  .etapa .et-val{ font-family:var(--mono); font-size:13px; color:var(--ink-soft); font-variant-numeric:tabular-nums; }
  .etapa .et-val b{ color:var(--ink); }

  .legenda{ font-size:13.5px; color:var(--muted); margin:6px 0 18px; }
  .legenda p{ margin:0 0 6px; color:var(--muted); max-width:78ch; }
  .filtros{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 18px; }
  .filtro{ font-family:var(--mono); font-size:12px; padding:6px 11px; border:1px solid var(--line-strong);
    background:var(--surface); color:var(--ink-soft); cursor:pointer; border-radius:2px; }
  .filtro:hover{ background:var(--surface-2); }
  .filtro.ativo{ background:var(--accent); border-color:var(--accent); color:#fff; }
  :root[data-theme="dark"] .filtro.ativo, :root:not([data-theme="light"]) .filtro.ativo{ color:#0e1315; }
  .lista{ display:flex; flex-direction:column; gap:6px; }
  details.q{ border:1px solid var(--line); background:var(--surface); }
  details.q[open]{ border-color:var(--line-strong); }
  details.q summary{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:10px 14px;
    cursor:pointer; list-style:none; }
  details.q summary::-webkit-details-marker{ display:none }
  details.q summary:hover{ background:var(--surface-2); }
  .qid{ font-family:var(--mono); font-size:11.5px; color:var(--muted); }
  .cat{ font-family:var(--mono); font-size:11px; color:var(--muted); }
  .mini{ font-family:var(--mono); font-size:11px; color:var(--muted); font-variant-numeric:tabular-nums; }
  .qtxt{ flex:1 1 320px; font-size:14.5px; color:var(--ink); }
  .pill{ font-family:var(--mono); font-size:10.5px; letter-spacing:.04em; padding:2px 7px;
    border-radius:99px; white-space:nowrap; }
  .pill.ok{ background:var(--accent-soft); color:var(--accent-ink); }
  .pill.meio{ background:var(--warn-soft); color:var(--warn); }
  .pill.ruim{ background:var(--bad-soft); color:var(--bad); }
  .pill.neutro{ background:var(--surface-2); color:var(--muted); }
  details.q dl{ display:grid; grid-template-columns:auto 1fr; gap:9px 16px; margin:0;
    padding:4px 16px 16px; border-top:1px solid var(--line); }
  @media (max-width:560px){ details.q dl{ grid-template-columns:1fr; gap:4px 0; } }
  details.q dt{ font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
    color:var(--muted); padding-top:4px; white-space:nowrap; }
  details.q dd{ margin:0; font-size:14.5px; color:var(--ink-soft); min-width:0; }
  dd.secs{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
  .sec{ font-family:var(--mono); font-size:11.5px; padding:3px 8px; background:var(--surface-2);
    color:var(--ink-soft); border:1px solid var(--line); }
  .sec.ok{ background:var(--accent-soft); color:var(--accent-ink); border-color:var(--accent); font-weight:600; }
  .sec.cortado{ opacity:.55; text-decoration:line-through; }
  .rot-sec{ font-size:12.5px; color:var(--muted); margin-left:2px; }
  .vazio{ font-size:13.5px; color:var(--muted); font-style:italic; }
  dd.resp{ white-space:pre-wrap; background:var(--surface-2); padding:11px 13px; font-size:14px;
    line-height:1.55; max-height:280px; overflow-y:auto; }
  dd.ref{ font-size:14px; color:var(--ink); }
  dd.ragas{ font-family:var(--mono); font-size:12px; font-variant-numeric:tabular-nums; }
  dd.ragas b{ color:var(--ink); }

  footer{ margin-top:48px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; }
"""

SCRIPT = """
<script>
  (function(){
    var botoes = document.querySelectorAll('.filtro');
    var itens = document.querySelectorAll('details.q');
    botoes.forEach(function(b){
      b.addEventListener('click', function(){
        botoes.forEach(function(o){ o.classList.remove('ativo'); });
        b.classList.add('ativo');
        var f = b.dataset.filtro;
        itens.forEach(function(it){
          it.hidden = !(f === 'todas' || it.dataset.cat === f);
          if (it.hidden) it.open = false;
        });
      });
    });
  })();
</script>
"""


def _tabela_estagio(d: Dados, estagio: str, legenda: str) -> str:
    linhas = []
    for categoria, s in d.por_categoria[estagio].items():
        linhas.append(
            f'<tr><td>{e(categoria)}</td><td class="num">{s["n"]}</td>'
            f'<td class="num">{n2(s["precisao"])}</td><td class="num">{n2(s["cobertura"])}</td>'
            f'<td class="num">{n2(s["f1"])}</td><td class="num">{s["acerto"]:.0%}</td>'
            f'<td class="num">{s["trechos_por_pergunta"]:.1f}</td></tr>'
        )
    t = d.medias[estagio]
    linhas.append(
        f'<tr class="total"><td>Total</td><td class="num">{t["n"]}</td>'
        f'<td class="num">{n2(t["precisao"])}</td><td class="num">{n2(t["cobertura"])}</td>'
        f'<td class="num">{n2(t["f1"])}</td><td class="num">{t["acerto"]:.0%}</td>'
        f'<td class="num">{t["trechos_por_pergunta"]:.1f}</td></tr>'
    )
    return f'''<div class="table-wrap">
      <table>
        <caption>{legenda}</caption>
        <thead><tr><th>Categoria</th><th class="num">n</th><th class="num">Precisão</th>
        <th class="num">Cobertura</th><th class="num">F1</th><th class="num">Acerto</th>
        <th class="num">Trechos</th></tr></thead>
        <tbody>{"".join(linhas)}</tbody>
      </table>
    </div>'''


def _secao_o_que(d: Dados) -> str:
    contagem = d.contagem_categorias()
    linhas = "".join(
        f'<tr><td>{e(c)}</td><td class="num">{n}</td>'
        f'<td class="wrap">{e(CATEGORIA_DESCRICAO.get(c, ""))}</td></tr>'
        for c, n in sorted(contagem.items())
    )
    total = sum(contagem.values())
    n_mens, n_iscas = len(d.mensuraveis), len(d.iscas)
    tam = d.tamanho_trechos()
    return f'''  <section id="o-que">
    <h2><span class="num">01</span>O que foi avaliado</h2>
    <p class="dek">Só o Agente Q&amp;A, e só as perguntas cuja referência ao manual foi conferida à mão.</p>

    <p>O conjunto começou com 180 candidatas geradas por LLM a partir dos chunks indexados. A curadoria não foi formalidade: as candidatas apontavam o capítulo <em>do assunto</em> da pergunta, e a resposta muitas vezes mora em outra seção — um limite do Pronaf pode estar numa seção de limites, longe da seção principal do programa. Medir contra a referência original seria medir o retriever contra um alvo errado.</p>

    <p>Entraram na rodada as <strong>{total} linhas marcadas como “Questão Verificada”</strong>. Dessas, <strong>{n_mens} têm seção de origem no MCR</strong> e entram nas métricas de recuperação; as outras <strong>{n_iscas} são perguntas-isca</strong>, escritas para não ter resposta no manual, e são medidas à parte.</p>

    <div class="table-wrap">
      <table>
        <caption>Distribuição por categoria</caption>
        <thead><tr><th>Categoria</th><th class="num">n</th><th class="wrap">O que a categoria testa</th></tr></thead>
        <tbody>{linhas}
          <tr class="total"><td>Total</td><td class="num">{total}</td><td class="wrap">{n_mens} medíveis por recuperação + {n_iscas} iscas</td></tr>
        </tbody>
      </table>
    </div>

    <div class="nota">
      <span class="rot">Por que o corpus importa para ler tudo o que vem depois</span>
      <p>A coleção indexada tem <strong>101 chunks para 99 pares capítulo-seção distintos</strong>: cada chunk é praticamente uma seção inteira do manual, com <strong>{milhar(tam["media"])} caracteres em média</strong> e até {milhar(tam["max"])}. Isso traz uma vantagem e uma ressalva. A vantagem é que o gabarito fica exato — um trecho recuperado conta como certo quando a seção dele está entre as referências curadas, sem julgamento subjetivo. A ressalva é que achar 5 entre ~100 seções é bem mais fácil do que achar 5 entre 100 mil chunks: estes números não se transferem para um corpus maior.</p>
    </div>
  </section>

'''


def _secao_pipeline(d: Dados) -> str:
    bruto, pos = d.medias["recuperados"], d.medias["trechos"]
    um_trecho = sum(1 for r in d.registros if len(r.get("trechos") or []) == 1)
    lat = d.latencias()
    return f'''  <section id="pipeline">
    <h2><span class="num">02</span>Onde cada número é medido</h2>
    <p class="dek">O Q&amp;A tem três estágios, e medir só o final esconde qual deles falhou.</p>

    <div class="fluxo">
      <div class="etapa">
        <div class="et-rot">Estágio 1</div>
        <div class="et-nome">Busca híbrida</div>
        <div class="et-val">devolve <b>{bruto["trechos_por_pergunta"]:.1f}</b> trechos em média</div>
      </div>
      <div class="etapa">
        <div class="et-rot">Estágio 2</div>
        <div class="et-nome">Juiz</div>
        <div class="et-val">reduz para <b>{pos["trechos_por_pergunta"]:.1f}</b> trechos<br>{um_trecho} perguntas ficam com 1 só</div>
      </div>
      <div class="etapa">
        <div class="et-rot">Estágio 3</div>
        <div class="et-nome">Redação</div>
        <div class="et-val">responde a partir<br>do contexto filtrado</div>
      </div>
    </div>

    <p>As métricas de recuperação são calculadas <strong>duas vezes</strong>: uma na saída crua da busca e outra no contexto que sobra depois do juiz — que é o que de fato alimenta a redação. Sem essa separação, um trecho que a busca achou e o juiz descartou apareceria como falha da busca, e o efeito do juiz ficaria invisível.</p>

    <p>Um detalhe que aparece nos números: a busca às vezes devolve <strong>mais de 5 trechos</strong>. O <code>buscar_com_fallback</code> une o resultado filtrado por seção com o resultado sem filtro, então o topo-5 de cada um pode somar mais. A resposta completa leva <strong>{lat["mediana"]:.0f} segundos na mediana</strong>, com média de {lat["media"]:.0f} e pico de {lat["max"]:.0f}.</p>
  </section>

'''


METRICAS = '''  <section id="metricas">
    <h2><span class="num">03</span>As métricas, uma a uma</h2>
    <p class="dek">Fórmula, o que representa, e o que cada uma deliberadamente não mede.</p>

    <div class="metric">
      <h3>Precisão</h3>
      <div class="slug">recuperação · sem LLM</div>
      <div class="formula">precisão = trechos relevantes recuperados / trechos recuperados</div>
      <dl>
        <dt>Representa</dt><dd>Quanto do que foi entregue ao gerador serve. Precisão baixa significa contexto poluído: o modelo precisa achar a agulha no meio do palheiro que ele mesmo recebeu.</dd>
        <dt>Aqui</dt><dd>Um trecho é relevante quando o par (capítulo, seção) do payload está nas <code>referencias_mcr</code> curadas.</dd>
        <dt>Sem “@k”</dt><dd>O denominador é o que a busca devolveu de fato, não um k fixo. Dividir por 5 puniria uma busca que devolveu 2 trechos, os dois certos. Por isso a coluna “trechos” anda junto: é ela que dá escala para ler a precisão.</dd>
        <dt>Não mede</dt><dd>Nada sobre a resposta escrita. Contexto perfeito e resposta errada dão precisão 1,00.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>Cobertura <span class="slug">(recall)</span></h3>
      <div class="slug">recuperação · sem LLM</div>
      <div class="formula">cobertura = seções do gabarito recuperadas / seções do gabarito</div>
      <dl>
        <dt>Representa</dt><dd>Se a informação necessária chegou. É o teto de tudo o que vem depois: o que a busca não trouxe, o gerador não tem como responder — só inventando.</dd>
        <dt>Aqui</dt><dd>O denominador é o número de seções citadas na curadoria. Vale 1 na maioria das perguntas e 2 nas de comparação entre programas.</dd>
        <dt>Não mede</dt><dd>Quanto lixo veio junto. Devolver todas as 99 seções daria cobertura 1,00.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>F1</h3>
      <div class="slug">recuperação · sem LLM</div>
      <div class="formula">F1 = 2 × (precisão × cobertura) / (precisão + cobertura)</div>
      <dl>
        <dt>Representa</dt><dd>Um número só para comparar configurações, penalizando quem é bom em uma métrica às custas da outra. É a média harmônica: puxa para baixo quando as duas são desiguais.</dd>
        <dt>Aqui</dt><dd>Calculado por pergunta e depois promediado, e não a partir das médias — cada pergunta pesa igual, como na tabela da TCC-1.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>Taxa de acerto</h3>
      <div class="slug">recuperação · sem LLM</div>
      <div class="formula">acerto = perguntas com ao menos 1 seção do gabarito / perguntas</div>
      <dl>
        <dt>Representa</dt><dd>A leitura binária e mais próxima da experiência real: o sistema tinha em mãos a seção certa, sim ou não.</dd>
        <dt>Por que não é igual à cobertura</dt><dd>Numa pergunta com duas seções no gabarito, trazer uma só dá cobertura 0,50 e acerto 1.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>Taxa de abstenção</h3>
      <div class="slug">geração · juiz flash</div>
      <div class="formula">abstenção = iscas recusadas corretamente / iscas</div>
      <dl>
        <dt>Representa</dt><dd>Alucinação por comissão: com uma pergunta fora do manual, o sistema reconhece que não sabe ou inventa uma regra plausível?</dd>
        <dt>Aqui</dt><dd>Um classificador <code>flash</code> lê cada resposta e decide entre recusa e resposta substantiva. Busca por palavras não serviria: erraria a recusa educada (“o MCR não trata desse tema”) e o falso positivo (“não há limite máximo para…”, que é uma afirmação).</dd>
      </dl>
    </div>

    <h3>As quatro do RAGAS</h3>
    <p>O RAGAS usa um LLM como juiz: ele quebra a resposta em afirmações isoladas e verifica cada uma contra os trechos. Todas as notas vão de 0 a 1. O juiz é o <code>gemini-2.5-flash</code> e os embeddings são <code>voyage-4-lite</code>, o mesmo modelo denso que o retriever usa. Duas escolhas de medição valem registro: os trechos entram <strong>inteiros</strong>, e não truncados, senão uma afirmação tirada do fim da seção contaria como sem respaldo; e a resposta é pontuada <strong>sem o convite de handoff</strong> do fim, que não afirma nada sobre o MCR e não tem trecho que o sustente.</p>

    <div class="metric">
      <h3>Faithfulness <span class="slug">(fidelidade)</span></h3>
      <div class="slug">geração · RAGAS</div>
      <div class="formula">fidelidade = afirmações sustentadas pelos trechos / afirmações da resposta</div>
      <dl>
        <dt>Representa</dt><dd>A única métrica desta lista que mede alucinação na <strong>resposta</strong>. As de recuperação só olham para os trechos.</dd>
        <dt>Precisa de</dt><dd>Pergunta, resposta e trechos. Não precisa de gabarito.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>Answer relevancy <span class="slug">(relevância)</span></h3>
      <div class="slug">geração · RAGAS</div>
      <div class="formula">similaridade média entre a pergunta original e
perguntas que o juiz gera a partir da resposta</div>
      <dl>
        <dt>Representa</dt><dd>Se a resposta endereça o que foi perguntado, em vez de derivar para um tema vizinho. O mecanismo é indireto de propósito: se dá para reconstruir a pergunta a partir da resposta, a resposta estava no alvo.</dd>
        <dt>Não mede</dt><dd>Correção. Uma resposta errada, mas no tema, pontua alto. E zera de vez quando o juiz classifica a resposta como evasiva.</dd>
      </dl>
    </div>

    <div class="metric">
      <h3>Context precision / context recall</h3>
      <div class="slug">geração · RAGAS</div>
      <div class="formula">versão julgada por LLM da precisão e da cobertura,
comparando trechos contra a resposta de referência</div>
      <dl>
        <dt>Representa</dt><dd>O mesmo que as duas primeiras métricas desta página, só que decidido por leitura do texto em vez de por comparação de capítulo e seção.</dd>
        <dt>Para que servem aqui</dt><dd>Triangulação. Como o gabarito por seção é mais defensável, estas entram para conferir: convergência entre as duas leituras sustenta as duas; divergência grande é sinal de gabarito ou de juiz com problema.</dd>
      </dl>
    </div>
  </section>

'''


def avaliar_seguro(registro: dict, estagio: str):
    """`avaliar_registro` sem o cuidado repetido de pular registros com erro."""
    from eval.metrics_retrieval import avaliar_registro

    if registro.get("erro"):
        return None
    return avaliar_registro(registro, estagio=estagio)


def _lista_perdidas(d: Dados) -> str:
    perdidas = d.perdidas_pelo_juiz()
    if not perdidas:
        return "<p>Nenhuma pergunta perdeu, no filtro do juiz, a seção que a busca tinha trazido.</p>"
    linhas = []
    for r in perdidas:
        gab = ", ".join(f"MCR {c}-{s}" for c, s in r["referencias"])
        ficou = ", ".join(f"{t['capitulo_num']}-{t['secao_num']}" for t in r["trechos"]) or "nada"
        linhas.append(
            f'<tr><td>{e(r["id"])}</td><td class="wrap">{e(r["pergunta"])}</td>'
            f'<td>{e(gab)}</td><td>{e(ficou)}</td></tr>'
        )
    corpo = "".join(linhas)
    return (
        '<div class="table-wrap"><table>'
        "<caption>Perguntas em que a busca acertou e o juiz descartou</caption>"
        '<thead><tr><th>ID</th><th class="wrap">Pergunta</th><th>Gabarito</th>'
        "<th>Ficou com</th></tr></thead>"
        f"<tbody>{corpo}</tbody></table></div>"
    )


def _lista_falhas_busca(d: Dados) -> str:
    falhas = d.falhas_de_busca()
    if not falhas:
        return "<p>A seção certa apareceu na busca em todas as perguntas.</p>"
    itens = []
    for r in falhas:
        gab = ", ".join(f"MCR {c}-{s}" for c, s in r["referencias"])
        veio = ", ".join(
            f"{t['capitulo_num']}-{t['secao_num']}" for t in (r.get("recuperados") or [])
        )
        itens.append(
            f'<li><strong>{e(r["id"])}</strong> — {e(r["pergunta"])} '
            f'Gabarito {e(gab)}; vieram {e(veio) or "nenhum trecho"}.</li>'
        )
    return f"<ul>{''.join(itens)}</ul>"


def _delta(a: float, b: float) -> str:
    classe = "up" if b > a else "down" if b < a else ""
    sinal = "+" if b >= a else "−"
    return f'<td class="num {classe}">{sinal}{n2(abs(b - a))}</td>'


def _secao_recuperacao(d: Dados) -> str:
    bruto, pos = d.medias["recuperados"], d.medias["trechos"]
    perdidas = len(d.perdidas_pelo_juiz())
    mantidos = sum(
        1
        for reg in d.registros
        if (b := avaliar_seguro(reg, "recuperados")) is not None
        and (p := avaliar_seguro(reg, "trechos")) is not None
        and b.acertou
        and p.acertou
    )
    pp = (pos["acerto"] - bruto["acerto"]) * 100
    return f"""  <section id="resultados">
    <h2><span class="num">04</span>Recuperação: antes e depois do juiz</h2>
    <p class="dek">{bruto["n"]} perguntas. A primeira tabela é a busca crua; a segunda é o contexto que chega ao gerador.</p>

    {_tabela_estagio(d, "recuperados", "Estágio 1 — busca híbrida, antes do juiz")}
    {_tabela_estagio(d, "trechos", "Estágio 2 — contexto final, depois do juiz")}

    <div class="table-wrap">
      <table>
        <caption>O efeito do juiz, isolado</caption>
        <thead><tr><th>Métrica</th><th class="num">Busca crua</th><th class="num">Depois do juiz</th><th class="num">Diferença</th></tr></thead>
        <tbody>
          <tr><td>Precisão</td><td class="num">{n2(bruto["precisao"])}</td><td class="num">{n2(pos["precisao"])}</td>{_delta(bruto["precisao"], pos["precisao"])}</tr>
          <tr><td>Cobertura</td><td class="num">{n2(bruto["cobertura"])}</td><td class="num">{n2(pos["cobertura"])}</td>{_delta(bruto["cobertura"], pos["cobertura"])}</tr>
          <tr><td>F1</td><td class="num">{n2(bruto["f1"])}</td><td class="num">{n2(pos["f1"])}</td>{_delta(bruto["f1"], pos["f1"])}</tr>
          <tr><td>Taxa de acerto</td><td class="num">{bruto["acerto"]:.0%}</td><td class="num">{pos["acerto"]:.0%}</td><td class="num {"up" if pp >= 0 else "down"}">{pp:+.0f} p.p.</td></tr>
          <tr><td>Trechos por pergunta</td><td class="num">{bruto["trechos_por_pergunta"]:.1f}</td><td class="num">{pos["trechos_por_pergunta"]:.1f}</td><td class="num">{pos["trechos_por_pergunta"] - bruto["trechos_por_pergunta"]:+.1f}</td></tr>
        </tbody>
      </table>
    </div>

    <p>É o juiz que transforma uma busca de alta cobertura num contexto limpo: a precisão sai de {n2(bruto["precisao"])} para {n2(pos["precisao"])} enquanto os trechos caem de {bruto["trechos_por_pergunta"]:.1f} para {pos["trechos_por_pergunta"]:.1f} por pergunta. Em {mantidos} perguntas ele preservou o acerto enquanto limpava o contexto; em <strong>{perdidas} de {bruto["n"]}</strong> descartou a seção certa que a busca tinha trazido.</p>

    {_lista_perdidas(d)}

    <h3>As perguntas que a busca nem trouxe</h3>
    <p>Quando a seção certa não aparece em estágio nenhum, não há juiz que salve.</p>
    {_lista_falhas_busca(d)}
  </section>

"""


def _secao_abstencao(d: Dados) -> str:
    # Sem o arquivo de `metrics_abstencao`, a seção sai fora: imprimir 0 de 10
    # seria pior do que não imprimir nada.
    if not d.abstencao.get("contagem"):
        return ""
    contagem = d.abstencao.get("contagem", {})
    total = sum(contagem.values()) or len(d.iscas)
    acertos = contagem.get("abstencao", 0)
    responderam = [
        qid
        for qid, classe in (d.abstencao.get("por_pergunta") or {}).items()
        if classe == "resposta_substantiva"
    ]
    perguntas = {r["id"]: r["pergunta"] for r in d.registros}
    if responderam:
        itens = "".join(
            f'<li><strong>{e(qid)}</strong> — {e(perguntas.get(qid, ""))}</li>' for qid in responderam
        )
        bloco = (
            f"<p>As que receberam resposta substantiva em vez de recusa:</p><ul>{itens}</ul>"
            "<p>Vale lê-las uma a uma antes de contá-las como alucinação: uma negativa correta e "
            "ancorada no manual (“o Pronaf não financia isso”) é a resposta certa, e o classificador "
            "distingue recusa de resposta substantiva, não acerto de erro.</p>"
        )
    else:
        bloco = "<p>Nenhuma isca recebeu resposta substantiva.</p>"

    return f"""  <section id="abstencao">
    <h2><span class="num">05</span>Abstenção nas perguntas-isca</h2>
    <p class="dek">{total} perguntas escritas para não ter resposta no manual.</p>

    <p><span class="score">{acertos}/{total}</span>O sistema recusou corretamente em {acertos} das {total}, reconhecendo que o MCR não trata do tema. É a medida de alucinação por comissão: com uma pergunta fora do manual, inventar uma regra plausível seria o pior resultado possível.</p>

    {bloco}
  </section>

"""


def _secao_ragas(d: Dados) -> str:
    r = d.ragas()
    if not r:
        return ""
    chaves = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    linhas = []
    for categoria, (n, medias) in r["por_categoria"].items():
        celulas = "".join(f'<td class="num">{n2(medias[k])}</td>' for k in chaves)
        linhas.append(f'<tr><td>{e(categoria)}</td><td class="num">{n}</td>{celulas}</tr>')
    n_total, medias_total = r["total"]
    celulas = "".join(f'<td class="num">{n2(medias_total[k])}</td>' for k in chaves)
    linhas.append(f'<tr class="total"><td>Total</td><td class="num">{n_total}</td>{celulas}</tr>')
    pos = d.medias["trechos"]

    return f"""  <section id="ragas">
    <h2><span class="num">06</span>Geração: as notas do RAGAS</h2>
    <p class="dek">As mesmas {n_total} perguntas, julgadas por LLM sobre os trechos integrais.</p>

    <div class="table-wrap">
      <table>
        <caption>RAGAS · juiz gemini-2.5-flash · embeddings voyage-4-lite</caption>
        <thead><tr><th>Categoria</th><th class="num">n</th><th class="num">Fidelidade</th>
        <th class="num">Relevância</th><th class="num">Context prec.</th><th class="num">Context recall</th></tr></thead>
        <tbody>{"".join(linhas)}</tbody>
      </table>
    </div>

    <div class="nota">
      <span class="rot">Duas medições independentes, mesmo resultado</span>
      <p>A precisão e a cobertura de contexto do RAGAS são julgadas por um LLM lendo o texto; as da Seção 04 são contadas comparando capítulo e seção. São métodos sem nada em comum: <strong>{n2(medias_total["context_precision"])} contra {n2(pos["precisao"])}</strong> de precisão e <strong>{n2(medias_total["context_recall"])} contra {n2(pos["cobertura"])}</strong> de cobertura. Convergência entre medições independentes é o argumento mais forte desta página.</p>
    </div>

    <h3>Fidelidade {n2(medias_total["faithfulness"])}</h3>
    <p><strong>{r["fidelidade_alta"]} das {n_total} perguntas ficam em 0,80 ou acima</strong> e {r["fidelidade_baixa"]} ficam abaixo de 0,50. O que puxa a nota para baixo são as <strong>citações de capítulo e seção</strong> (“MCR, Cap. 7, Seção 4, Tabela 1”): o juiz as lê como afirmações e não encontra, no corpo do trecho, a confirmação de que aquele texto é aquela seção — o número está no metadado, não na prosa. É efeito do formato de citação, não invenção do modelo.</p>

    <h3>Relevância {n2(medias_total["answer_relevancy"])}, a métrica mais fácil de ler errado</h3>
    <p>Ela zera de vez quando o juiz classifica a resposta como evasiva, e <strong>{r["zeros_relevancia"]} das {n_total} receberam exatamente 0</strong>. Parte desses zeros é o sistema se comportando bem: quando a seção certa não chega ao contexto, dizer “não tenho essa informação” é o desejado, e a métrica pune. A falha existe, mas é de recuperação, e já foi contada na Seção 04. É a métrica a citar com mais cuidado no texto do TCC.</p>
  </section>

"""


def _chips(secoes: list[dict], sobreviveu: set[str] | None = None) -> str:
    if not secoes:
        return '<span class="vazio">nenhum trecho</span>'
    partes = []
    for s in secoes:
        classe = "sec ok" if s["relevante"] else "sec"
        if sobreviveu is not None and s["ref"] not in sobreviveu:
            classe += " cortado"
        marca = "✓ " if s["relevante"] else ""
        partes.append(
            f'<span class="{classe}" title="{e(s["label"])} · score {s["score"]}">'
            f'{marca}MCR {e(s["ref"])}</span>'
        )
    return "".join(partes)


def _pergunta(linha: dict) -> str:
    isca = linha["categoria"] == CATEGORIA_ABSTENCAO
    sobreviveu = {s["ref"] for s in linha["pos_juiz"]}

    if linha["gabarito"]:
        gab = " ".join(
            f'<span class="sec ok">MCR {e(ref)}</span>'
            + (f'<span class="rot-sec">{e(lab)}</span>' if lab else "")
            for ref, lab in zip(
                linha["gabarito"], linha.get("gabarito_rotulos") or linha["gabarito"]
            )
        )
    else:
        gab = '<span class="vazio">fora do MCR — a resposta certa é recusar</span>'

    metricas = ""
    if not isca and linha["precisao_pos_juiz"] is not None:
        metricas = (
            f'<span class="mini">prec {n2(linha["precisao_pos_juiz"])}</span>'
            f'<span class="mini">cobe {n2(linha["cobertura_pos_juiz"])}</span>'
        )

    def nota(chave):
        v = linha.get(chave)
        return f"<b>{n2(v)}</b>" if isinstance(v, (int, float)) else "<b>—</b>"

    ragas = ""
    if any(
        isinstance(linha.get(k), (int, float))
        for k in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    ):
        ragas = (
            '<dt>RAGAS</dt><dd class="ragas">'
            f'fidelidade {nota("faithfulness")} · relevância {nota("answer_relevancy")} · '
            f'context prec. {nota("context_precision")} · context recall {nota("context_recall")}</dd>'
        )

    ref = (
        f'<dt>Referência</dt><dd class="ref">{e(linha["resposta_referencia"])}</dd>'
        if linha.get("resposta_referencia")
        else ""
    )
    acertou = linha.get("acertou_pos_juiz")
    selo = ""
    if not isca and acertou is not None:
        selo = (
            '<span class="pill ok">seção certa no contexto</span>'
            if acertou
            else '<span class="pill ruim">seção certa fora do contexto</span>'
        )

    return f"""<details class="q" data-cat="{e(linha["categoria"])}">
      <summary>
        <span class="qid">{e(linha["id"])}</span>
        {selo}
        <span class="cat">{e(CAT_CURTA.get(linha["categoria"], linha["categoria"]))}</span>
        {metricas}
        <span class="qtxt">{e(linha["pergunta"])}</span>
      </summary>
      <dl>
        <dt>Deveria recuperar</dt><dd>{gab}</dd>
        <dt>A busca trouxe</dt><dd class="secs">{_chips(linha["recuperados"], sobreviveu)}</dd>
        <dt>Depois do juiz</dt><dd class="secs">{_chips(linha["pos_juiz"])}</dd>
        <dt>Resposta</dt><dd class="resp">{e(linha["resposta"])}</dd>
        {ref}
        {ragas}
      </dl>
    </details>"""


def _secao_detalhe(d: Dados) -> str:
    if not d.detalhe:  # sem `export_detalhe`, não há o que listar
        return ""
    contagem = Counter(linha["categoria"] for linha in d.detalhe)
    botoes = [
        f'<button type="button" class="filtro ativo" data-filtro="todas">todas ({len(d.detalhe)})</button>'
    ]
    for categoria, n in sorted(contagem.items()):
        botoes.append(
            f'<button type="button" class="filtro" data-filtro="{e(categoria)}">'
            f"{e(CAT_CURTA.get(categoria, categoria))} ({n})</button>"
        )

    itens = "\n      ".join(_pergunta(linha) for linha in d.detalhe)

    return f"""  <section id="detalhe">
    <h2><span class="num">07</span>Pergunta a pergunta</h2>
    <p class="dek">As {len(d.detalhe)} perguntas da rodada, com o que deveria ter sido recuperado, o que a busca trouxe, o que sobrou depois do juiz, a resposta que saiu e a referência curada.</p>

    <p>Se a resposta está <em>certa</em> é a pergunta que nenhuma métrica desta página responde, e é deliberado: correção de conteúdo do MCR é julgamento de quem entende de crédito rural. O que está aqui é o material para esse julgamento — resposta e referência lado a lado, com as seções que o sistema tinha em mãos na hora de escrever.</p>

    <div class="legenda">
      <p><span class="sec ok">✓ MCR 10-2</span> seção do gabarito · <span class="sec">MCR 7-4</span> fora do gabarito · <span class="sec cortado">MCR 7-4</span> descartada pelo juiz · passe o mouse para ver o título da seção e o score.</p>
      <p>O selo diz apenas se a seção do gabarito chegou ao contexto final — não se a resposta está correta.</p>
    </div>

    <div class="filtros" role="group" aria-label="Filtrar perguntas por categoria">
      {"".join(botoes)}
    </div>

    <div class="lista">
      {itens}
    </div>
  </section>

"""


def _secao_baseline(d: Dados) -> str:
    bruto, pos = d.medias["recuperados"], d.medias["trechos"]
    return f"""  <section id="baseline">
    <h2><span class="num">08</span>Comparação com o baseline da TCC-1</h2>
    <p class="dek">O número antigo era {n2(BASELINE_TCC1["precisao"])} de precisão e {n2(BASELINE_TCC1["cobertura"])} de cobertura, sobre {BASELINE_TCC1["n"]} consultas rotuladas à mão.</p>

    <div class="table-wrap">
      <table>
        <thead><tr><th></th><th class="num">TCC-1</th><th class="num">Busca crua</th><th class="num">Pós-juiz</th></tr></thead>
        <tbody>
          <tr><td>Perguntas</td><td class="num">{BASELINE_TCC1["n"]}</td><td class="num">{bruto["n"]}</td><td class="num">{pos["n"]}</td></tr>
          <tr><td>Precisão</td><td class="num">{n2(BASELINE_TCC1["precisao"])}</td><td class="num">{n2(bruto["precisao"])}</td><td class="num">{n2(pos["precisao"])}</td></tr>
          <tr><td>Cobertura</td><td class="num">{n2(BASELINE_TCC1["cobertura"])}</td><td class="num">{n2(bruto["cobertura"])}</td><td class="num">{n2(pos["cobertura"])}</td></tr>
          <tr><td>Rotulagem</td><td class="num">manual</td><td class="num">automática</td><td class="num">automática</td></tr>
        </tbody>
      </table>
    </div>

    <p>A comparação direta não é válida, e é melhor dizer isso antes que alguém pergunte: o conjunto de perguntas é outro, o rótulo de relevância agora é automático (par capítulo-seção) e o pipeline ganhou reescrita de consulta e juiz desde então. O que dá para afirmar é que <strong>o n saiu de {BASELINE_TCC1["n"]} para {pos["n"]}</strong>, que a medição virou reprodutível — mesma rodada, mesmo número, a qualquer momento — e que a cobertura na saída da busca ({n2(bruto["cobertura"])}) mostra que a informação necessária está chegando.</p>
  </section>

"""


def _secao_limites(d: Dados) -> str:
    contagem = d.contagem_categorias()
    menores = sorted(contagem.items(), key=lambda kv: kv[1])[:1]
    frase_menor = (
        f"<code>{e(menores[0][0])}</code> tem {menores[0][1]} perguntas verificadas: os números dela são anedota, não medida."
        if menores
        else ""
    )
    return f"""  <section id="limites">
    <h2><span class="num">09</span>O que estes números não sustentam</h2>
    <p class="dek">Para declarar antes da banca perguntar.</p>
    <ul>
      <li><strong>Corpus pequeno.</strong> 101 chunks. Recuperar entre ~100 seções é mais fácil do que entre 100 mil; nada aqui se transfere para um corpus grande sem nova medição.</li>
      <li><strong>Gabarito de um autor só.</strong> As referências foram conferidas pelo autor do trabalho, não por especialista em crédito rural. É o que a sessão com os analistas do Sicredi deve calibrar.</li>
      <li><strong>Juiz e gerador do mesmo fornecedor.</strong> A resposta vem do <code>gemini-2.5-pro</code> e a avaliação do <code>gemini-2.5-flash</code>. O viés de autopreferência documentado por Zheng et al. fica reduzido, não eliminado.</li>
      <li><strong>Categorias desbalanceadas.</strong> {frase_menor} O total é puxado pela categoria mais numerosa.</li>
      <li><strong>Uma rodada só.</strong> Sem repetição, não há variância conhecida — e o gerador e os juízes são estocásticos. Rodar três vezes daria uma faixa em vez de um ponto.</li>
      <li><strong>A resposta de referência não é independente.</strong> O campo <code>resposta_rascunho</code> foi escrito a partir dos mesmos chunks indexados, então favorece o sistema nas métricas que dependem dele.</li>
      <li><strong>As notas do RAGAS medem a resposta sem o convite de handoff</strong>, que é o que o usuário lê no fim de cada resposta. Ele sai antes da pontuação por não ser afirmação sobre o MCR.</li>
    </ul>
  </section>

"""


PROXIMOS = """  <section id="proximos">
    <h2><span class="num">10</span>Próximos passos, em ordem de retorno</h2>
    <ul>
      <li><strong>Completar a curadoria das categorias com poucas perguntas</strong>, sobretudo <code>referencia_cruzada</code> — é a mais difícil e a com menos evidência.</li>
      <li><strong>Repetir a rodada três vezes</strong> e reportar média e desvio, para a banca ver a variância em vez de um ponto isolado.</li>
      <li><strong>Revisar o formato da citação de capítulo e seção</strong>, ou instruir o juiz do RAGAS a não tratá-la como afirmação: é o que sobra puxando a fidelidade para baixo.</li>
      <li><strong>Medir o Agente Conselheiro</strong>, que esta rodada não cobre: acurácia de roteamento, extração de slots e fundamentação da recomendação do Pronamp.</li>
      <li><strong>Levar 20 a 30 perguntas à sessão com o Sicredi</strong> e calcular a concordância com o juiz automático — é o que transforma estes números em evidência validada.</li>
    </ul>
  </section>
"""


def render(d: Dados, titulo: str = "Avaliação do RAGro") -> str:
    pos = d.medias["trechos"]
    lat = d.latencias()
    ragas = d.ragas()
    fidelidade = n2(ragas["total"][1]["faithfulness"]) if ragas else "—"

    cabecalho = f"""<title>{e(titulo)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600&family=Source+Sans+3:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{ESTILO}</style>

<div class="wrap">

  <header class="top">
    <div class="kicker">RAGro · avaliação automática do Agente Q&amp;A</div>
    <h1>O que a avaliação do Agente Q&amp;A mostrou</h1>
    <p class="standfirst">{len(d.registros)} perguntas curadas do Manual de Crédito Rural, respondidas pelo sistema e medidas em duas camadas: recuperação por contagem, geração por LLM-juiz. Cada métrica está explicada antes do número que ela produz.</p>

    <dl class="ficha">
      <div><dt>Perguntas</dt><dd>{len(d.registros)}</dd></div>
      <div><dt>Acerto</dt><dd>{pos["acerto"]:.0%}</dd></div>
      <div><dt>Cobertura</dt><dd>{n2(pos["cobertura"])}</dd></div>
      <div><dt>Precisão</dt><dd>{n2(pos["precisao"])}</dd></div>
      <div><dt>Fidelidade</dt><dd>{fidelidade}</dd></div>
      <div><dt>Latência mediana</dt><dd>{lat["mediana"]:.0f} s</dd></div>
    </dl>
  </header>

"""

    rodape = f"""  <footer>
    Dados brutos em <code>{e(d.caminho.name)}</code> · página gerada por <code>eval/relatorio.py</code> · reprodução em <code>eval/README.md</code><br>
    Métricas de recuperação por contagem, sem LLM. Abstenção e RAGAS julgados por <code>gemini-2.5-flash</code>. Correção da resposta: julgamento humano, fora desta página.
  </footer>
</div>
{SCRIPT}"""

    return (
        cabecalho
        + _secao_o_que(d)
        + _secao_pipeline(d)
        + METRICAS
        + _secao_recuperacao(d)
        + _secao_abstencao(d)
        + _secao_ragas(d)
        + _secao_detalhe(d)
        + _secao_baseline(d)
        + _secao_limites(d)
        + PROXIMOS
        + rodape
    )

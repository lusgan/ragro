/*
 * Extrai a árvore de decisão do simulador oficial do PRONAF para
 * `src/pronaf/ruleset.json`.
 *
 *   node scripts/extract_pronaf/extract.js
 *
 * Por que Node num projeto Python: o simulador é uma página estática de ~540 KB
 * sem API — todas as regras são literais JavaScript inline (`LINHAS_PF`,
 * `QUESTIONS`, …), com predicados de elegibilidade escritos como arrow
 * functions. Avaliar esse JS no próprio JS é o jeito honesto de lê-lo; Node é
 * dependência só de re-extração, nunca de runtime. O ragro consome apenas o
 * JSON resultante.
 *
 * O passo que dá confiança é o VERIFY: cada predicado é transpilado para uma
 * AST declarativa e então comparado com a função original em todo o espaço de
 * estados alcançável. Só grava o ruleset se a equivalência for exata.
 */

const fs = require('fs');
const path = require('path');
const { parsePredicate, evalAst } = require('./transpile.js');

const URL = 'https://simuladorpronaf.mda.gov.br/';
const OUT = path.join(__dirname, '..', '..', 'src', 'pronaf', 'ruleset.json');

/* Trechos do <script> inline que contêm as regras. Se a extração falhar depois
 * de uma atualização do site, é quase sempre aqui que se mexe: os marcadores
 * são âncoras textuais, não números de linha. */
const BLOCOS = [
  { de: 'const BANCO_NOMES', ate: '/* ── GRUPO META ── */' },
  { de: 'const GM=', ate: 'const TIPO_OPTS=' },
  { de: 'const TIPO_OPTS=', ate: '/* ── PROGRESS ── */' },
];

async function baixar() {
  const res = await fetch(URL);
  if (!res.ok) throw new Error(`GET ${URL} → HTTP ${res.status}`);
  return res.text();
}

function fatiar(html) {
  const ini = html.indexOf('<script>');
  const fim = html.lastIndexOf('</script>');
  if (ini < 0 || fim < 0) throw new Error('não achei o <script> inline do simulador');
  const js = html.slice(ini + '<script>'.length, fim);
  const partes = BLOCOS.map(({ de, ate }) => {
    const a = js.indexOf(de);
    const b = js.indexOf(ate, a + 1);
    if (a < 0 || b < 0) throw new Error(`bloco não encontrado: ${de} … ${ate}`);
    return js.slice(a, b);
  });
  return ['let state = {};', ...partes].join('\n');
}

function carregar(fonte) {
  const exporta =
    'module.exports={TIPO_OPTS,RENDA_OPTS,PERFIL_OPTS,FINAL_PF,FINAL_COOP,COOP_PERFIL,' +
    'QUESTIONS,LINHAS_PF,LINHAS_COOP,BANCO_NOMES,BANCO_OBS,getBancosPorLinha,SUDENE_MG,SUDENE_ES};';
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', fonte + '\n' + exporta)(mod, mod.exports, require);
  return mod.exports;
}

/* Campos que o simulador calcula em função do estado (bônus por região etc.).
 * Reduz para valor fixo quando não varia, ou para um mapa por região. */
function resolverCampo(linha, campo, regioes, rendas) {
  if (typeof linha[campo] !== 'function') {
    return { tipo: 'fixo', valor: linha[campo] === undefined ? null : linha[campo] };
  }
  const base = { renda: 'ate60k', perfil: [], finalidade: [] };
  const porRegiao = {};
  const distintos = new Set();
  for (const regiao of regioes) {
    porRegiao[regiao] = linha[campo]({ ...base, regiao });
    distintos.add(JSON.stringify(porRegiao[regiao]));
  }
  const dependeRenda = rendas.some(
    (renda) =>
      JSON.stringify(linha[campo]({ ...base, renda, regiao: 'su' })) !== JSON.stringify(porRegiao.su)
  );
  if (distintos.size === 1 && !dependeRenda) {
    return { tipo: 'fixo', valor: JSON.parse([...distintos][0]) };
  }
  return { tipo: 'por_regiao', valor: porRegiao, depende_renda: dependeRenda };
}

/* Prova que cada AST decide exatamente como a função original, varrendo todo o
 * espaço de estados que o questionário consegue produzir. */
function verificar(e, asts) {
  const rendas = e.RENDA_OPTS.map((o) => o.v);
  const perfis = e.PERFIL_OPTS.map((o) => o.v);
  const finsPf = e.FINAL_PF.map((o) => o.v);
  const finsCoop = e.FINAL_COOP.map((o) => o.v);
  const orgs = e.QUESTIONS.find((q) => q.id === 'organico').opts.map((o) => o.v);
  const regioes = e.QUESTIONS.find((q) => q.id === 'regiao').opts.map((o) => o.v);
  const coopPerfis = e.COOP_PERFIL.map((o) => o.v);
  const subconjuntos = (arr) => {
    const out = [];
    for (let m = 0; m < 1 << arr.length; m++) {
      const s = [];
      for (let i = 0; i < arr.length; i++) if (m & (1 << i)) s.push(arr[i]);
      out.push(s);
    }
    return out;
  };

  let estados = 0;
  let avaliacoes = 0;
  const divergencias = [];
  const conferir = (linhas, s) => {
    estados++;
    for (const l of linhas) {
      avaliacoes++;
      if (!!l.show(s) !== !!evalAst(asts[l.id], s) && divergencias.length < 5) {
        divergencias.push({ id: l.id, estado: s });
      }
    }
  };

  for (const renda of rendas)
    for (const regiao of regioes)
      for (const sudene of regiao === 'se' ? [false, true] : [false])
        for (const perfil of subconjuntos(perfis))
          for (const finalidade of subconjuntos(finsPf))
            for (const organico of finalidade.includes('custeio') ? orgs : [undefined])
              conferir(e.LINHAS_PF, {
                tipo: 'individual', renda, perfil, finalidade, organico, regiao,
                sudene_municipio_ok: sudene,
              });

  for (const coop_perfil of coopPerfis)
    for (const regiao of regioes)
      for (const finalidade of subconjuntos(finsCoop))
        conferir(e.LINHAS_COOP, { tipo: 'cooperativa', coop_perfil, finalidade, regiao });

  return { estados, avaliacoes, divergencias };
}

async function main() {
  const html = await baixar();
  const e = carregar(fatiar(html));
  const regioes = e.QUESTIONS.find((q) => q.id === 'regiao').opts.map((o) => o.v);
  const rendas = e.RENDA_OPTS.map((o) => o.v);
  const todas = [...e.LINHAS_PF, ...e.LINHAS_COOP];

  const asts = {};
  for (const l of todas) asts[l.id] = parsePredicate(String(l.show));

  const { estados, avaliacoes, divergencias } = verificar(e, asts);
  if (divergencias.length) {
    console.error('AST divergiu do simulador — ruleset NÃO gravado:');
    divergencias.forEach((d) => console.error('  ', JSON.stringify(d)));
    process.exit(1);
  }
  console.log(
    `verificação: ${estados.toLocaleString('pt-BR')} estados, ` +
      `${avaliacoes.toLocaleString('pt-BR')} avaliações, 0 divergências`
  );

  const empacotar = (l, escopo) => ({
    id: l.id,
    nome: l.nome,
    grupo_finalidade: l.grp,
    grupo_pronaf: l.grupoLabel,
    limite: resolverCampo(l, 'limite', regioes, rendas),
    limite_mil_reais: resolverCampo(l, 'limiteRaw', regioes, rendas),
    juros_aa_pct: l.juros ?? null,
    prazo_anos: l.prazoAnos ?? null,
    carencia_anos: l.carenciaAnos ?? null,
    prazo_texto: l.prazo ?? null,
    carencia_texto: l.carencia ?? null,
    bonus_adimplencia: resolverCampo(l, 'bonus', regioes, rendas),
    observacao: resolverCampo(l, 'obs', regioes, rendas),
    destaque: !!l.destaque,
    escopo,
    elegibilidade_js: String(l.show).replace(/\s+/g, ' ').trim(),
    elegibilidade: asts[l.id],
  });

  const pergunta = (texto, multipla, opcoes, extra = {}) => ({ texto, multipla, opcoes, ...extra });
  const doQuestions = Object.fromEntries(
    e.QUESTIONS.filter((q) => !q.id.endsWith('_DISABLED')).map((q) => [
      q.id,
      pergunta(typeof q.text === 'function' ? q.text({}) : q.text, false, q.opts, {
        condicao: q.show ? parsePredicate(String(q.show)) : null,
      }),
    ])
  );

  const ruleset = {
    fonte: URL,
    plano_safra: '2026/2027',
    extraido_em: new Date().toISOString().slice(0, 10),
    metodo:
      'AST transpilada dos predicados show() do simulador oficial; equivalência ' +
      `verificada em ${avaliacoes.toLocaleString('pt-BR')} avaliações sobre ` +
      `${estados.toLocaleString('pt-BR')} estados (0 divergências).`,
    perguntas: {
      tipo: pergunta('Você é agricultor(a) familiar ou cooperativa?', false, e.TIPO_OPTS),
      renda: pergunta('Qual a renda bruta anual da família?', false, e.RENDA_OPTS),
      perfil: pergunta('Qual o seu perfil?', true, e.PERFIL_OPTS, { somente_tipo: 'individual' }),
      finalidade_pf: pergunta('Para que você precisa do crédito?', true, e.FINAL_PF, {
        somente_tipo: 'individual',
      }),
      finalidade_coop: pergunta('Para que a cooperativa precisa do crédito?', true, e.FINAL_COOP, {
        somente_tipo: 'cooperativa',
      }),
      coop_perfil: pergunta('A cooperativa se enquadra no perfil A/A-C?', false, e.COOP_PERFIL, {
        somente_tipo: 'cooperativa',
      }),
      ...doQuestions,
    },
    ordem_perguntas: {
      individual: ['tipo', 'renda', 'perfil', 'finalidade', 'organico', 'regiao'],
      cooperativa: ['tipo', 'coop_perfil', 'finalidade', 'regiao'],
    },
    bancos: {
      nomes: e.BANCO_NOMES,
      observacoes: e.BANCO_OBS,
      regra_js: String(e.getBancosPorLinha).replace(/\s+/g, ' ').trim(),
    },
    municipios_sudene: { mg: e.SUDENE_MG, es: e.SUDENE_ES },
    linhas: [
      ...e.LINHAS_PF.map((l) => empacotar(l, 'individual')),
      ...e.LINHAS_COOP.map((l) => empacotar(l, 'cooperativa')),
    ],
  };

  fs.writeFileSync(OUT, JSON.stringify(ruleset, null, 2));
  console.log(`ruleset gravado: ${OUT} (${ruleset.linhas.length} linhas)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

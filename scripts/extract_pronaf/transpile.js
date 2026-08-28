/* Parser recursivo-descendente para o subconjunto de JS usado nos predicados show(). */
function parsePredicate(src){
  let s = src.replace(/\/\/[^\n]*/g,'').replace(/\s+/g,' ').trim();
  const m = s.match(/^s\s*=>\s*(.*)$/) || s.match(/^\(\s*s\s*\)\s*=>\s*(.*)$/) || s.match(/^\(\s*\)\s*=>\s*(.*)$/);
  if(!m) throw new Error('assinatura nao reconhecida: '+src);
  let t = m[1], i = 0;
  const ws=()=>{while(t[i]===' ')i++;};
  const eat=lit=>{ws(); if(t.startsWith(lit,i)){i+=lit.length;return true;} return false;};
  const expect=lit=>{if(!eat(lit)) throw new Error(`esperava ${lit} em ${i} de: ${t}`);};
  const str=()=>{ws(); const q=t[i]; if(q!=="'"&&q!=='"') throw new Error('esperava string em '+i);
    let j=++i, out=''; while(t[j]!==q){out+=t[j];j++;} i=j+1; return out;};
  const ident=()=>{ws(); const mm=/^[A-Za-z_$][A-Za-z0-9_$]*/.exec(t.slice(i)); if(!mm)throw new Error('esperava ident em '+i); i+=mm[0].length; return mm[0];};

  function orExpr(){ let l=andExpr(); while(eat('||')) l={op:'ou',args:[l,andExpr()]}; return l; }
  function andExpr(){ let l=unary();  while(eat('&&')) l={op:'e', args:[l,unary()]};  return l; }
  function unary(){ ws(); if(t.startsWith('!!',i)){i+=2; return {op:'truthy',arg:unary()};}
                    if(t[i]==='!'){i++; return {op:'nao',arg:unary()};} return primary(); }
  function cmpTail(node){ ws();
    if(eat('===')) return {op:'igual', arg:node, valor:str()};
    if(eat('!==')) return {op:'diferente', arg:node, valor:str()};
    return node; }
  function primary(){ ws();
    if(eat('(')){ const e=orExpr(); expect(')'); return cmpTail(e); }
    if(t.startsWith('false',i)){ i+=5; return {op:'const',valor:false}; }
    if(t.startsWith('true',i)){ i+=4; return {op:'const',valor:true}; }
    if(t.startsWith('s.',i)){ i+=2; const f=ident(); return cmpTail({op:'campo',campo:f}); }
    const name=ident();
    if(eat('(')){ const args=[];
      if(!eat(')')){ do{ ws();
          if(t.startsWith('s',i)&&!/[A-Za-z0-9_$]/.test(t[i+1]||'')){i++;args.push({op:'estado'});}
          else args.push({op:'lit',valor:str()});
        } while(eat(',')); expect(')'); }
      const lits=args.filter(a=>a.op==='lit').map(a=>a.valor);
      switch(name){
        case 'fin':  return {op:'contem',campo:'finalidade',valor:lits[0]};
        case 'perf': return {op:'contem',campo:'perfil',valor:lits[0]};
        case 'semP': return {op:'nao',arg:{op:'contem',campo:'perfil',valor:lits[0]}};
        case 'temPesca': return {op:'contem',campo:'finalidade',valor:'pesca'};
        case 'temNaoCusteio': return {op:'tem_finalidade_alem_de',valor:'custeio'};
        case 'temQ': return {op:'tem_alguma_finalidade'};
        case 'rEquip': case 'rendaEquip': return cmpTail({op:'renda_equivalente'});
        default: throw new Error('funcao desconhecida: '+name);
      }
    }
    throw new Error('token inesperado em '+i+': '+t.slice(i,i+30));
  }
  const ast=orExpr(); ws();
  if(i<t.length) throw new Error('sobrou "'+t.slice(i)+'" em: '+t);
  return ast;
}

/* Avaliador da AST em JS — usado só para provar que a AST == funcao original */
function evalAst(n,s){
  switch(n.op){
    case 'const': return n.valor;
    case 'e': return evalAst(n.args[0],s)&&evalAst(n.args[1],s);
    case 'ou': return evalAst(n.args[0],s)||evalAst(n.args[1],s);
    case 'nao': return !evalAst(n.arg,s);
    case 'truthy': return !!rawv(n.arg,s);
    case 'contem': return Array.isArray(s[n.campo])&&s[n.campo].includes(n.valor);
    case 'tem_finalidade_alem_de': return Array.isArray(s.finalidade)&&s.finalidade.some(f=>f!==n.valor);
    case 'tem_alguma_finalidade': return Array.isArray(s.finalidade)&&s.finalidade.length>0;
    case 'igual': return rawv(n.arg,s)===n.valor;
    case 'diferente': return rawv(n.arg,s)!==n.valor;
    default: return !!rawv(n,s);
  }
}
function rawv(n,s){
  if(n.op==='campo') return s[n.campo];
  if(n.op==='renda_equivalente') return s.renda==='ate714k'?'ate500k':s.renda;
  return evalAst(n,s);
}
module.exports={parsePredicate,evalAst};

"""Escape de texto para o markdown do Streamlit.

O Streamlit renderiza `$...$` como LaTeX. Num app sobre crédito rural isso não
é detalhe de estilo: "De R$ 60 mil a R$ 150 mil" tem dois cifrões, o par vira
modo matemático e o texto exibido perde os dois `$` — o usuário lê "De R 60 mil
a R 150 mil". Todo valor em reais que aparece em par no mesmo parágrafo some
assim, e é justamente o formato em que limites, faixas de renda e juros
aparecem.

Por isso todo texto de origem externa (LLM, MCR, entrada do usuário) passa por
`escapar` antes de ir para `st.markdown`/`st.write`.
"""

from __future__ import annotations

import re

# Só cifrão ainda não escapado — reescapar viraria uma barra invertida visível.
_CIFRAO_NAO_ESCAPADO = re.compile(r"(?<!\\)\$")


def escapar(texto: str) -> str:
    """Escapa `$` para o Streamlit não interpretar o trecho como LaTeX.

    Limitação conhecida: não distingue cifrão dentro de bloco de código, onde o
    Streamlit já não renderiza LaTeX e a barra invertida apareceria literal. As
    respostas dos agentes são prosa e tabelas, não código, então a troca vale a
    pena; se algum dia gerarem blocos de código, isto precisa virar um parser.
    """
    if not texto:
        return texto
    return _CIFRAO_NAO_ESCAPADO.sub(r"\\$", texto)

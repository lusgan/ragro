"""Índice de capítulos do MCR (Manual de Crédito Rural).

Serve só para orientar o filtro de metadados em `retriever.py` — não é fonte
de verdade sobre o conteúdo de cada capítulo, só um mapa dos números para o
`rewriter` inferir um filtro plausível a partir do assunto da pergunta.

Um capítulo errado aqui custa recall, nunca corretude: o filtro inferido é
sempre descartável (`retriever.buscar_com_fallback`) e, se zerar os
resultados, a busca é refeita sem ele. O pior caso é buscar mais do que o
necessário — nunca responder com base no capítulo errado.
"""

from __future__ import annotations

CAPITULOS: dict[int, str] = {
    1: "Disposições Preliminares",
    2: "Condições Básicas",
    3: "Operações",
    4: "Finalidade e Instrumentos Especiais de Política Agrícola",
    5: "Crédito a Cooperativas de Produção Agropecuária",
    6: "Recursos",
    7: "Encargos Financeiros e Limites de Crédito",
    8: "Programa Nacional de Apoio ao Médio Produtor Rural (Pronamp)",
    9: "Fundo de Defesa da Economia Cafeeira (Funcafé)",
    10: "Programa Nacional de Fortalecimento da Agricultura Familiar (Pronaf)",
    11: "Programas de Investimento Agropecuário (InvestAgro)",
    12: "Programa de Garantia da Atividade Agropecuária (Proagro)",
}

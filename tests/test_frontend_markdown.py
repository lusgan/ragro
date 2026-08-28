"""Escape de cifrão antes do markdown do Streamlit.

Bug real: as faixas de renda da triagem apareciam como "De R 60 mil a R 150
mil" — o Streamlit leu o par de `$` como LaTeX e comeu os dois. Num app cujo
produto é justamente o valor em reais, isso não é cosmético.
"""

from __future__ import annotations

from frontend.markdown import escapar


def test_par_de_cifroes_no_mesmo_texto_e_escapado() -> None:
    """O caso que quebrou: dois valores em reais no mesmo parágrafo."""
    assert escapar("De R$ 60 mil a R$ 150 mil por ano") == (
        "De R\\$ 60 mil a R\\$ 150 mil por ano"
    )


def test_cifrao_isolado_tambem_e_escapado() -> None:
    """Um `$` sozinho não vira LaTeX hoje, mas basta o próximo parágrafo ter
    outro para o par se formar na mesma renderização."""
    assert escapar("Limite de R$ 250 mil") == "Limite de R\\$ 250 mil"


def test_cifrao_ja_escapado_nao_e_escapado_de_novo() -> None:
    """Reescapar mostraria a barra invertida literal para o usuário."""
    assert escapar("R\\$ 100") == "R\\$ 100"


def test_texto_sem_cifrao_passa_intacto() -> None:
    texto = "Pronaf Custeio – Faixa III, juros de 1% ao ano."
    assert escapar(texto) == texto


def test_texto_vazio_e_none_nao_quebram() -> None:
    assert escapar("") == ""
    assert escapar(None) is None


def test_valores_do_engine_sobrevivem_ao_escape() -> None:
    """O texto continua legível: o escape some na renderização, não no sentido."""
    escapado = escapar("Até R$ 1.500.000,00 por beneficiário")
    assert escapado.replace("\\", "") == "Até R$ 1.500.000,00 por beneficiário"

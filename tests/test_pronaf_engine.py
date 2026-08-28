"""
Paridade entre `src/pronaf/engine.py` e o simulador oficial do MDA.

O motor Python não reimplementa as regras do PRONAF: ele interpreta ASTs
transpiladas dos predicados `show()` do simulador. Isso move o risco para dois
pontos, e é exatamente neles que estes testes batem:

1. **O interpretador de AST** pode divergir do JavaScript original (precedência,
   coerção de tipo, campo ausente). O golden fixture em `fixtures/` guarda 3.000
   estados sorteados com a resposta que o simulador oficial dá — gerado por
   `scripts/extract_pronaf/extract.js`, que por sua vez só emite o ruleset após
   provar a equivalência AST↔`show()` em 275 milhões de avaliações.
2. **O fluxo do questionário** (`proxima_pergunta`) pode pedir algo fora de
   ordem ou parar cedo, produzindo um perfil incompleto que ainda assim avalia
   sem erro — silenciosamente recomendando a linha errada.

Se o Plano Safra mudar, o fixture precisa ser regerado junto com o ruleset;
falha aqui depois de uma re-extração significa regra nova, não bug.
"""

import json
from pathlib import Path

import pytest

from src.programs.pronaf.engine import (
    Perfil,
    PerfilInvalido,
    avaliar,
    municipio_sudene,
    proxima_pergunta,
    recomendar,
    ruleset,
)

GOLDEN = Path(__file__).parent / "fixtures" / "pronaf_golden.json"


def _perfil(estado: dict) -> Perfil:
    return Perfil(
        tipo=estado["tipo"],
        renda=estado.get("renda"),
        perfil=estado.get("perfil") or [],
        finalidade=estado.get("finalidade") or [],
        organico=estado.get("organico"),
        regiao=estado.get("regiao"),
        coop_perfil=estado.get("coop_perfil"),
        sudene_municipio_ok=bool(estado.get("sudene_municipio_ok")),
    )


def test_paridade_com_simulador_oficial() -> None:
    """Todo estado do golden produz exatamente as linhas do simulador oficial."""
    casos = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(casos) == 3000, "fixture truncado — regere com extract.js"

    divergencias = [
        (c["estado"], [linha.id for linha in avaliar(_perfil(c["estado"]))], c["esperado"])
        for c in casos
        if [linha.id for linha in avaliar(_perfil(c["estado"]))] != c["esperado"]
    ]
    assert not divergencias, f"{len(divergencias)} estados divergiram: {divergencias[:3]}"


def test_ordem_das_linhas_e_preservada() -> None:
    """A ordem importa: o simulador lista por relevância, não alfabeticamente."""
    p = Perfil(
        tipo="individual", renda="ate60k", perfil=["mulher"],
        finalidade=["custeio"], organico="sim", regiao="ne",
    )
    assert [linha.id for linha in avaliar(p)] == [
        "b_custeio_org", "mulher_custeio_org", "custeio_f3",
    ]


class TestFluxoDoQuestionario:
    def test_comeca_perguntando_o_tipo(self) -> None:
        q = proxima_pergunta(Perfil())
        assert q is not None and q["id"] == "tipo"

    def test_pessoa_fisica_percorre_a_ordem_oficial(self) -> None:
        p = Perfil()
        vistas = []
        respostas = {
            "tipo": lambda: setattr(p, "tipo", "individual"),
            "renda": lambda: setattr(p, "renda", "ate150k"),
            "perfil": lambda: setattr(p, "perfil", ["geral"]),
            "finalidade": lambda: setattr(p, "finalidade", ["custeio", "maquinas"]),
            "organico": lambda: setattr(p, "organico", "alimentos"),
            "regiao": lambda: setattr(p, "regiao", "su"),
        }
        while (q := proxima_pergunta(p)) is not None:
            vistas.append(q["id"])
            respostas[q["id"]]()
            assert len(vistas) <= 6, "questionário não termina"
        assert vistas == ["tipo", "renda", "perfil", "finalidade", "organico", "regiao"]

    def test_organico_so_e_perguntado_no_custeio(self) -> None:
        """`organico` qualifica a safra — sem custeio, a pergunta não faz sentido."""
        p = Perfil(tipo="individual", renda="ate150k", perfil=["geral"], finalidade=["maquinas"])
        q = proxima_pergunta(p)
        assert q is not None and q["id"] == "regiao"

    def test_cooperativa_pula_renda_e_perfil_da_pessoa(self) -> None:
        p = Perfil(tipo="cooperativa")
        vistas = []
        while (q := proxima_pergunta(p)) is not None:
            vistas.append(q["id"])
            if q["id"] == "coop_perfil":
                p.coop_perfil = "coop_geral"
            elif q["id"] == "finalidade":
                p.finalidade = ["coop_agro_invest"]
            elif q["id"] == "regiao":
                p.regiao = "su"
            assert len(vistas) <= 3
        assert vistas == ["coop_perfil", "finalidade", "regiao"]
        assert "renda" not in vistas and "perfil" not in vistas


class TestRegrasQueDependemDoContexto:
    def test_bonus_de_adimplencia_varia_por_regiao(self) -> None:
        """Mesmo perfil, mesma linha, bônus diferente — Norte/Nordeste tem; Sul não."""
        def bonus(regiao: str) -> str | None:
            p = Perfil(
                tipo="individual", renda="ate60k", perfil=["geral"],
                finalidade=["custeio"], organico="sim", regiao=regiao,
            )
            return next(l.bonus_adimplencia for l in avaliar(p) if l.id == "b_custeio_org")

        assert "Sim" in bonus("ne")
        assert "Não" in bonus("su")

    def test_assentado_troca_as_linhas_gerais_pelas_de_grupo_a(self) -> None:
        """Marcar `assentado` SUPRIME linhas genéricas — a árvore não é aditiva."""
        base = dict(tipo="individual", renda="ate150k", finalidade=["floresta"], regiao="no")
        geral = {l.id for l in avaliar(Perfil(perfil=["geral"], **base))}
        assentado = {l.id for l in avaliar(Perfil(perfil=["geral", "assentado"], **base))}
        assert "floresta_g" in geral and "floresta_g" not in assentado
        assert "floresta_aab" in assentado

    def test_semiarido_no_sudeste_exige_municipio_da_sudene(self) -> None:
        base = dict(
            tipo="individual", renda="ate150k", perfil=["geral"],
            finalidade=["semiarido"], regiao="se",
        )
        assert not avaliar(Perfil(**base, sudene_municipio_ok=False))
        assert avaliar(Perfil(**base, sudene_municipio_ok=True))

    @pytest.mark.parametrize(
        ("uf", "municipio", "esperado"),
        [
            ("mg", "Montes Claros", True),
            ("mg", "montes claros", True),
            ("mg", "Januaria", True),      # sem acento
            ("mg", "Belo Horizonte", False),
            ("es", "São Mateus", True),
        ],
    )
    def test_municipio_sudene_ignora_acento_e_caixa(
        self, uf: str, municipio: str, esperado: bool
    ) -> None:
        assert municipio_sudene(uf, municipio) is esperado


class TestRecomendarRecusaPerfilErrado:
    """`recomendar` é a superfície que o LLM chama — e o LLM erra o vocabulário.

    O modo de falha caro não é a exceção: é aceitar `renda='60000'`, cair no
    caminho de outra faixa e devolver um limite errado com cara de resposta
    oficial. Cada teste aqui trava uma entrada que precisa falhar alto.
    """

    BASE = {
        "tipo": "individual", "renda": "ate60k", "perfil": ["mulher"],
        "finalidade": ["maquinas"], "regiao": "ne",
    }

    def test_perfil_valido_e_aceito(self) -> None:
        assert recomendar(self.BASE)["total"] > 0

    @pytest.mark.parametrize(
        ("caso", "alteracao"),
        [
            ("renda como número cru", {"renda": "60000"}),
            ("renda fora do vocabulário", {"renda": "media"}),
            ("finalidade inventada", {"finalidade": ["trator"]}),
            ("finalidade como string", {"finalidade": "maquinas"}),
            ("finalidade vazia", {"finalidade": []}),
            ("perfil vazio", {"perfil": []}),
            ("tipo desconhecido", {"tipo": "empresa"}),
            ("campo que não existe", {"idade": 34}),
        ],
    )
    def test_entrada_invalida_falha_alto(self, caso: str, alteracao: dict) -> None:
        with pytest.raises(PerfilInvalido):
            recomendar({**self.BASE, **alteracao})

    def test_campo_obrigatorio_ausente_falha(self) -> None:
        with pytest.raises(PerfilInvalido, match="regiao"):
            recomendar({k: v for k, v in self.BASE.items() if k != "regiao"})

    def test_organico_e_exigido_com_custeio_e_recusado_sem(self) -> None:
        """A pergunta condicional vira contrato: nem faltando, nem sobrando."""
        with pytest.raises(PerfilInvalido, match="organico"):
            recomendar({**self.BASE, "finalidade": ["custeio"]})
        with pytest.raises(PerfilInvalido, match="custeio"):
            recomendar({**self.BASE, "organico": "sim"})

    def test_mensagem_de_erro_lista_os_valores_aceitos(self) -> None:
        """Quem chama é um modelo: o erro precisa ensinar o vocabulário certo."""
        with pytest.raises(PerfilInvalido) as err:
            recomendar({**self.BASE, "renda": "60000"})
        assert "ate60k" in str(err.value) and "ate714k" in str(err.value)

    def test_cooperativa_exige_coop_perfil(self) -> None:
        with pytest.raises(PerfilInvalido, match="coop_perfil"):
            recomendar({"tipo": "cooperativa", "finalidade": ["coop_cotas"], "regiao": "su"})


class TestRecomendarDevolveJson:
    def test_ordem_da_finalidade_nao_muda_a_resposta(self) -> None:
        """A avaliação usa pertinência ao conjunto, não a ordem que o LLM mandou."""
        a = recomendar({**TestRecomendarRecusaPerfilErrado.BASE, "finalidade": ["maquinas", "moradia"]})
        b = recomendar({**TestRecomendarRecusaPerfilErrado.BASE, "finalidade": ["moradia", "maquinas"]})
        assert [l["id"] for l in a["linhas"]] == [l["id"] for l in b["linhas"]]

    def test_saida_e_serializavel_e_carrega_procedencia(self) -> None:
        r = recomendar(TestRecomendarRecusaPerfilErrado.BASE)
        json.dumps(r)  # falha se algum campo não for JSON
        assert r["plano_safra"] == "2026/2027"
        assert r["total"] == len(r["linhas"])
        assert all(l["bancos"] and l["nome"] for l in r["linhas"])

    def test_municipio_da_sudene_decide_o_semiarido_no_sudeste(self) -> None:
        """Mesma resposta de região, resultado oposto conforme o município."""
        se = {
            "tipo": "individual", "renda": "ate150k", "perfil": ["geral"],
            "finalidade": ["semiarido"], "regiao": "se",
        }
        assert recomendar(se)["total"] == 0
        assert recomendar({**se, "municipio": {"uf": "mg", "nome": "Belo Horizonte"}})["total"] == 0
        assert recomendar({**se, "municipio": {"uf": "mg", "nome": "Montes Claros"}})["total"] == 1

    def test_municipio_malformado_falha(self) -> None:
        with pytest.raises(PerfilInvalido, match="municipio"):
            recomendar({**TestRecomendarRecusaPerfilErrado.BASE, "municipio": "Montes Claros"})


def test_ruleset_declara_a_procedencia() -> None:
    """Sem proveniência não dá para saber que safra o motor está respondendo."""
    rs = ruleset()
    assert rs["fonte"].startswith("https://simuladorpronaf.mda.gov.br")
    assert rs["plano_safra"] == "2026/2027"
    assert len(rs["linhas"]) == 66
    assert all(l.get("elegibilidade") for l in rs["linhas"])

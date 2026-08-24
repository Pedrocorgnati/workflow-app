"""Gate da rubrica compartilhada de coerencia de task do /loop (Tasks 12 e 13).

A rubrica canonica vive em `ai-forge/rules/loop-task-coherence.md`. Quatro
comandos a consomem em gates DISTINTOS (produtor, triagem, revisao,
pos-integracao). Este modulo trava duas coisas independentes:

1. **Fiacao** - os quatro consumidores realmente apontam para a rubrica, e o
   gate pos-integracao continua separado do classificador inicial.
2. **Comportamento** - uma implementacao de referencia do teste de conflito da
   secao 4 da rubrica reprova a fixture de contradicao minima e **passa** na
   fixture positiva densa.

O item (2) e o que importa. Fixture negativa sozinha prova que o gate morde;
so a positiva prova que ele nao morde a mao errada. O modo de falha caro de um
gate de coerencia nao e deixar passar contradicao - e bloquear task valida, que
e longa, cita muito codigo e tem Notas ricas. Gate que reprova por suspeita e
gate que o operador desliga.

A implementacao de referencia aqui e deliberadamente estreita: ela cobre C1, C3,
C5 e ANCHOR, que sao os eixos decidiveis por texto. C2 (escopo vs saida) e C4
(simbolos existentes) dependem do workspace real e sao verificados pelos
consumidores em runtime; aqui so travamos que a rubrica os declara.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUBRICA = REPO_ROOT / "ai-forge" / "rules" / "loop-task-coherence.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "loop"
FIXTURE_NEGATIVA = FIXTURES / "task-contradicao-minima.md"
FIXTURE_POSITIVA = FIXTURES / "task-coerente-densa.md"

CONSUMIDORES = {
    "produtor": REPO_ROOT / ".claude/commands/loop/iteraction/create-task.md",
    "triagem": REPO_ROOT / ".claude/commands/loop/individual-analysis.md",
    "revisao": REPO_ROOT / ".claude/commands/loop/iteraction/review-created-task.md",
    "pos_integracao": REPO_ROOT / ".claude/commands/loop/check-tasks-and-cmd.md",
}

RUBRICA_REF = "ai-forge/rules/loop-task-coherence.md"


# ==========================================================================
# Implementacao de referencia do teste de conflito (rubrica secao 4)
# ==========================================================================

# Secoes normativas: onde uma ordem VALE. Notas e Contexto sao descritivas.
_SECOES_NORMATIVAS = {"Objetivo", "Escopo exato", "Pre-requisitos"}
_SECAO_ACEITE = "Criterios de aceite"
_SECOES_DESCRITIVAS = {"Notas", "Contexto"}

_PRESERVAR = re.compile(
    r"(?i)(\bnao\s+(remover|remova|apagar|excluir|comentar|alterar|tocar|mexer)\b"
    r"|\bmanter\b|\bpermanece\b|\bpreservar\b|\bintacto\b|\bcontinua sendo\b)"
)
_REMOVER = re.compile(
    r"(?i)(\bdeve ser removido\b|\bremover\b|\bremovido\b|\bapagar\b|\bexcluir\b|\beliminar\b)"
)
_QUALIFICADOR = re.compile(r"(?i)\b(quando|caso|se|somente se|apenas se)\b")

# Substantivos de dominio que funcionam como alvo mesmo sem crases.
_ALVOS_NOMINAIS = re.compile(r"(?i)\b(curto-circuito|ramo|fallback|guarda|filtro)\b")
_LINHA = re.compile(r"(?i)\blinha\s+(\d+)\b")
_CRASE = re.compile(r"`([^`]+)`")


def _sem_comentarios_html(texto: str) -> str:
    return re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)


def _sem_frontmatter(texto: str) -> str:
    if texto.startswith("---"):
        partes = texto.split("---", 2)
        if len(partes) == 3:
            return partes[2]
    return texto


def _secoes(texto: str) -> dict[str, str]:
    """Corpo por heading `## `. Headings `###` ficam dentro da secao pai."""
    corpo = _sem_frontmatter(_sem_comentarios_html(texto))
    out: dict[str, str] = {}
    atual = "(preambulo)"
    buffer: list[str] = []
    for linha in corpo.splitlines():
        m = re.match(r"^##\s+(?!#)(.+?)\s*$", linha)
        if m:
            out[atual] = "\n".join(buffer)
            atual = m.group(1).strip()
            buffer = []
        else:
            buffer.append(linha)
    out[atual] = "\n".join(buffer)
    return out


def _blocos(corpo: str) -> list[str]:
    """Junta continuacoes de bullet num bloco. Bullet novo inicia bloco."""
    blocos: list[str] = []
    atual: list[str] = []
    for linha in corpo.splitlines():
        strip = linha.strip()
        if not strip:
            continue
        if re.match(r"^([-*]|\*\*ST\d+)", strip):
            if atual:
                blocos.append(" ".join(atual))
            atual = [strip]
        else:
            atual.append(strip)
    if atual:
        blocos.append(" ".join(atual))
    return blocos


def _clausulas(bloco: str) -> list[str]:
    """Divide em clausulas sem quebrar dentro de crases."""
    guardadas: list[str] = []

    def _mascara(m: re.Match) -> str:
        guardadas.append(m.group(0))
        return f"\x00{len(guardadas) - 1}\x00"

    mascarado = _CRASE.sub(_mascara, bloco)
    partes = re.split(r"[.;:]", mascarado)
    saida = []
    for parte in partes:
        restaurada = re.sub(
            r"\x00(\d+)\x00", lambda m: guardadas[int(m.group(1))], parte
        ).strip()
        if restaurada:
            saida.append(restaurada)
    return saida


def _alvos(clausula: str) -> set[str]:
    alvos = {s.strip() for s in _CRASE.findall(clausula) if s.strip()}
    alvos |= {f"linha {n}" for n in _LINHA.findall(clausula)}
    alvos |= {a.lower() for a in _ALVOS_NOMINAIS.findall(clausula)}
    return alvos


def _postura(clausula: str) -> str | None:
    # Preservar e testado primeiro: "nao remover" precisa vencer "remover".
    if _PRESERVAR.search(clausula):
        return "preservar"
    if _REMOVER.search(clausula):
        return "remover"
    return None


def _qualificada(clausula: str) -> bool:
    return bool(_QUALIFICADOR.search(clausula))


def _eixo(secao_a: str, secao_b: str) -> str:
    secoes = {secao_a, secao_b}
    if _SECAO_ACEITE in secoes:
        return "C3"
    if secoes & _SECOES_DESCRITIVAS and secoes & _SECOES_NORMATIVAS:
        return "C1"
    return "C5"


def auditar(texto: str) -> list[dict]:
    """Aplica a rubrica. Devolve achados no formato da secao 6."""
    itens: list[tuple[str, str, str, bool, set[str]]] = []
    for secao, corpo in _secoes(texto).items():
        for bloco in _blocos(corpo):
            for clausula in _clausulas(bloco):
                postura = _postura(clausula)
                alvos = _alvos(clausula)
                if postura and alvos:
                    itens.append(
                        (secao, clausula, postura, _qualificada(clausula), alvos)
                    )

    achados: list[dict] = []
    for i, (sec_a, cl_a, post_a, qual_a, alvos_a) in enumerate(itens):
        for sec_b, cl_b, post_b, qual_b, alvos_b in itens[i + 1 :]:
            # Condicao 1: mesmo alvo.
            comuns = alvos_a & alvos_b
            if not comuns:
                continue
            # Condicao 2: predicados incompativeis.
            if post_a == post_b:
                continue
            # Condicao 3: nenhum qualificador reconcilia.
            if qual_a or qual_b:
                continue
            achados.append(
                {
                    "eixo": _eixo(sec_a, sec_b),
                    "severidade": "bloqueante",
                    "alvo": sorted(comuns)[0],
                    "trecho_a": {"secao": sec_a, "citacao": cl_a},
                    "trecho_b": {"secao": sec_b, "citacao": cl_b},
                    "motivo": "mesmo alvo, predicados incompativeis, sem qualificador",
                }
            )

    # ANCHOR: `linha N` sem simbolo entre crases na mesma clausula.
    for secao, corpo in _secoes(texto).items():
        for bloco in _blocos(corpo):
            for clausula in _clausulas(bloco):
                if _LINHA.search(clausula) and not _CRASE.search(clausula):
                    achados.append(
                        {
                            "eixo": "ANCHOR",
                            "severidade": "bloqueante",
                            "alvo": f"linha {_LINHA.search(clausula).group(1)}",
                            "trecho_a": {"secao": secao, "citacao": clausula},
                            "motivo": "numero de linha isolado, sem ancora simbolica",
                        }
                    )
    return achados


def _bloqueantes(achados: list[dict]) -> list[dict]:
    return [a for a in achados if a["severidade"] == "bloqueante"]


# ==========================================================================
# 1) Fiacao: a rubrica existe e os quatro consumidores a consomem
# ==========================================================================


def test_rubrica_existe_e_declara_os_cinco_eixos_mais_ancoragem():
    texto = RUBRICA.read_text(encoding="utf-8")
    for eixo in ("C1", "C2", "C3", "C4", "C5"):
        assert f"### {eixo} -" in texto, f"eixo {eixo} ausente da rubrica"
    assert "ANCHOR" in texto


def test_rubrica_cobre_os_cinco_temas_do_fonte():
    texto = RUBRICA.read_text(encoding="utf-8").lower()
    for tema in (
        "instrucao versus notas",
        "escopo versus saida esperada",
        "criterio de aceite versus proibicoes",
        "dependencias e simbolos existentes",
        "afirmacoes imperativas incompativeis",
    ):
        assert tema in texto, f"tema '{tema}' nao coberto pela rubrica (10.3 P1-B)"


def test_rubrica_declara_ancora_simbolica_como_primaria():
    texto = RUBRICA.read_text(encoding="utf-8")
    assert "Ancora simbolica e primaria" in texto
    assert "numero de linha isolado nao satisfaz a rubrica" in texto.lower()


@pytest.mark.parametrize("papel,path", sorted(CONSUMIDORES.items()))
def test_consumidor_aponta_para_a_rubrica(papel, path):
    assert path.exists(), f"consumidor {papel} ausente: {path}"
    assert RUBRICA_REF in path.read_text(encoding="utf-8"), (
        f"{papel} ({path.name}) nao consome a rubrica compartilhada"
    )


def test_gate_pos_integracao_permanece_separado_do_classificador():
    # Compartilhar a rubrica nao pode virar desculpa para fundir fases com
    # responsabilidades diferentes (10.3 P0-C, 14.3).
    pos = CONSUMIDORES["pos_integracao"].read_text(encoding="utf-8")
    assert "POS-INTEGRACAO" in pos
    assert "independente" in pos.lower()
    triagem = CONSUMIDORES["triagem"].read_text(encoding="utf-8")
    assert "TRIAGEM" in triagem
    assert "nao** substitui" in triagem or "nao substitui" in triagem.lower()


def test_papeis_dos_quatro_gates_sao_distintos():
    papeis = {
        "produtor": "PRODUTOR",
        "triagem": "TRIAGEM",
        "revisao": "REVISAO",
        "pos_integracao": "POS-INTEGRACAO",
    }
    for chave, marcador in papeis.items():
        texto = CONSUMIDORES[chave].read_text(encoding="utf-8")
        assert marcador in texto, f"{chave} nao declara o papel {marcador}"


def test_rubrica_exige_fixtures_positiva_e_negativa():
    texto = RUBRICA.read_text(encoding="utf-8")
    assert "task-contradicao-minima.md" in texto
    assert "Positiva (obrigatoria)" in texto


# ==========================================================================
# 2) Comportamento: negativa reprova, positiva passa
# ==========================================================================


def test_fixture_negativa_reprova():
    achados = _bloqueantes(auditar(FIXTURE_NEGATIVA.read_text(encoding="utf-8")))
    assert achados, "a contradicao minima derivada da task 013 passou pelo gate"


def test_fixture_negativa_acusa_o_par_certo():
    achados = _bloqueantes(auditar(FIXTURE_NEGATIVA.read_text(encoding="utf-8")))
    conflitos = [a for a in achados if a["eixo"] in {"C1", "C3", "C5"}]
    assert conflitos, "nenhum achado de contradicao (so ancoragem) na fixture negativa"
    alvos = {a["alvo"] for a in conflitos}
    assert any("curto-circuito" in a or "linha 897" in a for a in alvos), (
        f"o alvo do conflito nao e o curto-circuito da linha 897: {alvos}"
    )
    for a in conflitos:
        assert "trecho_b" in a, "achado de conflito sem os dois lados citados"
        assert a["trecho_a"]["citacao"] and a["trecho_b"]["citacao"]


def test_fixture_negativa_cruza_secoes_distantes():
    # O ponto da rubrica: o conflito nao esta dentro de uma secao, esta ENTRE
    # secoes que a leitura linear nunca aproxima.
    achados = _bloqueantes(auditar(FIXTURE_NEGATIVA.read_text(encoding="utf-8")))
    pares = {
        frozenset({a["trecho_a"]["secao"], a["trecho_b"]["secao"]})
        for a in achados
        if "trecho_b" in a
    }
    assert any(len(p) == 2 for p in pares), (
        "nenhum achado cruza duas secoes distintas"
    )
    assert any("Notas" in p for p in pares), (
        "o conflito com a secao Notas (eixo C1) nao foi detectado"
    )


def test_fixture_positiva_passa():
    achados = _bloqueantes(auditar(FIXTURE_POSITIVA.read_text(encoding="utf-8")))
    assert achados == [], (
        "o gate reprovou uma task valida - este e o modo de falha caro: "
        f"{[(a['eixo'], a['alvo']) for a in achados]}"
    )


def test_qualificador_explicito_nao_vira_contradicao():
    # Condicao 3 da secao 4: "quando X, preservar; caso contrario, remover" e
    # ramificacao, nao contradicao.
    texto = FIXTURE_POSITIVA.read_text(encoding="utf-8")
    assert "caso contrario" in texto and "preservar o ramo" in texto
    assert _bloqueantes(auditar(texto)) == []


def test_qualificador_vago_nao_reconcilia():
    # "se necessario" nao separa casos: continua contradicao.
    texto = """
## Escopo exato

- Nao remover o `helperX`

## Notas

- O `helperX` deve ser removido
"""
    assert _bloqueantes(auditar(texto)), "contradicao sem qualificador passou"


def test_alvos_diferentes_nunca_conflitam():
    # Condicao 1: redacao parecida com alvo diferente nao e achado.
    texto = """
## Escopo exato

- Nao remover o `helperA`

## Notas

- O `helperB` deve ser removido
"""
    assert _bloqueantes(auditar(texto)) == []


def test_mesma_postura_nao_conflita():
    # Condicao 2: aceite que repete a proibicao e reforco, nao contradicao.
    texto = """
## Escopo exato

- Nao remover o `helperX`

## Criterios de aceite

- O `helperX` permanece no codigo
"""
    assert _bloqueantes(auditar(texto)) == []


def test_ancora_de_linha_isolada_reprova():
    texto = "## Escopo exato\n\n- Ajustar o comportamento da linha 897\n"
    achados = _bloqueantes(auditar(texto))
    assert any(a["eixo"] == "ANCHOR" for a in achados)


def test_ancora_de_linha_com_simbolo_passa():
    texto = "## Escopo exato\n\n- Ajustar `buildJobsIntent` (linha 897)\n"
    assert [a for a in _bloqueantes(auditar(texto)) if a["eixo"] == "ANCHOR"] == []


def test_comentario_html_nao_e_auditado():
    # As fixtures explicam a propria armadilha em comentario HTML. Auditar o
    # comentario faria o gate acusar a explicacao como se fosse a task.
    texto = """
## Escopo exato

- Manter o `helperX`

<!-- explicacao: aqui falamos em remover o `helperX` de proposito -->
"""
    assert _bloqueantes(auditar(texto)) == []


def test_achado_de_conflito_sempre_cita_os_dois_lados():
    for fixture in (FIXTURE_NEGATIVA, FIXTURE_POSITIVA):
        for a in auditar(fixture.read_text(encoding="utf-8")):
            if a["eixo"] == "ANCHOR":
                continue
            assert a["trecho_a"]["citacao"].strip()
            assert a["trecho_b"]["citacao"].strip()

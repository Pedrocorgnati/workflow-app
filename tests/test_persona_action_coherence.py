"""Gate G7: o par persona-action de cada seed (bloco C6, Task 18).

Identidade de seed nao termina no nome do arquivo. Um botao da grade dispara
uma persona COM uma action, e o par pode estar errado sem que nenhum dos dois
lados esteja errado sozinho: `questioner-rules.md` e uma persona valida,
`Revisar` e uma action valida, e mesmo assim o par contradiz o que a persona
declara sobre si.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from workflow_app import brainstorm_seed_contract as contract


REPO_ROOT = Path(__file__).parents[3].resolve()

#: Seeds com par persona-action ainda incoerente em disco.
#:
#: VAZIO desde a Task 20, que trocou as actions de `07-questioner.md`,
#: `19-delegador.md` e `22-scaffolds-blueprints-updater.md` pelas tres
#: especializadas. O conjunto continua existindo -- em vez de virar um
#: `assert not reprovados` -- porque nomear a excecao e o que permite
#: reabri-la de forma declarada se algum dia um seed precisar rodar
#: temporariamente com par pendente; e porque o teste falha do mesmo jeito se
#: alguem reintroduzir a incoerencia sem registrar nada aqui.
SEEDS_COM_PAR_PENDENTE: frozenset[str] = frozenset()

_FM_RX = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _seed_pairs() -> dict[str, tuple[str, str]]:
    """Le (agent_path, action) dos 24 seeds canonicos direto do disco."""
    seed_dir = contract.resolve_seed_dir(REPO_ROOT)
    pairs: dict[str, tuple[str, str]] = {}
    for name in contract.CANONICAL_SEED_FILENAMES:
        text = (seed_dir / name).read_text(encoding="utf-8")
        match = _FM_RX.match(text)
        assert match, f"{name} sem frontmatter"
        fields: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t", "#")):
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip().strip("'\"")
        pairs[name] = (fields.get("agent_path", ""), fields.get("action", ""))
    return pairs


# --- a tabela em si -------------------------------------------------------


def test_toda_persona_dos_seeds_esta_na_tabela():
    faltando = sorted(
        {path for path, _ in _seed_pairs().values()}
        - contract.KNOWN_PERSONA_PATHS
    )
    assert not faltando, f"personas de seed fora da tabela: {faltando}"


def test_tabela_nao_tem_persona_alem_das_24():
    sobrando = sorted(
        contract.KNOWN_PERSONA_PATHS
        - {path for path, _ in _seed_pairs().values()}
    )
    assert not sobrando, f"personas na tabela sem seed correspondente: {sobrando}"


def test_toda_categoria_declarada_tem_acoes():
    orfas = sorted(
        set(contract.PERSONA_CATEGORIES.values())
        - set(contract.PERSONA_CATEGORY_ACTIONS)
    )
    assert not orfas, f"categorias sem conjunto de actions: {orfas}"


def test_toda_categoria_definida_e_usada():
    """Categoria sem persona e vocabulario morto e vira convite a chute."""
    nao_usadas = sorted(
        set(contract.PERSONA_CATEGORY_ACTIONS)
        - set(contract.PERSONA_CATEGORIES.values())
    )
    assert not nao_usadas, f"categorias definidas e nunca usadas: {nao_usadas}"


def test_funcao_e_pura_nao_toca_disco(monkeypatch):
    """Nao pode ler arquivo: o gate roda no submit do gear, sem I/O."""

    def _bomba(*_args, **_kwargs):
        raise AssertionError("validate_persona_action tocou o disco")

    monkeypatch.setattr(Path, "open", _bomba)
    monkeypatch.setattr(Path, "read_text", _bomba)
    monkeypatch.setattr(Path, "is_file", _bomba)
    for path, actions in contract.PERSONA_ACTION_COHERENCE.items():
        assert contract.validate_persona_action(path, next(iter(actions))) is None


# --- os tres pares que A7 mediu ------------------------------------------


@pytest.mark.parametrize(
    "persona,action_atual,trecho_da_nuance",
    [
        (
            "ai-forge/MCP/agents/questioner-rules.md",
            "Revisar",  # a action que o seed carregava antes da Task 20
            "persistencia padrao como sintese final",
        ),
        (
            "ai-forge/MCP/agents/analista-delegador-rules.md",
            "Otimizar",
            "atribui toda producao tecnica aos agentes delegados",
        ),
        (
            "ai-forge/MCP/agents/scaffolds-blueprints-updater.md",
            "Otimizar",
            "restricao e de DESTINO, nao de mutacao",
        ),
    ],
)
def test_os_tres_pares_incoerentes_sao_reprovados(
    persona, action_atual, trecho_da_nuance
):
    razao = contract.validate_persona_action(persona, action_atual)
    assert razao is not None, f"{persona} + {action_atual} passou e nao devia"
    assert trecho_da_nuance in razao, (
        "a reprovacao precisa citar a nuance medida, nao so dizer 'incoerente';\n"
        f"esperado conter: {trecho_da_nuance!r}\nrecebido: {razao!r}"
    )


def test_as_tres_nuances_permanecem_distintas():
    """Achatar as tres em 'nao escreve' seria exagerar o veredito de A7."""
    textos = list(contract.PERSONA_ACTION_NUANCES.values())
    assert len(set(textos)) == len(textos) == 3


def test_cada_nuance_cita_a_linha_que_a_sustenta():
    for persona, texto in contract.PERSONA_ACTION_NUANCES.items():
        assert re.search(r"\.md:\d+", texto), (
            f"nuance de {persona} nao cita arquivo:linha: {texto!r}"
        )


# --- os 21 restantes ------------------------------------------------------


def test_os_demais_pares_do_disco_sao_aprovados():
    pares = _seed_pairs()
    reprovados = {
        name
        for name, (persona, action) in pares.items()
        if contract.validate_persona_action(persona, action) is not None
    }
    assert reprovados == set(SEEDS_COM_PAR_PENDENTE), (
        "o conjunto de seeds com par incoerente mudou;\n"
        f"esperado: {sorted(SEEDS_COM_PAR_PENDENTE)}\n"
        f"medido:   {sorted(reprovados)}"
    )
    assert len(pares) == contract.CANONICAL_SEED_COUNT


# --- a troca de persona ---------------------------------------------------


def test_trocar_a_persona_por_outra_de_categoria_diferente_reprova():
    """O criterio de aceite literal da Task 18.

    `01-criar-md.md` dispara `Criar arquivo`. Trocada a persona por
    `code-debugger` (categoria `enricher`), a action nao muda e o par tem de
    cair mesmo assim -- e isso que separa "validar a action" de "validar o
    par".
    """
    assert (
        contract.validate_persona_action(
            "ai-forge/MCP/agents/criar-md-rules.md", "Criar arquivo"
        )
        is None
    )
    razao = contract.validate_persona_action(
        "ai-forge/MCP/agents/code-debugger.md", "Criar arquivo"
    )
    assert razao is not None
    assert "enricher" in razao


def test_troca_dentro_da_mesma_categoria_continua_aprovada():
    """A tabela julga categoria, nao identidade: o falso positivo simetrico.

    `ux-ui-specialist` e `performance-engineer` sao duas personas `reviewer`
    distintas. Trocar uma pela outra nao e um erro que ESTA tabela saiba ver,
    e o teste registra esse limite em vez de deixar alguem supor cobertura
    que nao existe.
    """
    for persona in (
        "ai-forge/MCP/agents/ux-ui-specialist.md",
        "ai-forge/MCP/agents/performance-engineer.md",
    ):
        assert contract.validate_persona_action(persona, "Revisar") is None


def test_a_chave_e_o_path_nao_o_slug():
    """Chave por slug faria fixture sintetica passar por acidente (D-C6).

    O nome do seed `22-scaffolds-blueprints-updater.md` coincide com o da
    persona; o do seed `19-delegador.md` nao coincide. Se a chave fosse
    derivada do nome do seed, o primeiro caso passaria por coincidencia e o
    segundo nunca seria encontrado.
    """
    assert "scaffolds-blueprints-updater.md" not in contract.PERSONA_ACTION_COHERENCE
    assert "19-delegador.md" not in contract.PERSONA_ACTION_COHERENCE
    assert all(
        key.startswith("ai-forge/MCP/agents/")
        for key in contract.PERSONA_ACTION_COHERENCE
    )


def test_persona_desconhecida_se_abstem_e_e_distinguivel():
    """Abster nao pode ser confundido com aprovar."""
    nova = "ai-forge/MCP/agents/persona-que-ninguem-mediu.md"
    assert nova not in contract.KNOWN_PERSONA_PATHS
    assert contract.validate_persona_action(nova, "Otimizar") is None
    assert contract.validate_persona_action(nova, "acao inexistente") is None


def test_path_com_barra_invertida_ou_prefixo_ponto_normaliza():
    assert (
        contract.validate_persona_action(
            "./ai-forge/MCP/agents/code-debugger.md", "Otimizar"
        )
        is None
    )
    assert (
        contract.validate_persona_action(
            "  ai-forge/MCP/agents/code-debugger.md  ", "  Otimizar  "
        )
        is None
    )


def test_tabelas_sao_imutaveis():
    for tabela in (
        contract.PERSONA_CATEGORIES,
        contract.PERSONA_CATEGORY_ACTIONS,
        contract.PERSONA_ACTION_NUANCES,
        contract.PERSONA_ACTION_COHERENCE,
    ):
        with pytest.raises(TypeError):
            tabela["x"] = "y"  # type: ignore[index]


def test_os_tres_seeds_trocados_passam_no_gate_com_a_action_nova():
    """Fechamento da Task 20: a troca resolveu o par, nao so mudou o rotulo."""
    pares = _seed_pairs()
    esperado = {
        "07-questioner.md": "Questionar",
        "19-delegador.md": "Delegar",
        "22-scaffolds-blueprints-updater.md": "Atualizar scaffolds e blueprints",
    }
    for name, action_nova in esperado.items():
        persona, action = pares[name]
        assert action == action_nova, f"{name} ainda com action {action!r}"
        assert contract.validate_persona_action(persona, action) is None


def test_as_3_copias_da_lista_de_actions_concordam():
    """Aceite da Task 20, medido nas fontes que sobraram depois da Task 29.

    Eram QUATRO copias; a Task 29 aposentou a quarta (`ActionType`, que era um
    `Literal` de 15 membros) abrindo o tipo para `str`. As tres restantes
    continuam sem poder importar umas as outras sem criar ciclo -- o contrato
    e puro, os widgets sao Qt -- entao este teste e o que as mantem iguais.
    """
    from workflow_app.widgets.brainstorm_mcp_config_dialog import ACTION_COHERENCE
    from workflow_app.widgets.mcp_prompt_actions import ACTION_LITERALS
    from workflow_app.widgets.mcp_prompt_button import VALID_ACTIONS_PTBR

    assert set(ACTION_LITERALS) == set(ACTION_COHERENCE)
    assert set(ACTION_LITERALS) == set(VALID_ACTIONS_PTBR)
    assert {
        "Questionar",
        "Delegar",
        "Atualizar scaffolds e blueprints",
    } <= set(ACTION_LITERALS)


def test_actiontype_esta_aberto():
    """Task 29: fechar o tipo era exigir edicao de Python por action nova.

    Guarda contra a reintroducao do `Literal`, que voltaria a criar a quarta
    copia sem que nenhum teste de paridade a alcancasse (um `Literal` so
    existe para o type checker; em runtime nao ha o que comparar).
    """
    from workflow_app.widgets import mcp_prompt_button

    assert mcp_prompt_button.ActionType is str
    assert not hasattr(mcp_prompt_button.ActionType, "__args__")


def test_toda_action_aceita_pela_tabela_existe_no_vocabulario():
    """A tabela G7 nao pode exigir uma action que nenhum combo oferece."""
    from workflow_app.widgets.mcp_prompt_actions import ACTION_LITERALS

    exigidas = {
        action
        for actions in contract.PERSONA_CATEGORY_ACTIONS.values()
        for action in actions
    }
    inexistentes = sorted(exigidas - set(ACTION_LITERALS))
    assert not inexistentes, f"tabela G7 exige action inexistente: {inexistentes}"

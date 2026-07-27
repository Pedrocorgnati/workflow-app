"""Testes focais da fonte unica de specs suplementares (AGENT-TASK-006).

Cobre: modelo tipado, validacao de campo, unicidade (slug/testid/action),
ausencia de efeito colateral no import e as APIs de leitura consumidas pelos
caminhos de build e rebuild.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from workflow_app.agent_integration_specs import (
    BRAINSTORM_TESTID_PREFIX,
    CODEX_TARGET_TERMINAL,
    DEFAULT_TARGET_TERMINAL,
    MCP_TESTID_PREFIX,
    SUPPORTED_ACTIONS,
    AgentIntegrationSpecError,
    BrainstormAgentSpec,
    McpAgentSpec,
    assert_no_seed_slug_collision,
    assert_no_testid_collision,
    brainstorm_agent_specs,
    brainstorm_button_kwargs,
    find_brainstorm_agent_spec,
    find_mcp_agent_spec,
    mcp_agent_specs,
    registry_testids,
    supported_actions,
    validate_action,
    validate_registry,
    validate_repo_relative_md,
    validate_slug,
)
from workflow_app.widgets.mcp_prompt_actions import ACTION_LITERALS
from workflow_app.widgets.mcp_prompt_button import (
    VALID_ACTIONS,
    VALID_BUTTON_TYPES,
    VALID_TERMINALS,
)

_AN_ACTION = "Otimizar"


def _mcp_spec(slug: str = "hardening-engineer") -> McpAgentSpec:
    return McpAgentSpec(
        slug=slug,
        label="hardening",
        directive=(
            "no papel de hardening engineer, conforme regras em "
            "ai-forge/MCP/agents/hardening-engineer-rules.md"
        ),
    )


def _brainstorm_spec(slug: str = "hardening-engineer", **over) -> BrainstormAgentSpec:
    base = dict(
        slug=slug,
        label="hardening",
        button_type="type-selector-radio-input",
        action=_AN_ACTION,
        agent_name="hardening engineer",
        agent_path="ai-forge/MCP/agents/hardening-engineer-rules.md",
        prompt_path="blacksmith/brainstorm-mcp/07-24-criacao-de-agentes.md",
    )
    base.update(over)
    return BrainstormAgentSpec(**base)


# ── Import inerte / ausencia de mutacao global ───────────────────────────────


def test_import_nao_muta_catalogos_de_origem():
    """Importar o modulo nao altera VALID_ACTIONS/BUTTON_TYPES/TERMINALS."""
    import workflow_app.agent_integration_specs as mod

    assert VALID_ACTIONS == {"send", "queue", "config"} | {
        "Criar arquivo",
        "Otimizar",
        "Criar tasks",
        "Revisar tasks",
        "Revisar",
        "Executar",
        "Revisar execucao",
        "Loop prepare",
        "Analisar complexidade",
    }
    assert "Otimizar" in ACTION_LITERALS
    assert mod.VALID_BUTTON_TYPES_FROZEN == frozenset(VALID_BUTTON_TYPES)
    assert mod.VALID_TERMINALS_FROZEN == frozenset(VALID_TERMINALS)
    # Copias defensivas: mutar o frozenset e impossivel, e o set de origem
    # continua sendo o objeto canonico do widget.
    assert isinstance(mod.VALID_BUTTON_TYPES_FROZEN, frozenset)
    assert isinstance(mod.SUPPORTED_ACTIONS, frozenset)


def test_import_frio_nao_escreve_no_disco(tmp_path):
    """Import FRIO do modulo, em cwd temporario, nao cria nem le arquivos.

    Roda em subprocesso limpo de proposito (finding 008 W1). A versao anterior
    deste teste apagava a entrada de `sys.modules` e reimportava dentro da
    sessao de teste: isso nao e import frio (o pacote pai `workflow_app` e
    tudo que ele ja importou continuavam quentes) e ainda era destrutivo — as
    suites que seguram o objeto ANTIGO no topo do arquivo passavam a divergir
    do objeto NOVO resolvido pelo codigo de producao, e a identidade de
    `AgentIntegrationSpecError` deixava de bater no `except`.

    Interpretador novo com `cwd=tmp_path` prova a propriedade de verdade: se o
    modulo tivesse efeito colateral de disco (ler um JSON de registry, criar
    cache, tocar um lockfile), o diretorio nao ficaria vazio.
    """
    script = (
        "import os, sys\n"
        "from workflow_app.agent_integration_specs import mcp_agent_specs\n"
        "from workflow_app.agent_integration_specs import brainstorm_agent_specs\n"
        "assert mcp_agent_specs() == (), mcp_agent_specs()\n"
        "assert brainstorm_agent_specs() == (), brainstorm_agent_specs()\n"
        "print(os.listdir('.'))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", proc.stdout
    assert list(Path(tmp_path).iterdir()) == []


def test_registry_vazio_por_default_e_imutavel():
    """Sem agente registrado, os dois registries sao tuplas vazias."""
    assert mcp_agent_specs() == ()
    assert brainstorm_agent_specs() == ()
    assert isinstance(mcp_agent_specs(), tuple)
    assert isinstance(brainstorm_agent_specs(), tuple)
    assert registry_testids() == ()


def test_leitura_repetida_e_deterministica():
    """Chamar duas vezes devolve o mesmo valor (leitura sem efeito colateral)."""
    assert mcp_agent_specs() == mcp_agent_specs()
    assert brainstorm_agent_specs() == brainstorm_agent_specs()
    assert supported_actions() == supported_actions()
    assert supported_actions() == tuple(sorted(SUPPORTED_ACTIONS))


# ── Modelo tipado ────────────────────────────────────────────────────────────


def test_mcp_spec_testid_e_persona_prompt():
    spec = _mcp_spec()
    assert spec.testid == f"{MCP_TESTID_PREFIX}hardening-engineer"
    assert spec.persona_prompt == spec.directive
    assert "hardening-engineer-rules.md" in spec.persona_prompt


def test_brainstorm_spec_testid_e_terminal_default():
    spec = _brainstorm_spec()
    assert spec.testid == f"{BRAINSTORM_TESTID_PREFIX}hardening-engineer"
    assert spec.resolved_target_terminal == DEFAULT_TARGET_TERMINAL


def test_brainstorm_spec_codex_resolve_terminal_codex():
    spec = _brainstorm_spec(
        button_type="Codex", target_terminal=CODEX_TARGET_TERMINAL
    )
    assert spec.resolved_target_terminal == CODEX_TARGET_TERMINAL


def test_brainstorm_spec_codex_com_terminal_errado_e_recusada():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        _brainstorm_spec(
            button_type="Codex", target_terminal="terminal-workspace-output"
        )
    assert exc.value.field == "target_terminal"


def test_specs_sao_frozen():
    spec = _mcp_spec()
    with pytest.raises(Exception):
        spec.slug = "outro"  # type: ignore[misc]


# ── Validacao de campo ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_slug",
    ["", "   ", "Hardening", "hardening_engineer", "-hardening", "hardening-",
     "hardening--engineer", "hardening engineer", "a" * 65],
)
def test_slug_invalido_recusado(bad_slug):
    with pytest.raises(AgentIntegrationSpecError):
        validate_slug(bad_slug)


def test_slug_valido_normalizado():
    assert validate_slug("  hardening-engineer  ") == "hardening-engineer"


@pytest.mark.parametrize("bad_action", ["", "   ", "Inexistente", "send", None])
def test_action_ausente_ou_invalida_recusada(bad_action):
    """Action fora da interseccao VALID_ACTIONS x ACTION_LITERALS e recusada."""
    with pytest.raises(AgentIntegrationSpecError):
        validate_action(bad_action)


def test_action_legacy_nao_e_suportada():
    """Legacy send/queue/config existem no widget mas nao em ACTION_LITERALS."""
    assert {"send", "queue", "config"}.isdisjoint(SUPPORTED_ACTIONS)
    assert SUPPORTED_ACTIONS == frozenset(VALID_ACTIONS) & frozenset(
        ACTION_LITERALS.keys()
    )


def test_action_suportada_aceita():
    assert validate_action(_AN_ACTION) == _AN_ACTION


@pytest.mark.parametrize(
    "bad_path",
    [
        "/ai-forge/MCP/agents/x.md",
        "../fora-do-repo.md",
        "ai-forge/../../x.md",
        "ai-forge\\MCP\\agents\\x.md",
        "ai-forge/MCP/agents/TODO.md",
        "ai-forge/MCP/agents/x.txt",
        "",
    ],
)
def test_path_relativo_invalido_recusado(bad_path):
    with pytest.raises(AgentIntegrationSpecError):
        validate_repo_relative_md(bad_path, field_name="agent_path")


def test_path_relativo_valido_normalizado():
    got = validate_repo_relative_md(
        " ai-forge/MCP/agents/x.md ", field_name="agent_path"
    )
    assert got == "ai-forge/MCP/agents/x.md"


def test_button_type_invalido_recusado():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        _brainstorm_spec(button_type="Gemini")
    assert exc.value.field == "button_type"


def test_target_terminal_invalido_recusado():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        _brainstorm_spec(target_terminal="terminal-inexistente")
    assert exc.value.field == "target_terminal"


def test_label_com_control_char_recusado():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        _mcp_spec_label_invalido()
    assert exc.value.field == "label"


def _mcp_spec_label_invalido() -> McpAgentSpec:
    return McpAgentSpec(
        slug="hardening-engineer",
        label="harden​ing",
        directive="no papel de hardening engineer",
    )


def test_directive_com_segredo_recusada():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        McpAgentSpec(
            slug="hardening-engineer",
            label="hardening",
            directive="use a chave sk-abcdefghijklmnopqrstuvwx",
        )
    assert exc.value.field == "directive"


def test_erro_nunca_ecoa_valor_sensivel():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        McpAgentSpec(
            slug="hardening-engineer",
            label="hardening",
            directive="Bearer abcdefghijkl",
        )
    assert "abcdefghijkl" not in str(exc.value)


# ── Unicidade ────────────────────────────────────────────────────────────────


def test_slug_duplicado_no_mesmo_destino_recusado():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        validate_registry([_mcp_spec(), _mcp_spec()], [])
    assert exc.value.field == "slug"

    with pytest.raises(AgentIntegrationSpecError):
        validate_registry([], [_brainstorm_spec(), _brainstorm_spec()])


def test_mesmo_slug_nos_dois_destinos_e_permitido():
    """Um agente pode ter integracao MCP e Brainstorm: testids tem prefixos."""
    validate_registry([_mcp_spec("x-agent")], [_brainstorm_spec("x-agent")])
    testids = registry_testids([_mcp_spec("x-agent")], [_brainstorm_spec("x-agent")])
    assert testids == (
        f"{MCP_TESTID_PREFIX}x-agent",
        f"{BRAINSTORM_TESTID_PREFIX}x-agent",
    )
    assert len(set(testids)) == 2


def test_testid_duplicado_recusado():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        assert_no_testid_collision(
            [f"{MCP_TESTID_PREFIX}x-agent"], [_mcp_spec("x-agent")], []
        )
    assert exc.value.field == "testid"


def test_testid_sem_colisao_passa():
    assert_no_testid_collision(
        ["output-mcp-persona-executor", "mcp-prompt-btn-criar-md"],
        [_mcp_spec("x-agent")],
        [_brainstorm_spec("x-agent")],
    )


def test_colisao_com_seed_canonico_recusada():
    with pytest.raises(AgentIntegrationSpecError) as exc:
        assert_no_seed_slug_collision(
            ["criar-md", "search-in"], [_brainstorm_spec("criar-md")]
        )
    assert exc.value.field == "slug"


def test_sem_colisao_com_seeds_passa():
    assert_no_seed_slug_collision(
        ["criar-md", "search-in"], [_brainstorm_spec("hardening-engineer")]
    )


def test_registry_recusa_tipo_errado():
    with pytest.raises(AgentIntegrationSpecError):
        validate_registry([object()], [])  # type: ignore[list-item]
    with pytest.raises(AgentIntegrationSpecError):
        validate_registry([], [_mcp_spec()])  # type: ignore[list-item]


# ── APIs de leitura para build e rebuild ─────────────────────────────────────


def test_find_por_slug_devolve_none_quando_ausente():
    assert find_mcp_agent_spec("inexistente") is None
    assert find_brainstorm_agent_spec("inexistente") is None


def test_button_kwargs_casam_com_a_assinatura_do_widget():
    from workflow_app.widgets.mcp_prompt_button import MCPPromptButton

    spec = _brainstorm_spec()
    kwargs = brainstorm_button_kwargs(spec)
    import inspect

    params = set(inspect.signature(MCPPromptButton.__init__).parameters)
    assert set(kwargs).issubset(params)
    assert kwargs["testid_slug"] == spec.slug
    assert kwargs["action"] == _AN_ACTION
    assert kwargs["target_path"] == DEFAULT_TARGET_TERMINAL
    assert kwargs["prompt"] == spec.prompt_path
    assert "radio_state_getter" not in kwargs


def test_button_kwargs_com_repo_root_resolve_prompt_sem_tocar_disco(tmp_path):
    spec = _brainstorm_spec()
    kwargs = brainstorm_button_kwargs(spec, repo_root=tmp_path)
    assert kwargs["prompt"] == tmp_path / spec.prompt_path
    assert not (tmp_path / spec.prompt_path).exists()


def test_button_kwargs_repassa_radio_state_getter():
    def getter() -> str:
        return "Claude"

    kwargs = brainstorm_button_kwargs(_brainstorm_spec(), radio_state_getter=getter)
    assert kwargs["radio_state_getter"] is getter


def test_button_kwargs_build_e_rebuild_sao_identicos():
    """Mesma spec produz kwargs identicos: build inicial == rebuild do grid."""
    spec = _brainstorm_spec()
    assert brainstorm_button_kwargs(spec) == brainstorm_button_kwargs(spec)


def test_button_kwargs_recusa_objeto_estranho():
    with pytest.raises(AgentIntegrationSpecError):
        brainstorm_button_kwargs(_mcp_spec())  # type: ignore[arg-type]

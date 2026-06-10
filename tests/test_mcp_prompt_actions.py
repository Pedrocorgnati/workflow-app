"""Testes de literais canonicos e template hardened (T5).

Cobre 4 cenarios do T5 (loop 05-21-implantation-tasklist-aba-brainstorm):
- test_action_literals_count_and_keys: 7 literais canonicos (label -> texto).
- test_hardened_template_renders_correctly: TEMPLATE_HARDENED com substituicao
  byte-a-byte dos 4 placeholders + clausula anti-injection.
- test_build_prompt_raises_for_invalid_action: ValueError em action fora
  do catalogo de `ACTION_LITERALS`.
- test_build_prompt_appends_second_phase: bloco _AGENT2_TEMPLATE quando
  agent2_* + action2 presentes na seed_meta.

Hardening T9 §2: usa `importorskip` para evitar zona morta xfail enquanto
T5 nao entregar o modulo.
"""

from __future__ import annotations

import pytest

pytest.importorskip("workflow_app.widgets.mcp_prompt_actions")

pytestmark = pytest.mark.timeout(5)

from pathlib import Path

from workflow_app.widgets.mcp_prompt_actions import (
    ACTION_LITERALS,
    PROMPT_TEMPLATE_VERSION,
    TEMPLATE_HARDENED,
    TEMPLATE_SHORT,
    build_prompt,
)


_EXPECTED_KEYS = frozenset(
    {
        "Otimizar",
        "Criar tasks",
        "Revisar tasks",
        "Executar",
        "Revisar execucao",
        "Criar arquivo",
        "Loop prepare",
    }
)


def test_action_literals_count_and_keys():
    """ACTION_LITERALS expoe exatamente os 7 labels canonicos (pt-BR).

    Cada literal e str nao-vazio e PROMPT_TEMPLATE_VERSION e versao
    semantic (date-based) usada para invalidar snapshots golden.
    """
    assert set(ACTION_LITERALS.keys()) == _EXPECTED_KEYS
    assert len(ACTION_LITERALS) == 7
    for k, v in ACTION_LITERALS.items():
        assert isinstance(v, str) and v.strip(), f"{k}: literal vazio"
    assert isinstance(PROMPT_TEMPLATE_VERSION, str)
    assert PROMPT_TEMPLATE_VERSION


def test_hardened_template_renders_correctly(tmp_path):
    """build_prompt com target_path=True usa TEMPLATE_HARDENED.

    Validacoes:
    - Substituicao byte-a-byte de {target-path}, {agent-name}, {agent-path},
      {action}.
    - Bloco anti-injection ("INSTRUCOES DO SISTEMA" + clausula de
      precedencia) presente.
    - agent_path normalizado para POSIX (slash forward).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    md_path = "blacksmith/brainstorm-mcp/01-criar-md.md"
    seed_meta = {
        "agent_name": "Estruturador",
        "agent_path": "ai-forge\\MCP\\agents\\criar-md.md",
        "action": "Otimizar",
        "target_path": True,
    }
    out = build_prompt(seed_meta, md_path, repo_root)
    assert "INSTRUCOES DO SISTEMA" in out
    assert "Estruturador" in out
    # POSIX normalization:
    assert "ai-forge/MCP/agents/criar-md.md" in out
    assert "\\" not in out
    # md_path injetado em {target-path}:
    assert md_path in out
    # Literal canonico (Otimizar) injetado:
    assert ACTION_LITERALS["Otimizar"] in out
    # Spot-check do template base:
    assert "{target-path}" not in out
    assert "{action}" not in out


def test_loop_prepare_action_targets_queue_loop(tmp_path):
    """Loop prepare explica o handoff para queue-btn-loop sem executar /loop."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    md_path = "blacksmith/brainstorm-mcp/06-03-plano.md"
    seed_meta = {
        "agent_name": "Preparador",
        "agent_path": "ai-forge/MCP/agents/loop-preparer-rules.md",
        "action": "Loop prepare",
        "target_path": True,
    }
    out = build_prompt(seed_meta, md_path, repo_root)
    assert 'data-testid="queue-btn-loop"' in out
    assert "ai-forge/rules/loop-rules.md" in out
    assert "/loop --task" in out
    assert "/loop --cmd" in out
    assert "/loop --both" in out
    assert "sem executar /loop" in out
    assert "_LOOP-CONFIG.json" in out


def test_build_prompt_raises_for_invalid_action(tmp_path):
    """Action fora de ACTION_LITERALS levanta ValueError byte-a-byte."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seed_meta = {
        "agent_name": "x",
        "agent_path": "agents/x.md",
        "action": "NaoExiste",
        "target_path": False,
    }
    with pytest.raises(ValueError, match="action invalida"):
        build_prompt(seed_meta, None, repo_root)


def test_build_prompt_appends_second_phase(tmp_path):
    """seed_meta com agent2_* + action2 anexa bloco de segunda fase.

    O bloco _AGENT2_TEMPLATE e adicionado APOS o template principal
    (hardened ou short) com `agent2_path` validado anti-traversal
    contra `repo_root`.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    agent2 = repo_root / "agents" / "phase2.md"
    agent2.parent.mkdir(parents=True)
    agent2.write_text("# phase 2 rules\n", encoding="utf-8")
    seed_meta = {
        "agent_name": "Phase1Agent",
        "agent_path": "agents/phase1.md",
        "action": "Criar arquivo",
        "target_path": False,
        "agent2_name": "Phase2Agent",
        "agent2_path": "agents/phase2.md",
        "action2": "Loop prepare",
    }
    out = build_prompt(seed_meta, None, repo_root)
    # Primeira fase (TEMPLATE_SHORT).
    assert "Phase1Agent" in out
    assert ACTION_LITERALS["Criar arquivo"] in out
    # Segunda fase (anexada apos `---`).
    assert "Phase2Agent" in out
    assert ACTION_LITERALS["Loop prepare"] in out
    assert out.count("---") >= 1
    # Sanity: ambos templates importados (smoke do contrato do modulo).
    assert isinstance(TEMPLATE_HARDENED, str) and TEMPLATE_HARDENED
    assert isinstance(TEMPLATE_SHORT, str) and TEMPLATE_SHORT

"""Unit tests for MCPPromptButton (loop 05-20-mcp-flow-implantation, P1).

Uses pytest-qt for Qt fixtures. Standalone widget — does NOT touch main_window.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from workflow_app.widgets.mcp_prompt_button import (
    MCPPromptButton,
    MCPPromptConfigModal,
)


# ── 1. Creation with valid args ───────────────────────────────────────────


def test_creation_valid_args(qtbot):
    """MCPPromptButton aceita args canonicos para os 3 button_types."""
    btn_claude = MCPPromptButton(
        label="Claude · Send",
        button_type="Claude",
        prompt="Resuma o diff.",
        action="send",
        target_path="terminal-interactive-output",
    )
    qtbot.addWidget(btn_claude)
    assert btn_claude.text() == "Claude · Send"
    assert btn_claude.property("testid") == "mcp-prompt-button-claude"
    assert btn_claude.payload()["button_type"] == "Claude"

    btn_codex = MCPPromptButton(
        label="Codex · Review",
        button_type="Codex",
        prompt="Adversarial review.",
        action="queue",
        target_path="terminal-codex-output",
    )
    qtbot.addWidget(btn_codex)
    assert btn_codex.property("testid") == "mcp-prompt-button-codex"

    btn_kimi = MCPPromptButton(
        label="Kimi · Pair",
        button_type="Kimi",
        prompt="Pair analyse.",
        action="config",
        target_path="terminal-workspace-output",
    )
    qtbot.addWidget(btn_kimi)
    assert btn_kimi.property("testid") == "mcp-prompt-button-kimi"


# ── 2. Validation: Codex requires terminal-codex-output ───────────────────


def test_validation_codex_requires_terminal_codex_output(qtbot):
    """button_type=Codex sem terminal-codex-output deve raise ValueError."""
    with pytest.raises(ValueError, match="Codex.*terminal-codex-output"):
        MCPPromptButton(
            label="Bad Codex",
            button_type="Codex",
            prompt="x",
            action="send",
            target_path="terminal-interactive-output",
        )

    with pytest.raises(ValueError, match="Codex.*terminal-codex-output"):
        MCPPromptButton(
            label="Bad Codex 2",
            button_type="Codex",
            prompt="x",
            action="send",
            target_path=None,
        )

    # invalid type
    with pytest.raises(ValueError, match="button_type"):
        MCPPromptButton(
            label="x",
            button_type="Gemini",  # type: ignore[arg-type]
            prompt="x",
            action="send",
            target_path="terminal-interactive-output",
        )


# ── 3. Signal emitted on click ────────────────────────────────────────────


def test_signal_emitted_on_click(qtbot):
    """Left-click emite `prompt_requested` com payload canonico."""
    btn = MCPPromptButton(
        label="Click me",
        button_type="Claude",
        prompt="hello world",
        action="send",
        target_path="terminal-interactive-output",
    )
    qtbot.addWidget(btn)

    with qtbot.waitSignal(btn.prompt_requested, timeout=1000) as blocker:
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    payload = blocker.args[0]
    assert isinstance(payload, dict)
    assert payload["label"] == "Click me"
    assert payload["button_type"] == "Claude"
    assert payload["prompt_text"] == "hello world"
    assert payload["action"] == "send"
    assert payload["target_path"] == "terminal-interactive-output"


# ── 4. Modal opens on right-click ─────────────────────────────────────────


def test_modal_opens_on_right_click(qtbot, monkeypatch):
    """Right-click instancia MCPPromptConfigModal e chama exec()."""
    btn = MCPPromptButton(
        label="Configure",
        button_type="Kimi",
        prompt="initial prompt",
        action="config",
        target_path="terminal-workspace-output",
    )
    qtbot.addWidget(btn)

    exec_calls: list[MCPPromptConfigModal] = []

    def _fake_exec(self) -> int:
        exec_calls.append(self)
        return QDialog.DialogCode.Rejected  # cancela para nao mutar widget

    monkeypatch.setattr(MCPPromptConfigModal, "exec", _fake_exec)

    qtbot.mouseClick(btn, Qt.MouseButton.RightButton)

    assert len(exec_calls) == 1, "Right-click deveria abrir o modal exatamente uma vez"
    modal = exec_calls[0]
    assert isinstance(modal, MCPPromptConfigModal)
    assert modal.property("testid") == "mcp-prompt-config-modal"
    # valores iniciais devem refletir o estado do botao
    values = modal.values()
    assert values["label"] == "Configure"
    assert values["prompt"] == "initial prompt"
    assert values["target_path"] == "terminal-workspace-output"

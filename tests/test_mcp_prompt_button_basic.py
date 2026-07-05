"""Testes basicos de MCPPromptButton: rendering + signals + payload.

Cobre os criterios 3, 4 e 8 do §10.3 do mcp-flow-implantation.md (mantidos
da suite original de 4 testes em test_mcp_prompt_button.py, agora
particionada em 7 arquivos por concerno - hardening T9 §1 do loop
05-21-implantation-tasklist-aba-brainstorm).

5 testes:
- test_creation_valid_args (3 button_types canonicos)
- test_validation_codex_requires_terminal_codex_output (Codex/target invalido)
- test_validation_invalid_button_type_raises (Gemini, etc)
- test_signal_emitted_on_click_carries_payload (left-click + payload completo)
- test_modal_opens_on_right_click (right-click abre MCPPromptConfigModal)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.timeout(5)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from workflow_app.widgets.mcp_prompt_button import (
    MCPPromptButton,
    MCPPromptConfigModal,
)


def test_creation_valid_args(qtbot):
    """MCPPromptButton aceita args canonicos para os 3 button_types fixos."""
    btn_claude = MCPPromptButton(
        label="Claude Send",
        button_type="Claude",
        prompt="Resuma o diff.",
        action="send",
        target_path="terminal-interactive-output",
        testid_slug="claude-send",
    )
    qtbot.addWidget(btn_claude)
    assert btn_claude.property("testid") == "mcp-prompt-btn-claude-send"
    assert btn_claude.payload()["button_type"] == "Claude"

    btn_codex = MCPPromptButton(
        label="Codex Review",
        button_type="Codex",
        prompt="Adversarial review.",
        action="queue",
        target_path="terminal-codex-output",
        testid_slug="codex-review",
    )
    qtbot.addWidget(btn_codex)
    assert btn_codex.property("testid") == "mcp-prompt-btn-codex-review"

    btn_kimi = MCPPromptButton(
        label="Kimi Pair",
        button_type="Kimi",
        prompt="Pair analyse.",
        action="config",
        target_path="terminal-workspace-output",
        testid_slug="kimi-pair",
    )
    qtbot.addWidget(btn_kimi)
    assert btn_kimi.property("testid") == "mcp-prompt-btn-kimi-pair"


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


def test_validation_invalid_button_type_raises(qtbot):
    """button_type fora do catalogo canonico levanta ValueError."""
    with pytest.raises(ValueError, match="button_type"):
        MCPPromptButton(
            label="Bad",
            button_type="Gemini",  # type: ignore[arg-type]
            prompt="x",
            action="send",
            target_path="terminal-interactive-output",
        )


def test_signal_emitted_on_click_carries_payload(qtbot, codex_alive_factory):
    """Left-click emite `prompt_requested` com payload canonico completo.

    O payload inclui button_id (para roteamento de dispatch_result),
    label, button_type, prompt_text, action, target_path e testid_slug.
    """
    # Garantir que botoes Codex nao sao avaliados aqui (Claude apenas).
    codex_alive_factory(True)
    btn = MCPPromptButton(
        label="Click me",
        button_type="Claude",
        prompt="hello world",
        action="send",
        target_path="terminal-interactive-output",
        testid_slug="click-me",
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
    assert payload["testid_slug"] == "click-me"
    assert payload["button_id"] == "mcp-prompt-btn-click-me"


def test_modal_opens_on_right_click(qtbot, monkeypatch):
    """Right-click instancia MCPPromptConfigModal e chama exec()."""
    btn = MCPPromptButton(
        label="Configure",
        button_type="Kimi",
        prompt="initial prompt",
        action="config",
        target_path="terminal-workspace-output",
        testid_slug="cfg",
    )
    qtbot.addWidget(btn)

    exec_calls: list[MCPPromptConfigModal] = []

    def _fake_exec(self) -> int:
        exec_calls.append(self)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(MCPPromptConfigModal, "exec", _fake_exec)

    # O modal abre via `contextMenuEvent` (DefaultContextMenu policy). Sob a
    # plataforma `offscreen`, qtbot.mouseClick(RightButton) NAO sintetiza um
    # QContextMenuEvent (verificado: 0 disparos), entao entregamos o evento
    # diretamente — e o caminho real que o handler trata em producao.
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication

    _pos = QPoint(btn.width() // 2, btn.height() // 2)
    _ctx_event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, _pos, btn.mapToGlobal(_pos)
    )
    QApplication.sendEvent(btn, _ctx_event)

    assert len(exec_calls) == 1
    modal = exec_calls[0]
    assert isinstance(modal, MCPPromptConfigModal)
    assert modal.property("testid") == "mcp-prompt-config-modal"
    values = modal.values()
    assert values["label"] == "Configure"
    assert values["prompt"] == "initial prompt"
    assert values["target_path"] == "terminal-workspace-output"

"""
MCPPromptButton — Botao canonico para disparo de prompts MCP (Claude / Codex / Kimi).

Uso (STANDALONE, ainda nao wired ao main_window):
    btn = MCPPromptButton(
        label="Analyse",
        button_type="Claude",
        prompt="Analise o codigo no diff atual.",
        action="send",
        target_path="terminal-interactive-output",
    )
    btn.prompt_requested.connect(lambda payload: print(payload))

Comportamento:
- Left-click: emite `prompt_requested(dict)` com label/type/prompt/action/target_path/agent.
- Right-click: abre `MCPPromptConfigModal` (edicao inline da config).
- Cor de fundo varia por type (Claude=azul, Codex=verde, Kimi=roxo).
- Validacao no __init__: type="Codex" exige target_path="terminal-codex-output".
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
)

ButtonType = Literal["Claude", "Codex", "Kimi"]
ActionType = Literal["send", "queue", "config"]

_TYPE_BG: dict[str, str] = {
    "Claude": "#BFDBFE",  # azul claro
    "Codex":  "#BBF7D0",  # verde claro
    "Kimi":   "#DDD6FE",  # roxo claro
}
_TYPE_FG: dict[str, str] = {
    "Claude": "#1E3A8A",
    "Codex":  "#14532D",
    "Kimi":   "#4C1D95",
}

_VALID_TARGETS: set[str] = {
    "terminal-interactive-output",
    "terminal-workspace-output",
    "terminal-codex-output",
}


class MCPPromptConfigModal(QDialog):
    """Modal de edicao da config do botao MCP (right-click)."""

    def __init__(
        self,
        parent: QPushButton | None = None,
        *,
        label: str = "",
        prompt: str = "",
        agent_name: str | None = None,
        agent_path: str | None = None,
        target_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar MCP Prompt Button")
        self.setProperty("testid", "mcp-prompt-config-modal")

        form = QFormLayout(self)
        self._label_edit = QLineEdit(label, self)
        self._prompt_edit = QPlainTextEdit(prompt, self)
        self._prompt_edit.setMinimumHeight(120)
        self._agent_name_edit = QLineEdit(agent_name or "", self)
        self._agent_path_edit = QLineEdit(agent_path or "", self)
        self._target_edit = QLineEdit(target_path or "", self)

        form.addRow("Label:", self._label_edit)
        form.addRow("Prompt:", self._prompt_edit)
        form.addRow("Agent name:", self._agent_name_edit)
        form.addRow("Agent path:", self._agent_path_edit)
        form.addRow("Target terminal:", self._target_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, str]:
        return {
            "label": self._label_edit.text(),
            "prompt": self._prompt_edit.toPlainText(),
            "agent_name": self._agent_name_edit.text() or "",
            "agent_path": self._agent_path_edit.text() or "",
            "target_path": self._target_edit.text() or "",
        }


class MCPPromptButton(QPushButton):
    """Botao canonico para disparo de prompts MCP."""

    prompt_requested = Signal(dict)

    def __init__(
        self,
        label: str,
        button_type: ButtonType,
        prompt: str | Path,
        agent_name: str | None = None,
        agent_path: str | None = None,
        action: ActionType = "send",
        target_path: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(label, parent)

        # ── Validacao ────────────────────────────────────────────────────
        if button_type not in _TYPE_BG:
            raise ValueError(
                f"button_type invalido: {button_type!r} (esperado: Claude|Codex|Kimi)"
            )
        if action not in ("send", "queue", "config"):
            raise ValueError(
                f"action invalida: {action!r} (esperado: send|queue|config)"
            )
        if target_path is not None and target_path not in _VALID_TARGETS:
            raise ValueError(
                f"target_path invalido: {target_path!r}. "
                f"Esperado: {sorted(_VALID_TARGETS)}"
            )
        if button_type == "Codex" and target_path != "terminal-codex-output":
            raise ValueError(
                "button_type='Codex' exige target_path='terminal-codex-output' "
                f"(recebido: {target_path!r})"
            )

        self._label = label
        self._button_type: ButtonType = button_type
        self._prompt: str | Path = prompt
        self._agent_name = agent_name
        self._agent_path = agent_path
        self._action: ActionType = action
        self._target_path = target_path

        # ── Visual ───────────────────────────────────────────────────────
        bg = _TYPE_BG[button_type]
        fg = _TYPE_FG[button_type]
        self.setProperty("testid", f"mcp-prompt-button-{button_type.lower()}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: {fg};"
            "  border: 1px solid #52525B; border-radius: 5px;"
            "  padding: 4px 10px; font-weight: 600; }"
            f"QPushButton:hover {{ background-color: {bg}; border-color: #71717A; }}"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )

        # Tooltip: primeiras 80 chars do prompt
        prompt_preview = self._resolve_prompt_text()[:80]
        self.setToolTip(
            f"[{button_type}] {label}\n"
            f"action={action} target={target_path or '-'}\n"
            f"prompt: {prompt_preview}{'...' if len(self._resolve_prompt_text()) > 80 else ''}"
        )

        self.clicked.connect(self._on_clicked)

    # ── API ─────────────────────────────────────────────────────────────

    def payload(self) -> dict:
        """Payload canonico emitido em `prompt_requested`."""
        return {
            "label": self._label,
            "button_type": self._button_type,
            "prompt": str(self._prompt),
            "prompt_text": self._resolve_prompt_text(),
            "agent_name": self._agent_name,
            "agent_path": self._agent_path,
            "action": self._action,
            "target_path": self._target_path,
        }

    # ── Helpers ─────────────────────────────────────────────────────────

    def _resolve_prompt_text(self) -> str:
        """Le prompt se for Path .md, senao retorna a string literal."""
        if isinstance(self._prompt, Path):
            try:
                return self._prompt.read_text(encoding="utf-8")
            except OSError:
                return f"[erro lendo {self._prompt}]"
        return str(self._prompt)

    def _on_clicked(self) -> None:
        self.prompt_requested.emit(self.payload())

    # ── Right-click → modal ─────────────────────────────────────────────

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        modal = MCPPromptConfigModal(
            parent=self,
            label=self._label,
            prompt=self._resolve_prompt_text(),
            agent_name=self._agent_name,
            agent_path=self._agent_path,
            target_path=self._target_path,
        )
        self._last_modal = modal  # mantem ref para inspecao em testes
        if modal.exec() == QDialog.DialogCode.Accepted:
            values = modal.values()
            self._label = values["label"] or self._label
            self.setText(self._label)
            self._prompt = values["prompt"]
            self._agent_name = values["agent_name"] or None
            self._agent_path = values["agent_path"] or None
            new_target = values["target_path"] or None
            if new_target and new_target in _VALID_TARGETS:
                if self._button_type == "Codex" and new_target != "terminal-codex-output":
                    # mantem o atual; nao quebra o widget
                    pass
                else:
                    self._target_path = new_target
        event.accept()


# ── Standalone test runner ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

    app = QApplication(sys.argv)
    root = QWidget()
    root.setWindowTitle("MCPPromptButton — standalone preview")
    layout = QHBoxLayout(root)

    b1 = MCPPromptButton(
        label="Claude · Send",
        button_type="Claude",
        prompt="Resuma o diff atual em 3 bullets.",
        action="send",
        target_path="terminal-interactive-output",
    )
    b2 = MCPPromptButton(
        label="Codex · Queue",
        button_type="Codex",
        prompt="Adversarial review da PR atual.",
        action="queue",
        target_path="terminal-codex-output",
    )
    b3 = MCPPromptButton(
        label="Kimi · Config",
        button_type="Kimi",
        prompt="Pair analyse no comando ativo.",
        action="config",
        target_path="terminal-workspace-output",
    )
    for b in (b1, b2, b3):
        b.prompt_requested.connect(lambda p: print("emitted:", p))
        layout.addWidget(b)

    root.show()
    sys.exit(app.exec())

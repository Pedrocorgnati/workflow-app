"""FlagsPanel — painel de flags MCP na aba LLM Config (item 021).

7 checkboxes (um por literal canonico), com logica de disable/tooltip
quando a flag e incompativel com o Main corrente (C-57).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from workflow_app.config.llm_flags import (
    _FLAG_LITERAL_TO_MAIN,
    _REDUNDANT_FLAG_MAINS,
    _SUPPORTED_MCP_FLAGS,
)

if TYPE_CHECKING:
    pass

# Ordem estavel dos checkboxes na UI (alfabetica por literal).
_FLAG_ORDER: list[str] = sorted(_SUPPORTED_MCP_FLAGS)

# Tooltip default para flags habilitadas.
_DEFAULT_TOOLTIP = (
    "Quando marcado, anexa {flag} ao label dos itens T1 (Claude). "
    "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
)


class FlagsPanel(QWidget):
    """Painel com 7 checkboxes de flag MCP na aba LLM Config.

    Sinal ``flags_changed`` e emitido quando qualquer checkbox muda de estado.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        main_llm_resolver: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._main_llm_resolver = main_llm_resolver
        self._checkboxes: dict[str, QCheckBox] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Flag")
        layout.addWidget(label)

        for flag in _FLAG_ORDER:
            chk = QCheckBox(flag)
            testid = f"queue-chk-flag-{flag.lstrip('-')}"
            chk.setProperty("testid", testid)
            chk.setToolTip(_DEFAULT_TOOLTIP.format(flag=flag))
            chk.toggled.connect(self._on_checkbox_toggled)
            layout.addWidget(chk)
            self._checkboxes[flag] = chk

        layout.addStretch(1)

    def _on_checkbox_toggled(self, checked: bool) -> None:
        _ = checked
        # Re-emit para consumidores externos (command_queue, etc.).
        if hasattr(self, "flags_changed"):
            self.flags_changed.emit()  # type: ignore[attr-defined]

    def checked_flags(self) -> list[str]:
        """Retorna as flags marcadas na ordem estavel."""
        return [f for f in _FLAG_ORDER if self._checkboxes[f].isChecked()]

    def set_main_llm(self, main: str) -> None:
        """Atualiza enabled/disabled e tooltip de cada checkbox.

        Regras (C-57):
          - Kill-switch SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0: todas disabled.
          - Main claude: todas habilitadas.
          - Main kimi: --kimi e --kimi-k3 disabled (redundantes).
          - Main codex: --codex disabled (redundante).
          - Main qwen: --qwen disabled (redundante).
          - Main grok: --grok disabled (redundante).
        """
        from workflow_app.config import delegation_flags_nonclaude_enabled

        ks_enabled = delegation_flags_nonclaude_enabled()
        if not ks_enabled:
            for flag, chk in self._checkboxes.items():
                chk.setEnabled(False)
                chk.setToolTip(
                    "Paridade de flags desabilitada pelo kill-switch "
                    "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0."
                )
            return

        slug = main.strip().lower() if main else "claude"

        for flag, chk in self._checkboxes.items():
            redundant_main = _REDUNDANT_FLAG_MAINS.get(flag)
            if redundant_main is not None and slug == redundant_main:
                chk.setEnabled(False)
                chk.setToolTip(self._tooltip_for_flag(flag, slug, disabled=True))
            else:
                chk.setEnabled(True)
                chk.setToolTip(self._tooltip_for_flag(flag, slug, disabled=False))

    def set_flag_states_from_mirror(self, flags: list[str]) -> None:
        """Sincroniza os checkboxes a partir de uma lista de flags ativas.

        Usado pelo espelho do command_queue para manter paridade bidirecional.
        Nao emite ``flags_changed`` para evitar loop de feedback.
        """
        for flag, chk in self._checkboxes.items():
            should_check = flag in flags
            if chk.isChecked() != should_check:
                chk.blockSignals(True)
                chk.setChecked(should_check)
                chk.blockSignals(False)

    def _tooltip_for_flag(
        self, flag: str, main: str, *, disabled: bool
    ) -> str:
        """Tooltip contextual para uma flag sob um Main especifico."""
        if disabled:
            redundant_main = _REDUNDANT_FLAG_MAINS.get(flag)
            if redundant_main and main == redundant_main:
                return (
                    f"Flag {flag} redundante sob Main {main}."
                )
            return (
                "Paridade de flags desabilitada pelo kill-switch "
                "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0."
            )
        return _DEFAULT_TOOLTIP.format(flag=flag)

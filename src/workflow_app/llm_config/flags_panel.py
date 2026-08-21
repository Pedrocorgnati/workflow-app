"""FlagsPanel — painel de flags MCP na aba LLM Routing (item 021).

Checkboxes (um por literal canonico), com logica de disable/tooltip
quando a flag e incompativel com o Main corrente (C-57 e C-43).

Layout: duas colunas rotuladas — thinking (raciocinio mais poderoso) e
execution (runtime de terminal). A capacidade NAO vive em
`queue-div-main-llm`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from workflow_app.config.llm_flags import (
    _EXECUTION_FLAG_ORDER,
    _FLAG_CANONICAL_ORDER,
    _FLAG_LITERAL_TO_MAIN,
    _FLAGS_BY_TERMINAL,
    _REDUNDANT_FLAG_MAINS,
    _THINKING_FLAG_ORDER,
)

# Ordem estavel dos checkboxes na UI (canonica).
_FLAG_ORDER: list[str] = list(_FLAG_CANONICAL_ORDER)

_COLUMN_LABEL_QSS = (
    "QLabel { color: #A1A1AA; font-size: 9px; font-weight: 700;"
    "  letter-spacing: 0.5px; background: transparent; border: none; }"
)

# Tooltip default para flags habilitadas.
_DEFAULT_TOOLTIP = (
    "Quando marcado, anexa {flag} ao label dos itens T1 (Claude). "
    "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
)

# C-43 / R-40: as skills de provider do lado Kimi (`.kimi/skills/codex`) sao
# auto-proxies do proprio Kimi. Honrar --codex sob Main Kimi produziria
# registro falso de segunda opiniao.
_KIMI_AUTOPROXY_TOOLTIP = (
    "--codex desabilitado sob Main Kimi: as skills de provider do lado Kimi "
    "sao auto-proxy, entao a flag viraria auto-consulta silenciosa em vez de "
    "segunda opiniao explicita. Para pedir Codex de forma explicita, troque "
    "o Main."
)

_KILL_SWITCH_TOOLTIP = (
    "Paridade de flags desabilitada pelo kill-switch "
    "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0."
)


def _terminals_for_flag(flag: str) -> str:
    """Terminais que aceitam a flag, na ordem T1 > T2 > T3.

    Consome `_FLAGS_BY_TERMINAL` (constante que ate 2026-08-17 nascia morta,
    gap ST003 do item 021): o operador precisa ver, sem clicar, onde a flag
    tem efeito.
    """
    return ", ".join(
        term for term in ("T1", "T2", "T3")
        if flag in _FLAGS_BY_TERMINAL.get(term, frozenset())
    )


class FlagsPanel(QWidget):
    """Painel de flags MCP na aba LLM Config (thinking / execution).

    Sinal ``flags_changed`` e emitido quando qualquer checkbox muda de estado.
    """

    flags_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        main_llm_resolver: Callable[[], str] | None = None,
        show_label: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self._main_llm_resolver = main_llm_resolver
        self._checkboxes: dict[str, QCheckBox] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._label: QLabel | None = None
        if show_label:
            self._label = QLabel("Flag")
            self._label.setStyleSheet(
                "QLabel { color: #A1A1AA; font-size: 11px; font-weight: 700;"
                "  background: transparent; border: none; }"
            )
            outer.addWidget(self._label)

        grid_host = QWidget()
        grid_host.setStyleSheet("background: transparent; border: none;")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)

        thinking_lbl = QLabel("thinking")
        thinking_lbl.setProperty("testid", "queue-div-flag-thinking")
        thinking_lbl.setStyleSheet(_COLUMN_LABEL_QSS)
        execution_lbl = QLabel("execution")
        execution_lbl.setProperty("testid", "queue-div-flag-execution")
        execution_lbl.setStyleSheet(_COLUMN_LABEL_QSS)
        grid.addWidget(thinking_lbl, 0, 0)
        grid.addWidget(execution_lbl, 0, 1)

        thinking_flags = [f for f in _THINKING_FLAG_ORDER if f in _FLAG_ORDER]
        execution_flags = [f for f in _EXECUTION_FLAG_ORDER if f in _FLAG_ORDER]

        def _add_flag_checkbox(flag: str, row: int, column: int) -> None:
            chk = QCheckBox(flag)
            testid = f"queue-chk-flag-{flag.lstrip('-')}"
            chk.setProperty("testid", testid)
            chk.setToolTip(_DEFAULT_TOOLTIP.format(flag=flag))
            chk.toggled.connect(self._on_checkbox_toggled)
            grid.addWidget(chk, row, column)
            self._checkboxes[flag] = chk

        for idx, flag in enumerate(thinking_flags):
            _add_flag_checkbox(flag, idx + 1, 0)
        for idx, flag in enumerate(execution_flags):
            _add_flag_checkbox(flag, idx + 1, 1)

        outer.addWidget(grid_host)
        outer.addStretch(1)

        # Estado inicial coerente com o Main persistido e com o kill-switch:
        # sem esta chamada o painel nascia com todas habilitadas ate o operador
        # girar o radio de Main pela primeira vez (gap A4 do item 021).
        if main_llm_resolver is not None:
            self.refresh()

    # ── Estado ────────────────────────────────────────────────────────────── #

    def _on_checkbox_toggled(self, checked: bool) -> None:
        _ = checked
        self.flags_changed.emit()

    def checkbox(self, flag: str) -> QCheckBox | None:
        """Acessor do QCheckBox de uma flag (None quando o literal e invalido).

        Usado pelo `CommandQueueWidget` para expor os checkboxes do painel como
        `_flag_<slug>_chk`, mantendo UM unico controle por literal (e portanto
        um unico `queue-chk-flag-*` por testid).
        """
        return self._checkboxes.get(flag)

    def checked_flags(self) -> list[str]:
        """Retorna as flags marcadas na ordem estavel."""
        return [f for f in _FLAG_ORDER if self._checkboxes[f].isChecked()]

    def refresh(self) -> None:
        """Reaplica enabled/tooltip lendo o Main do resolver injetado."""
        if self._main_llm_resolver is None:
            return
        try:
            self.set_main_llm(self._main_llm_resolver())
        except Exception:  # noqa: BLE001 - painel nunca derruba a janela
            self.set_main_llm("claude")

    def set_main_llm(self, main: str) -> None:
        """Atualiza enabled/disabled e tooltip de cada checkbox.

        Regras:
          - Kill-switch SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0: disabled
            apenas sob Main **nao-Claude** (source.md:444). Sob Main Claude o
            kill-switch nao tem efeito: nao existe delegacao non-Claude a
            frear quando o proprio Main ja e Claude.
          - Main claude: todas habilitadas (variantes de raciocinio nao
            redundam o CLI do T1).
          - Main kimi: --kimi e --kimi-k3 disabled (redundantes) e --codex
            disabled por auto-proxy (C-43/R-40).
          - Main codex: --codex e --codex-ultra disabled (redundantes).
          - Main qwen: --qwen disabled (redundante).
          - Main grok: --grok e --grok-xhigh disabled (redundantes).
        """
        from workflow_app.config import delegation_flags_nonclaude_enabled

        slug = main.strip().lower() if main else "claude"
        ks_enabled = delegation_flags_nonclaude_enabled()

        if not ks_enabled and slug != "claude":
            for chk in self._checkboxes.values():
                chk.setEnabled(False)
                chk.setToolTip(_KILL_SWITCH_TOOLTIP)
            return

        for flag, chk in self._checkboxes.items():
            if flag in {"--codex", "--codex-ultra"} and slug == "kimi":
                chk.setEnabled(False)
                chk.setToolTip(_KIMI_AUTOPROXY_TOOLTIP)
                continue
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
                return f"Flag {flag} redundante sob Main {main}."
            return _KILL_SWITCH_TOOLTIP
        target = _FLAG_LITERAL_TO_MAIN.get(flag, "")
        terminals = _terminals_for_flag(flag)
        suffix = ""
        if target and terminals:
            suffix = f"\nDelega para {target}. Aceita em: {terminals}."
        return _DEFAULT_TOOLTIP.format(flag=flag) + suffix

"""
OutputPanel — Terminal output viewer with VT100 rendering.

States:
  - Empty: centered "Aguardando execução..." in muted color
  - Running: QPlainTextEdit with monospace font, auto-scroll
  - Interactive: text area + QLineEdit + [Enviar] button at bottom

Layout:
  QStackedWidget with:
    page 0 = empty state label
    page 1 = terminal (QPlainTextEdit)
    page 2 = interactive (terminal + input bar)
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.signal_bus import signal_bus

_PAGE_EMPTY = 0
_PAGE_TERMINAL = 1
_PAGE_INTERACTIVE = 2

# Max lines to keep in terminal buffer (configurable)
DEFAULT_MAX_LINES = 10_000


class OutputPanel(QWidget):
    """Terminal output area that handles streaming VT100 output."""

    # Emitted when user submits interactive input
    user_input_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OutputPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("background-color: #18181B;")

        self._max_lines = DEFAULT_MAX_LINES
        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: Empty state
        empty_page = QWidget()
        empty_page.setStyleSheet("background-color: #18181B;")
        el = QVBoxLayout(empty_page)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label = QLabel("Aguardando execução...")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("color: #78716C; font-size: 14px;")
        el.addWidget(empty_label)
        self._stack.addWidget(empty_page)

        # Page 1: Terminal (plain text)
        terminal_page = QWidget()
        terminal_page.setStyleSheet("background-color: #18181B;")
        tl = QVBoxLayout(terminal_page)
        tl.setContentsMargins(0, 0, 0, 0)
        self._terminal = QPlainTextEdit()
        self._terminal.setObjectName("TerminalOutput")
        self._terminal.setReadOnly(True)
        self._terminal.setStyleSheet(
            "background-color: #18181B; color: #FAFAFA; border: none;"
            " font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;"
            " font-size: 13px;"
        )
        self._terminal.setMaximumBlockCount(self._max_lines)
        tl.addWidget(self._terminal)
        self._stack.addWidget(terminal_page)

        # Page 2: Interactive (terminal + input bar)
        interactive_page = QWidget()
        interactive_page.setStyleSheet("background-color: #18181B;")
        il = QVBoxLayout(interactive_page)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)

        self._terminal_i = QPlainTextEdit()
        self._terminal_i.setObjectName("TerminalOutput")
        self._terminal_i.setReadOnly(True)
        self._terminal_i.setStyleSheet(
            "background-color: #18181B; color: #FAFAFA; border: none;"
            " font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;"
            " font-size: 13px;"
        )
        self._terminal_i.setMaximumBlockCount(self._max_lines)
        il.addWidget(self._terminal_i, stretch=1)

        # Input bar
        input_bar = QWidget()
        input_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        input_bar.setFixedHeight(48)
        ib_layout = QHBoxLayout(input_bar)
        ib_layout.setContentsMargins(8, 8, 8, 8)
        ib_layout.setSpacing(8)

        self._input_field = QLineEdit()
        self._input_field.setObjectName("InteractiveInput")
        self._input_field.setPlaceholderText("Digite sua resposta...")
        self._input_field.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #FBBF24; border-radius: 4px; padding: 4px 10px;"
        )
        self._input_field.returnPressed.connect(self._submit_input)
        ib_layout.addWidget(self._input_field, stretch=1)

        self._send_btn = QPushButton("Enviar")
        self._send_btn.setObjectName("PrimaryButton")
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        self._send_btn.clicked.connect(self._submit_input)
        ib_layout.addWidget(self._send_btn)

        il.addWidget(input_bar)
        self._stack.addWidget(interactive_page)

        self._stack.setCurrentIndex(_PAGE_EMPTY)

    def _connect_signals(self) -> None:
        signal_bus.output_appended.connect(self.append_output)
        signal_bus.output_cleared.connect(self.clear)
        signal_bus.interactive_input_requested.connect(self._enter_interactive_mode)
        signal_bus.pipeline_started.connect(self._on_pipeline_started)
        signal_bus.pipeline_completed.connect(self._on_pipeline_completed)
        signal_bus.pipeline_cancelled.connect(self._on_pipeline_completed)

    # ─────────────────────────────────────────────────────── Public API ─ #

    def append_output(self, text: str) -> None:
        """Append a text chunk to the terminal output (auto-scroll)."""
        for terminal in (self._terminal, self._terminal_i):
            terminal.moveCursor(QTextCursor.MoveOperation.End)
            terminal.insertPlainText(text)
            terminal.moveCursor(QTextCursor.MoveOperation.End)

        if self._stack.currentIndex() == _PAGE_EMPTY:
            self._stack.setCurrentIndex(_PAGE_TERMINAL)

    def clear(self) -> None:
        """Clear terminal and reset to empty state."""
        self._terminal.clear()
        self._terminal_i.clear()
        self._stack.setCurrentIndex(_PAGE_EMPTY)

    def set_max_lines(self, max_lines: int) -> None:
        self._max_lines = max_lines
        self._terminal.setMaximumBlockCount(max_lines)
        self._terminal_i.setMaximumBlockCount(max_lines)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_pipeline_started(self) -> None:
        if self._stack.currentIndex() == _PAGE_EMPTY:
            self._stack.setCurrentIndex(_PAGE_TERMINAL)

    def _on_pipeline_completed(self) -> None:
        if self._stack.currentIndex() == _PAGE_INTERACTIVE:
            self._stack.setCurrentIndex(_PAGE_TERMINAL)

    def _enter_interactive_mode(self) -> None:
        # Copy current terminal content to interactive terminal
        current_text = self._terminal.toPlainText()
        self._terminal_i.setPlainText(current_text)
        self._terminal_i.moveCursor(QTextCursor.MoveOperation.End)
        self._stack.setCurrentIndex(_PAGE_INTERACTIVE)
        self._input_field.setFocus()

    def _submit_input(self) -> None:
        text = self._input_field.text().strip()
        if not text:
            return
        self._input_field.clear()
        self._stack.setCurrentIndex(_PAGE_TERMINAL)
        # Echo input to terminal
        self.append_output(f"\n> {text}\n")
        self.user_input_submitted.emit(text)
        signal_bus.user_input_submitted.emit(text)

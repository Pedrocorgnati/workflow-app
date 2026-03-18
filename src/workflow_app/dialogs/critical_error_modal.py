"""
CriticalErrorModal — Blocking modal for critical startup errors (module-08/TASK-2).

Displayed when claude-agent-sdk is missing or Claude CLI is not authenticated.
The only available button closes the application.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.errors import SDKNotAuthenticatedError, SDKNotAvailableError

# Graphite Amber theme colours
_COLOR_BG = "#18181B"
_COLOR_TEXT = "#F4F4F5"
_COLOR_AMBER = "#FBBF24"
_COLOR_ERROR = "#EF4444"


class CriticalErrorModal(QDialog):
    """
    Blocking modal for critical startup errors (SDK absent / not authenticated).

    On close, terminates the application via sys.exit(1).

    Usage:
        try:
            adapter.ensure_sdk_ready()
        except (SDKNotAvailableError, SDKNotAuthenticatedError) as exc:
            CriticalErrorModal.show_and_exit(exc)
    """

    def __init__(
        self,
        title: str,
        message: str,
        instruction: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui(title, message, instruction)
        self._apply_theme()

    def _build_ui(self, title: str, message: str, instruction: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title_lbl = QLabel(f"Erro Crítico: {title}")
        title_lbl.setStyleSheet(
            f"color: {_COLOR_ERROR}; font-size: 15px; font-weight: bold;"
        )
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(f"color: {_COLOR_TEXT}; font-size: 12px;")
        layout.addWidget(msg_lbl)

        instr_lbl = QLabel(f"Como corrigir:\n{instruction}")
        instr_lbl.setWordWrap(True)
        instr_lbl.setStyleSheet(
            f"color: {_COLOR_AMBER}; font-size: 12px; "
            f"background: #1C1C1E; border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(instr_lbl)

        btn = QPushButton("Fechar app")
        btn.setStyleSheet(
            f"background: {_COLOR_ERROR}; color: white; "
            f"border: none; border-radius: 4px; padding: 8px 20px; font-weight: bold;"
        )
        btn.clicked.connect(self._close_app)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _close_app(self) -> None:
        self.reject()
        QApplication.quit()
        sys.exit(1)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"QDialog {{ background: {_COLOR_BG}; color: {_COLOR_TEXT}; }}"
        )

    @classmethod
    def show_and_exit(
        cls,
        exc: Exception,
        parent: QWidget | None = None,
    ) -> None:
        """
        Factory: creates and displays the appropriate modal for the error type.

        Args:
            exc: SDKNotAvailableError or SDKNotAuthenticatedError.
            parent: Optional parent widget.
        """
        if isinstance(exc, SDKNotAvailableError):
            dlg = cls(
                title="SDK não encontrado",
                message=str(exc),
                instruction="pip install claude-agent-sdk",
                parent=parent,
            )
        elif isinstance(exc, SDKNotAuthenticatedError):
            dlg = cls(
                title="Claude não autenticado",
                message=str(exc),
                instruction="claude auth login",
                parent=parent,
            )
        else:
            dlg = cls(
                title="Erro de inicialização",
                message=str(exc),
                instruction="Verifique os logs para mais detalhes.",
                parent=parent,
            )
        dlg.exec()

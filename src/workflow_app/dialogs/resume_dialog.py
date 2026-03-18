"""
ResumeDialog — Displayed at startup when an interrupted pipeline is detected.

Shows info about the interrupted pipeline (last completed command, uncertain
command, pending count, timestamp) and lets the user choose:
  - Reexecutar: retry the uncertain command
  - Pular: skip uncertain and continue from next PENDENTE
  - Cancelar: cancel the pipeline entirely
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


@dataclass
class ResumeInfo:
    """Data about an interrupted pipeline to display in ResumeDialog."""

    pipeline_exec_id: int
    last_completed_command: str | None    # name of the last completed command
    uncertain_command: str | None         # command that was executing when interrupted
    pending_count: int                       # commands still PENDENTE after uncertain
    total_count: int                         # total commands in the pipeline
    completed_count: int                     # commands that completed successfully
    interrupted_at: datetime


class ResumeDialog(QDialog):
    """Startup dialog for resuming an interrupted pipeline."""

    RESULT_REEXECUTE = QDialog.DialogCode.Accepted
    RESULT_SKIP = 2
    RESULT_CANCEL = QDialog.DialogCode.Rejected

    def __init__(self, info: ResumeInfo, parent=None) -> None:
        super().__init__(parent)
        self._info = info
        self._user_choice: int = int(self.RESULT_CANCEL)
        self.setWindowTitle("Retomar Pipeline Interrompido")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        title = QLabel("Pipeline interrompido detectado")
        title.setStyleSheet(
            "color: #FBBF24; font-size: 15px; font-weight: bold;"
        )
        layout.addWidget(title)

        # Info card
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { background-color: #27272A; border: 1px solid #3F3F46;"
            "  border-radius: 6px; padding: 4px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)
        card_layout.setContentsMargins(12, 10, 12, 10)

        interrupted_str = self._info.interrupted_at.strftime("%Y-%m-%d %H:%M")
        rows = [
            ("Interrompido em:", interrupted_str),
            ("Último concluído:", self._info.last_completed_command or "—"),
            ("Comando incerto:", self._info.uncertain_command or "—"),
            ("Comandos pendentes:", str(self._info.pending_count)),
        ]
        for label_text, value in rows:
            row_lbl = QLabel(f"<b>{label_text}</b>&nbsp;{value}")
            row_lbl.setTextFormat(Qt.TextFormat.RichText)
            row_lbl.setStyleSheet("color: #F4F4F5; font-size: 12px;")
            card_layout.addWidget(row_lbl)

        layout.addWidget(card)

        # Progress bar
        if self._info.total_count > 0:
            progress = QProgressBar()
            progress.setMaximum(self._info.total_count)
            progress.setValue(self._info.completed_count)
            progress.setFormat(
                f"{self._info.completed_count}/{self._info.total_count} comandos"
            )
            progress.setStyleSheet(
                "QProgressBar { background-color: #3F3F46; border-radius: 4px;"
                "  color: #F4F4F5; font-size: 11px; text-align: center; }"
                "QProgressBar::chunk { background-color: #FBBF24; border-radius: 4px; }"
            )
            layout.addWidget(progress)

        # Action buttons
        btn_reexecute = QPushButton("Reexecutar comando incerto")
        btn_reexecute.setDefault(True)
        btn_reexecute.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        btn_reexecute.clicked.connect(self._on_reexecute)
        layout.addWidget(btn_reexecute)

        btn_skip = QPushButton("Pular e continuar")
        btn_skip.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        btn_skip.clicked.connect(self._on_skip)
        layout.addWidget(btn_skip)

        btn_cancel = QPushButton("Cancelar pipeline")
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: transparent; color: #71717A;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 14px; }"
            "QPushButton:hover { color: #A1A1AA; }"
        )
        btn_cancel.clicked.connect(self._on_cancel_pipeline)
        layout.addWidget(btn_cancel)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_reexecute(self) -> None:
        self._user_choice = int(self.RESULT_REEXECUTE)
        self.accept()

    def _on_skip(self) -> None:
        self._user_choice = self.RESULT_SKIP
        self.done(self.RESULT_SKIP)

    def _on_cancel_pipeline(self) -> None:
        self._user_choice = int(self.RESULT_CANCEL)
        self.reject()

    # ─────────────────────────────────────────────────────── API ─── #

    def user_choice(self) -> int:
        """Return the user's action choice after exec()."""
        return self._user_choice

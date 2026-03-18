"""
SaveTemplateDialog — Modal dialog to save a command queue as a custom template.

Accepts a name (required, unique) and description (optional).
Validates inline: empty name and duplicate name show an error label.
On Accepted, exposes .name, .description and .commands for the caller.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from workflow_app.domain import CommandSpec


class SaveTemplateDialog(QDialog):
    """Modal dialog for saving a custom template."""

    def __init__(
        self,
        parent=None,
        *,
        commands: list[CommandSpec] | None = None,
        existing_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Salvar como Template")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._commands: list[CommandSpec] = commands or []
        self._existing_names: list[str] = [n.lower() for n in (existing_names or [])]

        self._setup_ui()

    # ─────────────────────────────────────────────────────── properties ── #

    @property
    def name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def description(self) -> str:
        return self._desc_edit.toPlainText().strip()

    @property
    def commands(self) -> list[CommandSpec]:
        return self._commands

    # ──────────────────────────────────────────────────────── UI setup ── #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Name ────────────────────────────────────────────────────────── #
        name_label = QLabel("Nome do template *")
        name_label.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        layout.addWidget(name_label)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Ex: Pipeline Feature Rápida")
        self._name_edit.setStyleSheet(
            "QLineEdit { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
            "  font-size: 13px; }"
            "QLineEdit:focus { border-color: #F59E0B; }"
        )
        self._name_edit.textChanged.connect(self._clear_error)
        layout.addWidget(self._name_edit)

        # ── Inline error ─────────────────────────────────────────────────── #
        self._error_label = QLabel()
        self._error_label.setStyleSheet("color: #FB7185; font-size: 12px;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # ── Description ─────────────────────────────────────────────────── #
        desc_label = QLabel("Descrição (opcional)")
        desc_label.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        layout.addWidget(desc_label)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Descreva quando usar este template...")
        self._desc_edit.setFixedHeight(80)
        self._desc_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
            "  font-size: 13px; }"
            "QPlainTextEdit:focus { border-color: #F59E0B; }"
        )
        layout.addWidget(self._desc_edit)

        # ── Command count info ───────────────────────────────────────────── #
        count = len(self._commands)
        info = QLabel(f"{count} comando{'s' if count != 1 else ''} serão salvos.")
        info.setStyleSheet("color: #71717A; font-size: 12px;")
        layout.addWidget(info)

        layout.addSpacing(4)

        # ── Buttons ─────────────────────────────────────────────────────── #
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Salvar")
        self._save_btn.setDefault(True)
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #B45309; color: #FAFAFA;"
            "  border: 1px solid #D97706; border-radius: 4px; padding: 6px 16px;"
            "  font-weight: bold; }"
            "QPushButton:hover { background-color: #D97706; }"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)

    # ──────────────────────────────────────────────────────── handlers ── #

    def _on_save_clicked(self) -> None:
        name = self._name_edit.text().strip()

        if not name:
            self._show_error("Nome do template não pode ser vazio.")
            return

        if name.lower() in self._existing_names:
            self._show_error(f"Nome já existente: '{name}'. Escolha outro.")
            return

        self.accept()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        self._name_edit.setStyleSheet(
            "QLineEdit { background-color: #27272A; color: #FAFAFA;"
            "  border: 1px solid #FB7185; border-radius: 4px; padding: 6px 10px;"
            "  font-size: 13px; }"
        )

    def _clear_error(self) -> None:
        if self._error_label.isVisible():
            self._error_label.setVisible(False)
            self._name_edit.setStyleSheet(
                "QLineEdit { background-color: #27272A; color: #FAFAFA;"
                "  border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
                "  font-size: 13px; }"
                "QLineEdit:focus { border-color: #F59E0B; }"
            )

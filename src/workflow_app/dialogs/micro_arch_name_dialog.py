"""
MicroArchNameDialog — Modal para capturar o slug (kebab-case) da micro-arquitetura.

Exibe um input com validação em tempo real. Só habilita Confirmar quando o
valor é kebab-case válido. Auto-sanitiza o texto ao digitar.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class MicroArchNameDialog(QDialog):
    """Modal simples para capturar nome em kebab-case da micro-arquitetura."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nova Micro-Arquitetura")
        self.setModal(True)
        self.setFixedSize(420, 200)
        self._slug = ""
        self._setup_ui()

    @property
    def slug(self) -> str:
        return self._slug

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #18181B;")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Nome da micro-arquitetura")
        title.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("kebab-case: letras minúsculas e hífens.  Ex: checkout-pagamento")
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        layout.addWidget(subtitle)

        self._input = QLineEdit()
        self._input.setPlaceholderText("ex: minha-feature")
        self._input.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #52525B; border-radius: 4px;"
            " padding: 6px 10px; font-size: 13px; font-family: monospace;"
        )
        self._input.setFixedHeight(38)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_confirm)
        layout.addWidget(self._input)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #F87171; font-size: 10px;")
        self._error_label.setFixedHeight(14)
        layout.addWidget(self._error_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self._btn_confirm = QPushButton("Confirmar")
        self._btn_confirm.setFixedHeight(32)
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.setStyleSheet(
            "QPushButton { background-color: #166534; color: #FAFAFA;"
            "  border: none; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #52525B; }"
        )
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._btn_confirm)

        layout.addLayout(btn_row)

    # ── Slots ── #

    def _on_text_changed(self, text: str) -> None:
        # Auto-sanitize: lowercase, spaces → hyphens, strip invalid chars, collapse hyphens
        sanitized = text.lower().replace(" ", "-")
        sanitized = re.sub(r"[^a-z0-9-]", "", sanitized)
        sanitized = re.sub(r"-{2,}", "-", sanitized)

        if sanitized != text:
            self._input.blockSignals(True)
            self._input.setText(sanitized)
            self._input.setCursorPosition(len(sanitized))
            self._input.blockSignals(False)
            text = sanitized

        is_valid = bool(_KEBAB_RE.match(text)) if text else False
        self._btn_confirm.setEnabled(is_valid)

        _base = (
            "background-color: #3F3F46; color: #FAFAFA;"
            " border-radius: 4px; padding: 6px 10px;"
            " font-size: 13px; font-family: monospace;"
        )
        if not text:
            self._error_label.setText("")
            self._input.setStyleSheet(f"{_base} border: 1px solid #52525B;")
        elif is_valid:
            self._error_label.setText("")
            self._input.setStyleSheet(f"{_base} border: 1px solid #22C55E;")
        else:
            self._error_label.setText(
                "Deve começar com letra e conter apenas letras, números e hífens."
            )
            self._input.setStyleSheet(f"{_base} border: 1px solid #EF4444;")

    def _on_confirm(self) -> None:
        if not self._btn_confirm.isEnabled():
            return
        self._slug = self._input.text().strip()
        self.accept()

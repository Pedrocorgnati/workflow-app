"""
PreferencesDialog — Application preferences (module-13/TASK-4).

Tabs:
  - Geral: buffer de saída (linhas), timeout por comando
  - Execução: modo de permissão padrão

Size: 420×320px minimum
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class PreferencesDialog(QDialog):
    """Application preferences dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferências")
        self.setMinimumSize(420, 320)
        self.setModal(True)
        self.setStyleSheet("background-color: #18181B;")
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("Preferências")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #FAFAFA;")
        hl.addWidget(title)
        hl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; color: #A1A1AA; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
        )
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        root.addWidget(header)

        # Tab widget
        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background-color: #18181B; }"
            "QTabBar::tab { background-color: #27272A; color: #A1A1AA;"
            "  border: none; padding: 8px 16px; }"
            "QTabBar::tab:selected { background-color: #18181B; color: #FAFAFA;"
            "  border-bottom: 2px solid #FBBF24; }"
        )
        root.addWidget(tabs, stretch=1)

        # ── Geral tab ────────────────────────────────────────────────── #
        geral_tab = QWidget()
        geral_tab.setStyleSheet("background-color: #18181B;")
        gl = QVBoxLayout(geral_tab)
        gl.setContentsMargins(24, 20, 24, 20)
        gl.setSpacing(16)

        gl.addWidget(QLabel("Buffer de saída (linhas)"))
        self._buffer_spin = QSpinBox()
        self._buffer_spin.setRange(1_000, 100_000)
        self._buffer_spin.setValue(10_000)
        self._buffer_spin.setSingleStep(1_000)
        self._buffer_spin.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
        )
        gl.addWidget(self._buffer_spin)

        gl.addWidget(QLabel("Timeout por comando (segundos)"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(60, 3_600)
        self._timeout_spin.setValue(300)
        self._timeout_spin.setSingleStep(60)
        self._timeout_spin.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
        )
        gl.addWidget(self._timeout_spin)
        gl.addStretch()
        tabs.addTab(geral_tab, "Geral")

        # ── Execução tab ─────────────────────────────────────────────── #
        exec_tab = QWidget()
        exec_tab.setStyleSheet("background-color: #18181B;")
        el = QVBoxLayout(exec_tab)
        el.setContentsMargins(24, 20, 24, 20)
        el.setSpacing(16)

        el.addWidget(QLabel("Modo de Permissão Padrão"))
        self._permission_combo = QComboBox()
        self._permission_combo.addItems(["acceptEdits", "bypassPermissions", "default"])
        self._permission_combo.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 10px;"
        )
        el.addWidget(self._permission_combo)
        el.addStretch()
        tabs.addTab(exec_tab, "Execução")

        # Footer
        footer = QWidget()
        footer.setFixedHeight(56)
        footer.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(8)

        restore_btn = QPushButton("Restaurar Padrões")
        restore_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #71717A;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 14px; }"
            "QPushButton:hover { color: #FAFAFA; border-color: #52525B; }"
        )
        restore_btn.clicked.connect(self._restore_defaults)
        fl.addWidget(restore_btn)

        fl.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        cancel_btn.clicked.connect(self.reject)
        fl.addWidget(cancel_btn)

        save_btn = QPushButton("Salvar")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        save_btn.clicked.connect(self.accept)
        fl.addWidget(save_btn)
        root.addWidget(footer)

    def _restore_defaults(self) -> None:
        self._buffer_spin.setValue(10_000)
        self._timeout_spin.setValue(300)
        self._permission_combo.setCurrentText("acceptEdits")

    def get_settings(self) -> dict:
        return {
            "buffer_lines": self._buffer_spin.value(),
            "timeout_seconds": self._timeout_spin.value(),
            "permission_mode": self._permission_combo.currentText(),
        }

"""
PreferencesDialog — Application preferences with two tabs (module-13/TASK-4).

Aba Geral:
  - buffer_limit: int (1000–50000, padrão 10000)
  - timeout_seconds: int (60–3600, padrão 300)

Aba Execução:
  - default_permission_mode: str (acceptEdits / autoAccept / manual)

Persistence via file-based AppConfig (~/.workflow-app/config.json).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.config.app_config import AppConfig

# ── Constants ──────────────────────────────────────────────────────────────── #

_DEFAULT_BUFFER_LIMIT = 10_000
_DEFAULT_TIMEOUT_SECONDS = 300
_DEFAULT_PERMISSION_MODE = "acceptEdits"

_PERMISSION_MODE_OPTIONS: list[tuple[str, str]] = [
    ("acceptEdits — aceitar edições automaticamente", "acceptEdits"),
    ("autoAccept — aceitar tudo sem confirmação", "autoAccept"),
    ("manual — aprovar cada ação manualmente", "manual"),
]


class PreferencesDialog(QDialog):
    """Application preferences dialog with two tabs.

    Accepts an optional db_manager argument for API compatibility, but
    persists settings via the file-based AppConfig.
    """

    def __init__(
        self,
        db_manager=None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_manager = db_manager  # kept for future DB-backed settings

        self.setWindowTitle("Preferências")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog { background-color: #18181B; color: #FAFAFA; }"
            "QTabWidget::pane { border: 1px solid #3F3F46; border-radius: 4px; }"
            "QTabBar::tab { background: #27272A; color: #A1A1AA; padding: 6px 16px; }"
            "QTabBar::tab:selected { background: #3F3F46; color: #FAFAFA; }"
            "QSpinBox, QComboBox { background: #27272A; color: #FAFAFA;"
            "  border: 1px solid #3F3F46; border-radius: 4px; padding: 4px 8px; }"
            "QSpinBox:focus, QComboBox:focus { border-color: #FBBF24; }"
            "QPushButton { background: #27272A; color: #FAFAFA; border: 1px solid #3F3F46;"
            "  border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #3F3F46; }"
        )

        self._build_ui()
        self._load_config()

    # ─────────────────────────────────────────────────────── Build UI ─── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # ── Geral tab ─────────────────────────────────────────────────── #
        geral_tab = QWidget()
        geral_form = QFormLayout(geral_tab)
        geral_form.setSpacing(10)

        self._spin_buffer = QSpinBox()
        self._spin_buffer.setRange(1_000, 50_000)
        self._spin_buffer.setSingleStep(1_000)
        self._spin_buffer.setSuffix(" linhas")
        self._spin_buffer.setToolTip("Limite de linhas no buffer de output (1000–50000)")
        geral_form.addRow("Buffer de output:", self._spin_buffer)

        hint_buf = QLabel("Padrão: 10.000 linhas")
        hint_buf.setStyleSheet("color: #71717A; font-size: 11px;")
        geral_form.addRow("", hint_buf)

        self._spin_timeout = QSpinBox()
        self._spin_timeout.setRange(60, 3_600)
        self._spin_timeout.setSingleStep(30)
        self._spin_timeout.setSuffix(" segundos")
        self._spin_timeout.setToolTip("Timeout por comando SDK (60–3600 s)")
        geral_form.addRow("Timeout por comando:", self._spin_timeout)

        hint_tmt = QLabel("Padrão: 300 segundos (5 minutos)")
        hint_tmt.setStyleSheet("color: #71717A; font-size: 11px;")
        geral_form.addRow("", hint_tmt)

        self._tabs.addTab(geral_tab, "Geral")

        # ── Execução tab ──────────────────────────────────────────────── #
        exec_tab = QWidget()
        exec_form = QFormLayout(exec_tab)
        exec_form.setSpacing(10)

        self._combo_permission = QComboBox()
        for label, value in _PERMISSION_MODE_OPTIONS:
            self._combo_permission.addItem(label, userData=value)
        self._combo_permission.setToolTip("Modo de permissão padrão para novas execuções")
        exec_form.addRow("Modo de permissão:", self._combo_permission)

        hint_perm = QLabel(
            "acceptEdits: aprovação automática de edições de arquivo\n"
            "autoAccept: aceita toda e qualquer ação sem confirmação\n"
            "manual: cada ação requer aprovação explícita do usuário"
        )
        hint_perm.setStyleSheet("color: #71717A; font-size: 11px;")
        hint_perm.setWordWrap(True)
        exec_form.addRow("", hint_perm)

        self._tabs.addTab(exec_tab, "Execução")

        # ── Buttons ───────────────────────────────────────────────────── #
        btn_restore = QPushButton("Restaurar Padrões")
        btn_restore.clicked.connect(self._restore_defaults)

        btn_box = QDialogButtonBox()
        btn_save = QPushButton("Salvar")
        btn_save.setStyleSheet(
            "QPushButton { background: #FBBF24; color: #18181B; border: none; }"
            "QPushButton:hover { background: #F59E0B; }"
        )
        btn_cancel = QPushButton("Cancelar")
        btn_box.addButton(btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.addButton(btn_restore, QDialogButtonBox.ButtonRole.ResetRole)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)

        layout.addWidget(btn_box)

    # ─────────────────────────────────────────────────────── Load/Save ── #

    def _load_config(self) -> None:
        """Populate controls from AppConfig (file-based)."""
        buf = AppConfig.get("buffer_limit", _DEFAULT_BUFFER_LIMIT)
        tmt = AppConfig.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        perm = AppConfig.get("default_permission_mode", _DEFAULT_PERMISSION_MODE)

        self._spin_buffer.setValue(int(buf))
        self._spin_timeout.setValue(int(tmt))

        for i in range(self._combo_permission.count()):
            if self._combo_permission.itemData(i) == perm:
                self._combo_permission.setCurrentIndex(i)
                break

    def _save(self) -> None:
        """Persist settings and close."""
        AppConfig.set("buffer_limit", self._spin_buffer.value())
        AppConfig.set("timeout_seconds", self._spin_timeout.value())
        AppConfig.set("default_permission_mode", self._combo_permission.currentData())
        self._show_toast("Preferências salvas")
        self.accept()

    def _restore_defaults(self) -> None:
        """Reset to defaults after user confirmation."""
        reply = QMessageBox.question(
            self,
            "Restaurar Padrões",
            "Restaurar todas as preferências para os valores padrão?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._spin_buffer.setValue(_DEFAULT_BUFFER_LIMIT)
            self._spin_timeout.setValue(_DEFAULT_TIMEOUT_SECONDS)
            for i in range(self._combo_permission.count()):
                if self._combo_permission.itemData(i) == _DEFAULT_PERMISSION_MODE:
                    self._combo_permission.setCurrentIndex(i)
                    break

    def _show_toast(self, message: str) -> None:
        """Display a temporary toast at the bottom of the dialog."""
        from PySide6.QtCore import QTimer as _QTimer

        toast = QLabel(message, self)
        toast.setStyleSheet(
            "background: #FBBF24; color: #18181B; border-radius: 4px;"
            "padding: 6px 12px; font-size: 12px;"
        )
        toast.adjustSize()
        x = (self.width() - toast.width()) // 2
        y = self.height() - toast.height() - 8
        toast.move(max(0, x), max(0, y))
        toast.show()
        _QTimer.singleShot(2000, toast.deleteLater)

    # Kept for backward compatibility
    def get_settings(self) -> dict:
        return {
            "buffer_limit": self._spin_buffer.value(),
            "timeout_seconds": self._spin_timeout.value(),
            "permission_mode": self._combo_permission.currentData(),
        }

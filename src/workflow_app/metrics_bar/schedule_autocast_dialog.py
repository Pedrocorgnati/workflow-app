"""ScheduleAutocastDialog - modal para agendar disparo programatico do botao autocast."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ScheduleAutocastDialog(QDialog):
    """Modal de selecao de tempo. Resultado consultado via total_seconds()."""

    _SHORTCUTS = [("1h", 1, 0), ("2h", 2, 0), ("5h", 5, 0), ("8h", 8, 0)]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agendar autocast")
        self.setProperty("testid", "schedule-autocast-dialog")
        self.setModal(True)
        self._build_ui()
        self._wire_signals()
        self._refresh_ok_state()

    # ---------- UI ---------- #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        info = QLabel("Em quanto tempo disparar o autocast?")
        root.addWidget(info)

        row = QHBoxLayout()
        self._sp_hours = QSpinBox()
        self._sp_hours.setRange(0, 12)
        self._sp_hours.setValue(5)
        self._sp_hours.setSuffix(" h")
        self._sp_hours.setProperty("testid", "schedule-autocast-hours")

        self._sp_minutes = QSpinBox()
        self._sp_minutes.setRange(0, 59)
        self._sp_minutes.setValue(0)
        self._sp_minutes.setSuffix(" min")
        self._sp_minutes.setProperty("testid", "schedule-autocast-minutes")

        row.addWidget(self._sp_hours)
        row.addWidget(self._sp_minutes)
        root.addLayout(row)

        shortcuts = QHBoxLayout()
        self._shortcut_btns: list[QPushButton] = []
        for label, h, m in self._SHORTCUTS:
            btn = QPushButton(label)
            btn.setProperty("testid", f"schedule-autocast-shortcut-{label}")
            btn.clicked.connect(lambda _checked=False, hh=h, mm=m: self._apply_shortcut(hh, mm))
            shortcuts.addWidget(btn)
            self._shortcut_btns.append(btn)
        root.addLayout(shortcuts)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Agendar")
        ok_btn.setProperty("testid", "schedule-autocast-confirm")
        cancel_btn = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Cancelar")
        cancel_btn.setProperty("testid", "schedule-autocast-cancel")
        root.addWidget(self._buttons)

    # ---------- Wiring ---------- #

    def _wire_signals(self) -> None:
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._sp_hours.valueChanged.connect(self._refresh_ok_state)
        self._sp_minutes.valueChanged.connect(self._refresh_ok_state)

    def _apply_shortcut(self, hours: int, minutes: int) -> None:
        self._sp_hours.setValue(hours)
        self._sp_minutes.setValue(minutes)

    def _refresh_ok_state(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(self.total_seconds() > 0)

    # ---------- API publica ---------- #

    def total_seconds(self) -> int:
        return self._sp_hours.value() * 3600 + self._sp_minutes.value() * 60

"""ScheduleAutocastDialog - modal para agendar disparo programatico do botao autocast.

Layout e UX copiados do modal de temporizador do task-manager-desktop
(subtask_pane.py::_open_timer_dialog): radios Data/hora final vs Duracao,
atalhos de duracao e picker de calendario. Sem dependencia de runtime do
task-manager (Nome, Cor, Rotina e Horario fixo semanal ficam de fora).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QDateTime, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCalendarWidget,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Copia local do CLOCK_SVG de task_manager_desktop.ui.icons (nao importar).
_CLOCK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
    '<circle cx="12" cy="12" r="8.4" fill="#F8FAFC" fill-opacity="0.14" '
    'stroke="#F8FAFC" stroke-width="1.9"/>'
    '<path d="M12 7.2v5.1l3.5 2.1" stroke="#F8FAFC" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M7.2 3.9 4.8 6.2M16.8 3.9l2.4 2.3" '
    'stroke="#F8FAFC" stroke-width="1.8" stroke-linecap="round"/>'
    "</svg>"
)


def _svg_to_icon(svg: str, size: int = 20) -> QIcon:
    """Renderiza SVG inline em QIcon. Copia local de svg_to_icon do task-manager."""
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)


class ScheduleAutocastDialog(QDialog):
    """Modal de agendamento de autocast com escolha entre data/hora final ou duracao.

    Resultado: total_seconds() retorna segundos ate o disparo (para duracao)
             ou end_datetime() retorna QDateTime (para data/hora final).
    """

    _SHORTCUTS_DURATION = [
        ("1h", 1, 0),
        ("2h", 2, 0),
        ("5h", 5, 0),
        ("8h", 8, 0),
        ("1d", 24, 0),
        ("7d", 168, 0),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agendar Autocast")
        self.setProperty("testid", "dialog-schedule-autocast")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()
        self._wire_signals()
        self._refresh_ok_state()

    # ---------- UI ---------- #

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #111116; }"
            "QLabel#dlgHead { font-size: 15px; font-weight: 700; color: #F8FAFC; }"
            "QLabel#dlgSec { font-size: 10px; font-weight: 700; color: #71717A;"
            "                 letter-spacing: 1px; }"
            "QLineEdit {"
            "  background: #1C1D24; border: 1px solid #3B3D46; border-radius: 8px;"
            "  padding: 8px 10px; color: #F8FAFC; font-size: 13px; }"
            "QLineEdit:focus { border-color: #FBBF24; }"
            "QDateTimeEdit {"
            "  background: #1C1D24; border: 1px solid #3B3D46; border-radius: 8px;"
            "  padding: 8px 10px; color: #F8FAFC; font-size: 13px; }"
            "QDateTimeEdit:focus { border-color: #FBBF24; }"
            "QDateTimeEdit::drop-down { width: 0; border: none; }"
            "QToolButton#datePickerBtn {"
            "  background: #1C1D24; border: 1px solid #3B3D46; border-radius: 8px;"
            "  padding: 0; }"
            "QToolButton#datePickerBtn:hover { border-color: #FBBF24; background: #27272A; }"
            "QPushButton#shortBtn {"
            "  background: #1C1D24; border: 1px solid #3B3D46; border-radius: 6px;"
            "  color: #A1A1AA; font-size: 12px; font-weight: 800; padding: 8px 12px; }"
            "QPushButton#shortBtn:hover {"
            "  background: #27272A; border-color: #FBBF24; color: #FBBF24; }"
            "QFrame#scheduleBox { background: #15161C; border: 1px solid #3B3D46;"
            "  border-radius: 12px; }"
            "QRadioButton#modeRadio { color: #F8FAFC; font-size: 12px;"
            "  font-weight: 800; spacing: 8px; }"
            "QRadioButton#modeRadio::indicator { width: 14px; height: 14px; }"
            "QLabel#errLabel { color: #F87171; font-size: 11px; }"
            "QLabel#hintLabel { color: #71717A; font-size: 10px; }"
            "QFrame#divider { color: #2F3037; background: #2F3037; max-height: 1px; }"
            "QPushButton#okBtn {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #B45309,stop:1 #FBBF24);"
            "  border: none; border-radius: 8px; color: #0D0E12;"
            "  font-size: 13px; font-weight: 700; padding: 8px 22px; }"
            "QPushButton#okBtn:disabled { background: #27272A; color: #52525B; }"
            "QPushButton#okBtn:hover:!disabled {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #FBBF24,stop:1 #FDE68A); }"
            "QPushButton#cancelBtn {"
            "  background: transparent; border: 1px solid #3B3D46; border-radius: 8px;"
            "  color: #71717A; font-size: 13px; font-weight: 600; padding: 8px 16px; }"
            "QPushButton#cancelBtn:hover { border-color: #71717A; color: #F8FAFC; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(0)

        head = QLabel("Agendar Autocast", self)
        head.setObjectName("dlgHead")
        root.addWidget(head)
        root.addSpacing(16)

        schedule_box = QFrame(self)
        schedule_box.setObjectName("scheduleBox")
        schedule_box.setProperty("testid", "schedule-autocast-schedule-box")
        sched = QVBoxLayout(schedule_box)
        sched.setContentsMargins(14, 12, 14, 14)
        sched.setSpacing(0)

        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        self._mode_datetime = QRadioButton("Data/hora final", schedule_box)
        self._mode_datetime.setObjectName("modeRadio")
        self._mode_datetime.setProperty("testid", "schedule-autocast-mode-datetime")
        self._mode_datetime.setAccessibleName("Agendar em data/hora especifica")
        self._mode_datetime.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_duration = QRadioButton("Duração", schedule_box)
        self._mode_duration.setObjectName("modeRadio")
        self._mode_duration.setProperty("testid", "schedule-autocast-mode-duration")
        self._mode_duration.setAccessibleName("Agendar em X tempo a partir de agora")
        self._mode_duration.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_duration.setChecked(True)
        mode_group.addButton(self._mode_datetime)
        mode_group.addButton(self._mode_duration)
        sched.addWidget(self._mode_duration)
        sched.addWidget(self._mode_datetime)
        sched.addSpacing(12)

        self._datetime_container = QWidget()
        self._datetime_container.setProperty(
            "testid", "schedule-autocast-datetime-container"
        )
        dt_container_layout = QVBoxLayout(self._datetime_container)
        dt_container_layout.setContentsMargins(0, 0, 0, 0)
        dt_container_layout.setSpacing(4)

        lbl_dt = QLabel("DATA/HORA FINAL", self._datetime_container)
        lbl_dt.setObjectName("dlgSec")
        dt_container_layout.addWidget(lbl_dt)

        self._end_dt = QDateTimeEdit(self._datetime_container)
        self._end_dt.setCalendarPopup(True)
        self._end_dt.setDisplayFormat("dd/MM/yyyy  HH:mm")
        self._end_dt.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self._end_dt.setProperty("testid", "schedule-autocast-datetime")
        dt_row = QHBoxLayout()
        dt_row.setSpacing(8)
        dt_row.addWidget(self._end_dt, 1)

        self._picker_btn = QToolButton(self._datetime_container)
        self._picker_btn.setObjectName("datePickerBtn")
        self._picker_btn.setProperty("testid", "schedule-autocast-datetime-picker")
        self._picker_btn.setAccessibleName("Escolher data e hora finais")
        self._picker_btn.setToolTip("Escolher data e hora")
        self._picker_btn.setIcon(_svg_to_icon(_CLOCK_SVG, 19))
        self._picker_btn.setIconSize(QSize(19, 19))
        self._picker_btn.setFixedSize(40, 40)
        self._picker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dt_row.addWidget(self._picker_btn)
        dt_container_layout.addLayout(dt_row)
        sched.addWidget(self._datetime_container)

        self._duration_container = QWidget()
        self._duration_container.setProperty("testid", "schedule-autocast-duration-container")
        dur_container_layout = QVBoxLayout(self._duration_container)
        dur_container_layout.setContentsMargins(0, 0, 0, 0)
        dur_container_layout.setSpacing(4)

        lbl_duration = QLabel("DURAÇÃO", self._duration_container)
        lbl_duration.setObjectName("dlgSec")
        dur_container_layout.addWidget(lbl_duration)

        duration_row = QHBoxLayout()
        duration_row.setSpacing(8)
        self._duration_input = QLineEdit(self._duration_container)
        self._duration_input.setProperty("testid", "schedule-autocast-duration-input")
        self._duration_input.setAccessibleName("Duração em formato HH:MM:SS")
        self._duration_input.setPlaceholderText("05:00:00")
        # 7d -> "168:00:00" (9 chars); o teto antigo de 8 cortava o atalho.
        self._duration_input.setMaxLength(9)
        self._duration_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration_input.setText("05:00:00")
        duration_row.addWidget(self._duration_input, 1)

        for label, h, m in self._SHORTCUTS_DURATION:
            shortcut = QPushButton(label, self._duration_container)
            shortcut.setObjectName("shortBtn")
            shortcut.setProperty("testid", f"schedule-autocast-shortcut-{label}")
            shortcut.setCursor(Qt.CursorShape.PointingHandCursor)
            shortcut.clicked.connect(
                lambda _checked=False, hh=h, mm=m: self._apply_duration_shortcut(hh, mm)
            )
            duration_row.addWidget(shortcut)

        dur_container_layout.addLayout(duration_row)
        sched.addWidget(self._duration_container)

        hint = QLabel(
            "Autocast disparará automaticamente após o tempo definido. "
            "Data/hora final permite agendar para momento específico; "
            "Duração aguarda a partir de agora.",
            self,
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        sched.addSpacing(8)
        sched.addWidget(hint)

        root.addWidget(schedule_box)
        root.addSpacing(14)

        self._err_label = QLabel("", self)
        self._err_label.setObjectName("errLabel")
        self._err_label.setVisible(False)
        root.addWidget(self._err_label)
        root.addSpacing(18)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("✕  Cancelar", self)
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setProperty("testid", "schedule-autocast-cancel")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn = QPushButton("✓  Agendar", self)
        self._ok_btn.setObjectName("okBtn")
        self._ok_btn.setProperty("testid", "schedule-autocast-confirm")
        self._ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn.setDefault(True)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

        self._on_mode_changed()
        self._mode_datetime.toggled.connect(self._on_mode_changed)
        self._mode_duration.toggled.connect(self._on_mode_changed)

    # ---------- Wiring ---------- #

    def _wire_signals(self) -> None:
        self._ok_btn.clicked.connect(self._on_ok_clicked)
        self._cancel_btn.clicked.connect(self.reject)
        self._end_dt.dateTimeChanged.connect(self._refresh_ok_state)
        self._duration_input.textChanged.connect(self._refresh_ok_state)
        self._picker_btn.clicked.connect(self._open_datetime_picker)

    def _open_datetime_picker(self) -> None:
        """Calendario + hora, copiado de subtask_pane._open_timer_dialog._open_picker."""
        picker = QDialog(self)
        picker.setWindowTitle("Escolher data e hora")
        picker.setProperty("testid", "schedule-autocast-datetime-picker-dialog")
        picker.setModal(True)
        picker.setMinimumWidth(330)
        picker.setStyleSheet(self.styleSheet())
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(18, 18, 18, 18)
        picker_layout.setSpacing(12)

        calendar = QCalendarWidget(picker)
        calendar.setProperty("testid", "schedule-autocast-calendar")
        calendar.setSelectedDate(self._end_dt.dateTime().date())
        picker_layout.addWidget(calendar)

        time_edit = QTimeEdit(picker)
        time_edit.setProperty("testid", "schedule-autocast-time-edit")
        time_edit.setDisplayFormat("HH:mm:ss")
        time_edit.setTime(self._end_dt.dateTime().time())
        time_edit.setStyleSheet(
            "QTimeEdit { background: #1C1D24; border: 1px solid #3B3D46;"
            "border-radius: 8px; padding: 8px 10px; color: #F8FAFC;"
            "font-size: 14px; }"
        )
        picker_layout.addWidget(time_edit)

        picker_buttons = QHBoxLayout()
        picker_buttons.addStretch(1)
        picker_cancel = QPushButton("Cancelar", picker)
        picker_cancel.setObjectName("cancelBtn")
        picker_cancel.setProperty("testid", "schedule-autocast-picker-cancel")
        picker_ok = QPushButton("OK", picker)
        picker_ok.setObjectName("okBtn")
        picker_ok.setProperty("testid", "schedule-autocast-picker-ok")
        picker_buttons.addWidget(picker_cancel)
        picker_buttons.addWidget(picker_ok)
        picker_layout.addLayout(picker_buttons)
        picker_cancel.clicked.connect(picker.reject)
        picker_ok.clicked.connect(picker.accept)

        if picker.exec() == QDialog.DialogCode.Accepted:
            self._end_dt.setDateTime(
                QDateTime(calendar.selectedDate(), time_edit.time())
            )
            self._refresh_ok_state()

    def _on_mode_changed(self) -> None:
        """Atualiza visibilidade dos campos baseado no modo selecionado."""
        is_datetime = self._mode_datetime.isChecked()
        self._datetime_container.setVisible(is_datetime)
        self._duration_container.setVisible(not is_datetime)
        self._refresh_ok_state()

    def _apply_duration_shortcut(self, hours: int, minutes: int) -> None:
        """Aplica um atalho de duracao (ex: 1h, 1d)."""
        total_seconds = hours * 3600 + minutes * 60
        self._duration_input.setText(self._format_duration_text(total_seconds))

    def _format_duration_text(self, total_seconds: int) -> str:
        """Formata total_seconds como HH:MM:SS."""
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _parse_duration_text(self, text: str) -> int | None:
        """Parsea texto HH:MM:SS para segundos. Retorna None se invalido."""
        parts = text.strip().split(":")
        if len(parts) != 3:
            return None
        try:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            if h < 0 or m < 0 or m > 59 or s < 0 or s > 59:
                return None
            return h * 3600 + m * 60 + s
        except ValueError:
            return None

    def _refresh_ok_state(self) -> None:
        """Habilita/desabilita botao OK baseado na validacao."""
        is_datetime = self._mode_datetime.isChecked()
        is_valid = False

        if is_datetime:
            now = QDateTime.currentDateTime()
            is_valid = self._end_dt.dateTime() > now
        else:
            duration = self._parse_duration_text(self._duration_input.text())
            is_valid = duration is not None and duration > 0

        self._ok_btn.setEnabled(is_valid)
        self._err_label.setVisible(False)

    def _on_ok_clicked(self) -> None:
        """Valida e aceita o dialogo."""
        is_datetime = self._mode_datetime.isChecked()

        if is_datetime:
            now = QDateTime.currentDateTime()
            end_dt = self._end_dt.dateTime()
            if end_dt <= now:
                self._err_label.setText("Data/hora final deve ser no futuro")
                self._err_label.setVisible(True)
                return
            self.accept()
            return

        duration = self._parse_duration_text(self._duration_input.text())
        if duration is None or duration <= 0:
            self._err_label.setText("Duração inválida (formato: HH:MM:SS, deve ser > 0)")
            self._err_label.setVisible(True)
            return
        self.accept()

    # ---------- API publica ---------- #

    def is_datetime_mode(self) -> bool:
        """Retorna True se modo selecionado é Data/hora final."""
        return self._mode_datetime.isChecked()

    def end_datetime(self) -> QDateTime:
        """Retorna a data/hora final selecionada (apenas para modo datetime)."""
        return self._end_dt.dateTime()

    def total_seconds(self) -> int:
        """Retorna a duracao em segundos (apenas para modo duracao)."""
        duration = self._parse_duration_text(self._duration_input.text())
        return duration if duration is not None else 0

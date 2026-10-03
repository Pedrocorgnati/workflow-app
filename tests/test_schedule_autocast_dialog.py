"""Regression: ScheduleAutocastDialog abre sem puxar task-manager-desktop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QDialog

from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.metrics_bar.schedule_autocast_dialog import ScheduleAutocastDialog
from workflow_app.signal_bus import SignalBus

_DIALOG_SRC = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "workflow_app"
    / "metrics_bar"
    / "schedule_autocast_dialog.py"
)


def _find_by_testid(parent, testid: str):
    from PySide6.QtWidgets import QWidget

    for w in [parent, *parent.findChildren(QWidget)]:
        if w.property("testid") == testid:
            return w
    return None


def test_dialog_source_does_not_import_task_manager() -> None:
    src = _DIALOG_SRC.read_text(encoding="utf-8")
    assert "from task_manager" not in src
    assert "import task_manager" not in src


def test_dialog_constructs_without_task_manager(qapp) -> None:
    dlg = ScheduleAutocastDialog()
    assert dlg.property("testid") == "dialog-schedule-autocast"
    assert dlg.is_datetime_mode() is False
    assert dlg.total_seconds() == 5 * 3600
    assert _find_by_testid(dlg, "schedule-autocast-confirm") is not None
    assert _find_by_testid(dlg, "schedule-autocast-datetime-picker") is not None
    assert dlg._ok_btn.isEnabled() is True


def test_duration_shortcut_7d_fits_input(qapp) -> None:
    dlg = ScheduleAutocastDialog()
    shortcut = _find_by_testid(dlg, "schedule-autocast-shortcut-7d")
    assert shortcut is not None
    shortcut.click()
    assert dlg._duration_input.text() == "168:00:00"
    assert dlg.total_seconds() == 168 * 3600


def test_datetime_mode_enables_ok_for_future(qapp) -> None:
    dlg = ScheduleAutocastDialog()
    dlg._mode_datetime.setChecked(True)
    assert dlg.is_datetime_mode() is True
    # Dialog nao esta shown: isVisible() seria False no ancestral. isHidden()
    # reflete o setVisible do modo.
    assert dlg._datetime_container.isHidden() is False
    assert dlg._duration_container.isHidden() is True
    dlg._end_dt.setDateTime(QDateTime.currentDateTime().addSecs(3600))
    assert dlg._ok_btn.isEnabled() is True


def test_metrics_bar_schedule_click_constructs_dialog(qapp, monkeypatch) -> None:
    """O slot que abre o modal nao pode explodir na construcao (regressao 0ac9214)."""
    monkeypatch.setattr(
        ScheduleAutocastDialog,
        "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )
    mb = MetricsBar(SignalBus())
    mb._on_schedule_clicked()
    assert mb._schedule_end_at is None

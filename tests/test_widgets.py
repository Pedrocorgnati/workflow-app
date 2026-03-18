"""Tests for base widgets (module-02/TASK-7)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from workflow_app.domain import CommandStatus, ModelType
from workflow_app.widgets.base import (
    ModelBadge,
    ProgressBarWidget,
    StatusBadge,
    TimerWidget,
)

# ── StatusBadge ───────────────────────────────────────────────────────────────


class TestStatusBadge:
    def test_default_status(self, qapp):
        badge = StatusBadge()
        assert badge.status == CommandStatus.PENDENTE

    def test_initial_status_set(self, qapp):
        badge = StatusBadge(CommandStatus.EXECUTANDO)
        assert badge.status == CommandStatus.EXECUTANDO

    def test_set_status(self, qapp):
        badge = StatusBadge()
        badge.set_status(CommandStatus.CONCLUIDO)
        assert badge.status == CommandStatus.CONCLUIDO

    def test_all_statuses_apply_without_error(self, qapp):
        badge = StatusBadge()
        for status in CommandStatus:
            badge.set_status(status)
            assert badge.status == status

    def test_is_qwidget(self, qapp):
        badge = StatusBadge()
        assert isinstance(badge, QWidget)

    def test_label_text_changes(self, qapp):
        badge = StatusBadge(CommandStatus.PENDENTE)
        badge.set_status(CommandStatus.CONCLUIDO)
        # Label should reflect the new status
        assert badge._label.text() == "Concluido"


# ── ModelBadge ────────────────────────────────────────────────────────────────


class TestModelBadge:
    def test_default_model(self, qapp):
        badge = ModelBadge()
        assert badge.model_type == ModelType.SONNET

    def test_initial_model_set(self, qapp):
        badge = ModelBadge(ModelType.OPUS)
        assert badge.model_type == ModelType.OPUS

    def test_set_model(self, qapp):
        badge = ModelBadge()
        badge.set_model(ModelType.HAIKU)
        assert badge.model_type == ModelType.HAIKU

    def test_all_models_apply_without_error(self, qapp):
        badge = ModelBadge()
        for model in ModelType:
            badge.set_model(model)
            assert badge.model_type == model

    def test_text_reflects_model(self, qapp):
        badge = ModelBadge(ModelType.OPUS)
        assert badge.text() == "Opus"

    def test_is_qlabel(self, qapp):
        from PySide6.QtWidgets import QLabel
        badge = ModelBadge()
        assert isinstance(badge, QLabel)


# ── TimerWidget ───────────────────────────────────────────────────────────────


class TestTimerWidget:
    def test_initial_display(self, qapp):
        timer = TimerWidget()
        assert timer.text() == "00:00"
        assert timer.elapsed_seconds == 0

    def test_set_elapsed(self, qapp):
        timer = TimerWidget()
        timer.set_elapsed(90)
        assert timer.elapsed_seconds == 90
        assert timer.text() == "01:30"

    def test_reset(self, qapp):
        timer = TimerWidget()
        timer.set_elapsed(120)
        timer.reset()
        assert timer.elapsed_seconds == 0
        assert timer.text() == "00:00"

    def test_start_stop(self, qapp):
        timer = TimerWidget()
        timer.start()
        assert timer._running is True
        timer.stop()
        assert timer._running is False

    def test_stop_when_not_running_noop(self, qapp):
        timer = TimerWidget()
        timer.stop()  # Should not raise
        assert timer._running is False

    def test_start_when_running_noop(self, qapp):
        timer = TimerWidget()
        timer.start()
        timer.start()  # Should not raise / double-start
        assert timer._running is True
        timer.stop()

    def test_format_over_60_minutes(self, qapp):
        timer = TimerWidget()
        timer.set_elapsed(3661)  # 61 min 1 sec
        assert timer.text() == "61:01"

    def test_is_qlabel(self, qapp):
        from PySide6.QtWidgets import QLabel
        timer = TimerWidget()
        assert isinstance(timer, QLabel)


# ── ProgressBarWidget ─────────────────────────────────────────────────────────


class TestProgressBarWidget:
    def test_initial_state(self, qapp):
        pb = ProgressBarWidget()
        assert pb._completed == 0
        assert pb._total == 0

    def test_update_progress(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(3, 10)
        assert pb._completed == 3
        assert pb._total == 10

    def test_label_text(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(5, 20)
        assert pb._label.text() == "5/20"

    def test_bar_value_percent(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(1, 4)
        assert pb._bar.value() == 25

    def test_bar_value_zero_total(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(0, 0)
        assert pb._bar.value() == 0

    def test_bar_value_full(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(10, 10)
        assert pb._bar.value() == 100

    def test_reset(self, qapp):
        pb = ProgressBarWidget()
        pb.update_progress(5, 10)
        pb.reset()
        assert pb._completed == 0
        assert pb._total == 0
        assert pb._bar.value() == 0

    def test_is_qwidget(self, qapp):
        pb = ProgressBarWidget()
        assert isinstance(pb, QWidget)

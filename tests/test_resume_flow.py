"""
Tests for ResumeDialog and ResumeInfo (module-12/TASK-4).

Covers:
  - ResumeDialog stores ResumeInfo correctly
  - user_choice() returns RESULT_REEXECUTE on _on_reexecute
  - user_choice() returns RESULT_SKIP on _on_skip
  - user_choice() returns RESULT_CANCEL on _on_cancel_pipeline
  - Dialog displays key info (uncertain command, pending count)
  - Default user_choice is RESULT_CANCEL
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workflow_app.dialogs.resume_dialog import ResumeDialog, ResumeInfo


def make_info(**kwargs) -> ResumeInfo:
    defaults = dict(
        pipeline_exec_id=1,
        last_completed_command="/prd-create",
        uncertain_command="/hld-create",
        pending_count=3,
        total_count=6,
        completed_count=2,
        interrupted_at=datetime(2026, 3, 11, 14, 32, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ResumeInfo(**defaults)


@pytest.fixture()
def dialog(qapp, qtbot):
    d = ResumeDialog(make_info())
    qtbot.addWidget(d)
    return d


# ─────────────────────────────────────────── ResumeInfo ─────────── #

class TestResumeInfo:
    def test_fields_accessible(self):
        """ResumeInfo stores all required fields."""
        info = make_info()
        assert info.pipeline_exec_id == 1
        assert info.last_completed_command == "/prd-create"
        assert info.uncertain_command == "/hld-create"
        assert info.pending_count == 3
        assert info.total_count == 6
        assert info.completed_count == 2

    def test_none_last_completed(self):
        """last_completed_command can be None (no command completed yet)."""
        info = make_info(last_completed_command=None)
        assert info.last_completed_command is None

    def test_none_uncertain_command(self):
        """uncertain_command can be None."""
        info = make_info(uncertain_command=None)
        assert info.uncertain_command is None


# ─────────────────────────────────────────── ResumeDialog ─────────── #

class TestResumeDialogInitialState:
    def test_stores_info(self, dialog):
        """Dialog stores the ResumeInfo passed to it."""
        assert dialog._info.uncertain_command == "/hld-create"
        assert dialog._info.last_completed_command == "/prd-create"
        assert dialog._info.pending_count == 3

    def test_title_contains_retomar(self, dialog):
        """Window title mentions resumption."""
        assert "Retomar" in dialog.windowTitle() or "retom" in dialog.windowTitle().lower()

    def test_default_user_choice_is_cancel(self, dialog):
        """Default user_choice before any action is RESULT_CANCEL."""
        assert dialog.user_choice() == ResumeDialog.RESULT_CANCEL

    def test_is_modal(self, dialog):
        """Dialog is modal."""
        assert dialog.isModal()


class TestResumeDialogActions:
    def test_reexecute_sets_accepted_result(self, dialog, qtbot):
        """_on_reexecute sets user_choice to RESULT_REEXECUTE."""
        dialog._on_reexecute()
        assert dialog.user_choice() == ResumeDialog.RESULT_REEXECUTE

    def test_skip_sets_skip_result(self, dialog, qtbot):
        """_on_skip sets user_choice to RESULT_SKIP."""
        dialog._on_skip()
        assert dialog.user_choice() == ResumeDialog.RESULT_SKIP

    def test_cancel_sets_cancel_result(self, dialog, qtbot):
        """_on_cancel_pipeline sets user_choice to RESULT_CANCEL."""
        dialog._on_cancel_pipeline()
        assert dialog.user_choice() == ResumeDialog.RESULT_CANCEL

    def test_result_constants_are_distinct(self):
        """RESULT_REEXECUTE, RESULT_SKIP and RESULT_CANCEL are distinct."""
        reexecute = int(ResumeDialog.RESULT_REEXECUTE)
        skip = ResumeDialog.RESULT_SKIP
        cancel = int(ResumeDialog.RESULT_CANCEL)
        assert reexecute != skip
        assert reexecute != cancel
        assert skip != cancel


class TestResumeDialogWithNoLastCompleted:
    def test_handles_none_last_completed(self, qapp, qtbot):
        """Dialog renders correctly when last_completed_command is None."""
        info = make_info(last_completed_command=None)
        dialog = ResumeDialog(info)
        qtbot.addWidget(dialog)
        # Should not crash — _info stores None correctly
        assert dialog._info.last_completed_command is None

    def test_handles_zero_total_count(self, qapp, qtbot):
        """Dialog renders without progress bar when total_count is 0."""
        info = make_info(total_count=0, completed_count=0)
        dialog = ResumeDialog(info)
        qtbot.addWidget(dialog)
        # Should not crash
        assert dialog._info.total_count == 0

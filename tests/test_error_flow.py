"""
Tests for error UI flows (module-12/TASK-3).

Covers:
  - CommandItemWidget shows error row on ERRO status
  - Error row includes error message text
  - Error row hidden for non-ERRO statuses
  - retry_requested / cancel_requested signals are defined
  - ConfirmCancelModal can be accepted / rejected
  - ConfirmCancelModal text contains expected content
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.domain import CommandSpec, CommandStatus, ModelName


@pytest.fixture()
def spec() -> CommandSpec:
    return CommandSpec(name="/prd-create", model=ModelName.SONNET, position=1)


@pytest.fixture()
def item(spec, qapp, qtbot):
    w = CommandItemWidget(spec)
    qtbot.addWidget(w)
    w.show()
    return w


# ─────────────────────────────────────── CommandItemWidget error row ─ #

class TestCommandItemWidgetErrorRow:
    def test_error_row_hidden_by_default(self, item):
        """Error row is hidden when widget is first created."""
        assert not item._error_row.isVisible()

    def test_error_row_visible_on_erro_status(self, item):
        """Error row becomes visible when ERRO status is set."""
        item.set_status(CommandStatus.ERRO)
        assert item._error_row.isVisible()

    def test_error_row_shows_message(self, item):
        """Error row displays the provided error message."""
        item.set_status(CommandStatus.ERRO, error_message="Connection timed out")
        assert "Connection timed out" in item._error_label.text()

    def test_error_row_hidden_after_retry_sets_executando(self, item):
        """Setting EXECUTANDO after ERRO hides the error row."""
        item.set_status(CommandStatus.ERRO, error_message="err")
        item.set_status(CommandStatus.EXECUTANDO)
        assert not item._error_row.isVisible()

    def test_error_row_hidden_for_concluido(self, item):
        """CONCLUIDO status does not show error row."""
        item.set_status(CommandStatus.ERRO)
        item.set_status(CommandStatus.CONCLUIDO)
        assert not item._error_row.isVisible()

    def test_error_row_hidden_for_pulado(self, item):
        """PULADO status does not show error row."""
        item.set_status(CommandStatus.ERRO)
        item.set_status(CommandStatus.PULADO)
        assert not item._error_row.isVisible()

    def test_error_message_cleared_on_non_erro(self, item):
        """Error label text is cleared when leaving ERRO state."""
        item.set_status(CommandStatus.ERRO, error_message="timeout")
        item.set_status(CommandStatus.PENDENTE)
        assert item._error_label.text() == ""


class TestCommandItemWidgetErrorSignals:
    def test_retry_requested_signal_exists(self, item):
        """retry_requested signal is defined."""
        assert hasattr(item, "retry_requested")

    def test_cancel_requested_signal_exists(self, item):
        """cancel_requested signal is defined."""
        assert hasattr(item, "cancel_requested")

    def test_retry_requested_emits_position(self, item, qtbot):
        """Clicking retry emits retry_requested with spec.position."""
        item.set_status(CommandStatus.ERRO)
        positions: list[int] = []
        item.retry_requested.connect(positions.append)
        with qtbot.waitSignal(item.retry_requested, timeout=500):
            item._btn_retry.click()
        assert positions == [1]

    def test_skip_error_emits_position(self, item, qtbot):
        """Clicking skip in error row emits skip_requested with spec.position."""
        item.set_status(CommandStatus.ERRO)
        positions: list[int] = []
        item.skip_requested.connect(positions.append)
        with qtbot.waitSignal(item.skip_requested, timeout=500):
            item._btn_skip_err.click()
        assert positions == [1]

    def test_cancel_requested_emits(self, item, qtbot):
        """Clicking cancel emits cancel_requested (no arg)."""
        item.set_status(CommandStatus.ERRO)
        received: list[None] = []
        item.cancel_requested.connect(lambda: received.append(None))
        with qtbot.waitSignal(item.cancel_requested, timeout=500):
            item._btn_cancel_pipeline.click()
        assert len(received) == 1


# ─────────────────────────────────────── ConfirmCancelModal ─────── #

class TestConfirmCancelModal:
    def test_modal_has_expected_title(self, qapp, qtbot):
        """Dialog title contains 'Cancelar'."""
        from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
        modal = ConfirmCancelModal()
        qtbot.addWidget(modal)
        assert "Cancelar" in modal.windowTitle()

    def test_modal_has_warning_text(self, qapp, qtbot):
        """Dialog contains confirmation text."""
        from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
        modal = ConfirmCancelModal()
        qtbot.addWidget(modal)
        # Find any QLabel with the warning text
        from PySide6.QtWidgets import QLabel
        labels = modal.findChildren(QLabel)
        combined = " ".join(lbl.text() for lbl in labels)
        assert "cancelar" in combined.lower() or "pipeline" in combined.lower()

    def test_modal_accept(self, qapp, qtbot):
        """Calling accept() sets dialog result to Accepted."""
        from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
        modal = ConfirmCancelModal()
        qtbot.addWidget(modal)
        modal.accept()
        assert modal.result() == ConfirmCancelModal.DialogCode.Accepted

    def test_modal_reject(self, qapp, qtbot):
        """Calling reject() sets dialog result to Rejected."""
        from workflow_app.dialogs.confirm_cancel_modal import ConfirmCancelModal
        modal = ConfirmCancelModal()
        qtbot.addWidget(modal)
        modal.reject()
        assert modal.result() == ConfirmCancelModal.DialogCode.Rejected

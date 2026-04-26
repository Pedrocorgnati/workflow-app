"""
Tests for CommandQueueWidget (module-10/TASK-2).

Covers:
  - Initial state shows empty widget (Nenhum pipeline configurado)
  - load_pipeline() populates list and hides empty widget
  - clear_queue() returns to empty state
  - Signal slots update item statuses (command_started, completed, failed, skipped)
  - remove_requested removes the item from the list
  - skip_requested marks item as PULADO
  - Width is within min/max bounds (200–360px)
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    ModelName,
)


@pytest.fixture()
def specs() -> list[CommandSpec]:
    return [
        CommandSpec("/prd-create", ModelName.OPUS, position=1),
        CommandSpec("/hld-create", ModelName.SONNET, position=2),
        CommandSpec("/lld-create", ModelName.HAIKU, position=3),
    ]


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    return w


class TestCommandQueueWidgetInitialState:
    def test_width_within_bounds(self, widget):
        """Widget width is within min/max bounds (200–400px).

        Upper bound raised from 360→400 by TASK-050: the new DCP buttons
        (`DCP: Build Module Pipeline` / `DCP: Specific-Flow`) have spec-
        mandated literal labels wider than the previous legacy buttons.
        """
        assert 200 <= widget.width() <= 400

    def test_empty_widget_visible(self, widget):
        """Empty state widget is visible initially."""
        assert widget._empty_widget.isVisible()

    def test_list_widget_hidden(self, widget):
        """List widget is hidden initially."""
        assert not widget._list_widget.isVisible()

    def test_no_items_initially(self, widget):
        """No CommandItemWidget items initially."""
        assert len(widget._items) == 0


class TestCommandQueueWidgetLoadPipeline:
    def test_load_shows_list(self, widget, specs):
        """load_pipeline shows list widget and hides empty state."""
        widget.load_pipeline(specs)
        assert widget._list_widget.isVisible()
        assert not widget._empty_widget.isVisible()

    def test_load_creates_items(self, widget, specs):
        """load_pipeline creates one CommandItemWidget per spec."""
        widget.load_pipeline(specs)
        assert len(widget._items) == 3

    def test_load_items_have_correct_names(self, widget, specs):
        """Each loaded item displays the correct command name."""
        widget.load_pipeline(specs)
        names = [item._name_label.text() for item in widget._items]
        assert "/prd-create" in names
        assert "/hld-create" in names
        assert "/lld-create" in names

    def test_reload_replaces_existing_items(self, widget, specs):
        """Calling load_pipeline again replaces all items."""
        widget.load_pipeline(specs)
        widget.load_pipeline(specs[:1])
        assert len(widget._items) == 1


class TestCommandQueueWidgetClear:
    def test_clear_queue_returns_to_empty(self, widget, specs):
        """clear_queue() makes empty widget visible and hides list."""
        widget.load_pipeline(specs)
        widget.clear_queue()
        assert widget._empty_widget.isVisible()
        assert not widget._list_widget.isVisible()

    def test_clear_queue_removes_items(self, widget, specs):
        """clear_queue() empties the _items list."""
        widget.load_pipeline(specs)
        widget.clear_queue()
        assert len(widget._items) == 0


class TestCommandQueueWidgetStatusUpdates:
    def test_command_started_sets_executando(self, widget, specs):
        """command_started signal sets item status to EXECUTANDO."""
        widget.load_pipeline(specs)
        widget._on_command_started(0)  # index 0 → position 1
        assert widget._items[0]._status == CommandStatus.EXECUTANDO

    def test_command_completed_sets_concluido(self, widget, specs):
        """command_completed signal sets item status to CONCLUIDO."""
        widget.load_pipeline(specs)
        widget._on_command_completed(1)  # index 1 → position 2
        assert widget._items[1]._status == CommandStatus.CONCLUIDO

    def test_command_failed_sets_erro(self, widget, specs):
        """command_failed signal sets item status to ERRO."""
        widget.load_pipeline(specs)
        widget._on_command_failed(2, "timeout")  # index 2 → position 3
        assert widget._items[2]._status == CommandStatus.ERRO

    def test_command_skipped_sets_pulado(self, widget, specs):
        """command_skipped signal sets item status to PULADO."""
        widget.load_pipeline(specs)
        widget._on_command_skipped(0)  # index 0 → position 1
        assert widget._items[0]._status == CommandStatus.PULADO


class TestCommandQueueWidgetRemove:
    def test_remove_requested_removes_item(self, widget, specs):
        """_on_remove_requested removes item from list."""
        widget.load_pipeline(specs)
        widget._on_remove_requested(1)  # position 1
        assert len(widget._items) == 2

    def test_remove_last_item_shows_empty(self, widget):
        """Removing the last item returns to empty state."""
        single_spec = [CommandSpec("/cmd", ModelName.OPUS, position=1)]
        widget.load_pipeline(single_spec)
        widget._on_remove_requested(1)
        assert widget._empty_widget.isVisible()


# ────────────────────────────────────── Error flow (GAP-011) ─── #

class TestCommandQueueWidgetErrorFlow:
    """Error row signals are connected and cancel shows ConfirmCancelModal (GAP-011 fix)."""

    def test_retry_requested_resets_item_to_pendente(self, widget, specs):
        """retry_requested resets the failed item status to PENDENTE."""
        widget.load_pipeline(specs)
        # Manually set item to ERRO first
        item = widget._items[0]
        item.set_status(CommandStatus.ERRO)

        widget._on_retry_requested(1)  # position 1

        assert item._status == CommandStatus.PENDENTE

    def test_cancel_requested_shows_confirm_modal(self, widget, specs, monkeypatch):
        """_on_cancel_requested shows ConfirmCancelModal before cancelling."""
        from unittest.mock import MagicMock, patch
        widget.load_pipeline(specs)

        with patch(
            "workflow_app.command_queue.command_queue_widget.ConfirmCancelModal"
        ) as MockModal:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = MockModal.Accepted
            MockModal.return_value = mock_instance

            widget._on_cancel_requested()

            MockModal.assert_called_once()
            mock_instance.exec.assert_called_once()

    def test_pipeline_error_with_message_marks_executing_item(self, widget, specs):
        """_on_pipeline_error_with_message sets EXECUTANDO item to ERRO with message."""
        widget.load_pipeline(specs)
        item = widget._items[1]  # position 2
        item.set_status(CommandStatus.EXECUTANDO)

        widget._on_pipeline_error_with_message(0, "Command timed out")

        assert item._status == CommandStatus.ERRO

    def test_error_row_signals_exist_on_item(self, widget):
        """After load_pipeline(), item has retry_requested and cancel_requested signals."""
        single_spec = [CommandSpec("/cmd", ModelName.OPUS, position=1)]
        widget.load_pipeline(single_spec)
        item = widget._items[0]

        assert hasattr(item, "retry_requested")
        assert hasattr(item, "cancel_requested")

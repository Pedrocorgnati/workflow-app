"""Tests for drag-and-drop reordering in CommandQueueWidget (TASK-5)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QMimeData

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, InteractionType, ModelName


@pytest.fixture()
def queue_widget(qtbot):
    mock_pm = MagicMock()
    mock_pm.can_reorder.return_value = True
    w = CommandQueueWidget()
    w.set_pipeline_manager(mock_pm)
    qtbot.addWidget(w)
    specs = [
        CommandSpec("/cmd-a", ModelName.SONNET, InteractionType.AUTO, 1),
        CommandSpec("/cmd-b", ModelName.OPUS, InteractionType.AUTO, 2),
        CommandSpec("/cmd-c", ModelName.HAIKU, InteractionType.AUTO, 3),
    ]
    for spec in specs:
        w.add_command(spec)
    return w, mock_pm


def test_drag_blocked_when_cannot_reorder(qtbot):
    """Drag does not start when can_reorder returns False."""
    mock_pm = MagicMock()
    mock_pm.can_reorder.return_value = False
    w = CommandQueueWidget()
    w.set_pipeline_manager(mock_pm)
    qtbot.addWidget(w)
    spec = CommandSpec("/cmd", ModelName.SONNET, InteractionType.AUTO, 1)
    w.add_command(spec)

    item = w._items_layout.itemAt(0).widget()
    assert isinstance(item, CommandItemWidget)
    # _can_reorder_fn receives spec.position (1-based); converts to 0-based internally
    assert not item._can_reorder_fn(1)


def test_reorder_signal_emitted_on_valid_drop(queue_widget, qtbot):
    """reorder_requested is emitted with correct positions on valid drop."""
    w, mock_pm = queue_widget
    signals_received = []
    w.reorder_requested.connect(lambda f, t: signals_received.append((f, t)))

    w._items_container._drop_indicator_pos = 2
    mime = QMimeData()
    mime.setText("0")

    mock_event = MagicMock()
    mock_event.mimeData.return_value = mime
    w._on_drop(mock_event)

    assert len(signals_received) == 1
    assert signals_received[0] == (0, 2)


def test_drop_same_position_ignored(queue_widget):
    """Drop at same position does not emit reorder_requested."""
    w, _ = queue_widget
    signals_received = []
    w.reorder_requested.connect(lambda f, t: signals_received.append((f, t)))

    w._items_container._drop_indicator_pos = 1
    mime = QMimeData()
    mime.setText("1")

    mock_event = MagicMock()
    mock_event.mimeData.return_value = mime
    w._on_drop(mock_event)

    assert len(signals_received) == 0


def test_drop_indicator_pos_cleared_after_drop(queue_widget):
    """_drop_indicator_pos is cleared after drop processing."""
    w, _ = queue_widget
    w._items_container._drop_indicator_pos = 2
    mime = QMimeData()
    mime.setText("0")
    mock_event = MagicMock()
    mock_event.mimeData.return_value = mime
    w._on_drop(mock_event)
    assert w._items_container._drop_indicator_pos is None

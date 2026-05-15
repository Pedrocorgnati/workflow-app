"""Tests for QueueProgressRing widget (TASK-1 AC-1.3).

Cobre:
  - testid="queue-progress-ring" presente
  - set_progress atualiza fraction
  - fraction clamp para [0, 1]
  - sinal progress_changed emitido apenas em mudanca real
  - tooltip <= 60 chars
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.widgets.queue_progress_ring import QueueProgressRing


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_testid_present(app):
    ring = QueueProgressRing()
    assert ring.property("testid") == "queue-progress-ring"


def test_default_state(app):
    ring = QueueProgressRing()
    assert ring.done() == 0
    assert ring.total() == 0
    assert ring.fraction() == 0.0


def test_set_progress_basic(app):
    ring = QueueProgressRing()
    ring.set_progress(3, 10)
    assert ring.done() == 3
    assert ring.total() == 10
    assert ring.fraction() == pytest.approx(0.3)


def test_done_clamped_to_total(app):
    ring = QueueProgressRing()
    ring.set_progress(15, 10)
    assert ring.done() == 10
    assert ring.fraction() == 1.0


def test_negative_inputs_clamped(app):
    ring = QueueProgressRing()
    ring.set_progress(-5, -2)
    assert ring.done() == 0
    assert ring.total() == 0


def test_progress_changed_signal_dedup(app):
    ring = QueueProgressRing()
    received: list[tuple[int, int]] = []
    ring.progress_changed.connect(lambda d, t: received.append((d, t)))
    ring.set_progress(2, 5)
    ring.set_progress(2, 5)  # no-op, same values
    ring.set_progress(3, 5)
    assert received == [(2, 5), (3, 5)]


def test_tooltip_60_chars(app):
    ring = QueueProgressRing()
    assert len(ring.toolTip()) <= 60

"""Regression tests for the command-stacking cascade chokepoint fence (v2).

Root cause (recurred ~302×): `_enter_authoritative_idle` is the single place
the dot greens, but the v1 fence (`_awaiting_notify`) was checked ONLY in
`_on_force_idle`. The soft-idle timer (`_on_idle_confirmed`) and the 5s hardcap
(`_on_hardcap_expired`) reached `_enter_authoritative_idle` directly and greened
a real command still in flight, satisfying the autocast `verde+verde` gate and
stacking the next queue item into the busy CLI.

v2 fix moves the fence to the chokepoint itself: while `_awaiting_notify[ch]`
is True, NO path greens the dot unless it is the channel's own fresh
authoritative idle notify (which lowers the fence first). These tests lock that
contract across ALL feeder paths.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest -o addopts="" \
       tests/test_listener_cascade_chokepoint.py -v
(see memory workflow-app-pytest-cov-segfault: addopts="" avoids the pytest-cov
segfault; offscreen avoids needing a display.)
"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from workflow_app.signal_bus import SignalBus  # noqa: E402
from workflow_app.metrics_bar.metrics_bar import MetricsBar  # noqa: E402

CH = "interactive"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bar(qapp):
    mb = MetricsBar(signal_bus=SignalBus())
    # Simulate a real (non-helper) command in flight on T1.
    mb._idle_locked[CH] = False
    mb._command_epoch[CH] = 0.0
    mb._awaiting_notify[CH] = True
    mb._dot_interactive.set_busy(True)
    yield mb
    mb.deleteLater()


def _is_green(mb) -> bool:
    return not mb._dot_interactive.is_busy


# ── The three feeders must NOT green while the fence is up ──────────────── #

def test_soft_idle_timer_cannot_green_in_flight_command(bar):
    bar._on_idle_confirmed(CH)
    assert not _is_green(bar), "soft-idle timer greened a fenced command (cascade)"
    assert bar._awaiting_notify[CH] is True


def test_hardcap_cannot_green_in_flight_command(bar):
    bar._on_hardcap_expired(CH)
    assert not _is_green(bar), "hardcap greened a fenced command (cascade)"
    assert bar._awaiting_notify[CH] is True


def test_pure_silence_cannot_green_in_flight_command(bar):
    bar._on_force_idle(CH)
    assert not _is_green(bar), "silence heuristic greened a fenced command"
    assert bar._awaiting_notify[CH] is True


# ── A fresh authoritative notify DOES lower the fence and green ─────────── #

def _write_notify(tmp_path, *, iat, run_id="r1", state="idle"):
    p = tmp_path / "terminal-notify-interactive.json"
    p.write_text(json.dumps({
        "channel": CH, "state": state, "iat": iat, "run_id": run_id,
    }))
    return p


def test_fresh_notify_lowers_fence_then_hardcap_greens(bar, tmp_path):
    iat = time.time()
    p = _write_notify(tmp_path, iat=iat)
    bar._on_notify_file_changed(str(p))           # first-hand fileChanged
    assert bar._awaiting_notify[CH] is False, "fresh notify failed to lower fence"
    bar._on_hardcap_expired(CH)                    # now allowed
    assert _is_green(bar), "command did not green after authoritative notify"


# ── Hardening: stale/legacy/re-processed notifies must NOT lower the fence ─ #

def test_iatless_notify_does_not_lower_fence(bar, tmp_path):
    p = _write_notify(tmp_path, iat=0)             # legacy / manual write
    bar._on_notify_file_changed(str(p))
    assert bar._awaiting_notify[CH] is True, "iat-less notify lowered the fence"
    bar._on_hardcap_expired(CH)
    assert not _is_green(bar), "iat-less notify enabled a false green"


# ── Directory-rescan recovery of a SWALLOWED fileChanged (§15.6) ────────── #
# notify-terminal-idle.py writes via mkstemp+os.replace (inode swap); Linux
# inotify can drop the fileChanged entirely, surfacing the write only as a
# directoryChanged. The rescan (reprocess=True) MUST recover a genuinely-missed,
# run_id-bearing notify, or the dot stays stuck yellow forever — no CLI re-fire
# of wf-notify can recover it (every re-fire hits the same flaky inode-swap).
# This is the exact bug confirmed empirically on 2026-05-31.

def test_reprocess_recovers_swallowed_notify_and_greens(bar, tmp_path):
    """First-hand fileChanged never fired; only the directory watcher caught it.
    A run_id-bearing, never-consumed rescan must lower the fence so the dot greens.
    """
    p = _write_notify(tmp_path, iat=time.time(), run_id="recovery-1")
    bar._on_notify_file_changed(str(p), reprocess=True)   # ONLY path that fired
    assert bar._awaiting_notify[CH] is False, \
        "rescan failed to recover a swallowed authoritative notify (stuck yellow)"
    bar._on_hardcap_expired(CH)
    assert _is_green(bar), "recovered notify did not green the dot"


def test_reprocess_without_run_id_does_not_lower_fence(bar, tmp_path):
    """A run_id-LESS rescan has no dedup key, so it cannot be proven unconsumed —
    it must NOT lower the fence (legacy / manual writer)."""
    p = tmp_path / "terminal-notify-interactive.json"
    p.write_text(json.dumps({"channel": CH, "state": "idle", "iat": time.time()}))
    bar._on_notify_file_changed(str(p), reprocess=True)
    assert bar._awaiting_notify[CH] is True, "run_id-less rescan lowered the fence"
    bar._on_hardcap_expired(CH)
    assert not _is_green(bar), "run_id-less rescan enabled a false green"


def test_reprocess_of_consumed_notify_is_noop(bar, tmp_path):
    """Anti-cascade: a rescan that resurfaces an ALREADY-consumed notify (same
    run_id seen first-hand) must early-return via the dedup guard and never
    re-lower a fence legitimately re-raised by the next dispatch."""
    iat = time.time()
    p = _write_notify(tmp_path, iat=iat, run_id="consumed-1")
    bar._on_notify_file_changed(str(p))        # first-hand consumes run_id + lowers
    assert bar._awaiting_notify[CH] is False
    bar._awaiting_notify[CH] = True            # next dispatch re-raises the fence
    bar._on_notify_file_changed(str(p), reprocess=True)   # stale resurfaced rescan
    assert bar._awaiting_notify[CH] is True, \
        "rescan of a consumed run_id re-lowered the fence (cascade risk)"


def test_reprocess_stale_iat_dropped_by_epoch_fence(bar, tmp_path):
    """Even a run_id-bearing rescan must be dropped when its iat predates the
    latest dispatch epoch (cross-command stale notify)."""
    bar._command_epoch[CH] = time.time() + 100.0          # a much newer dispatch
    p = _write_notify(tmp_path, iat=time.time(), run_id="stale-epoch")
    bar._on_notify_file_changed(str(p), reprocess=True)
    assert bar._awaiting_notify[CH] is True, "epoch-stale rescan lowered the fence"
    bar._on_hardcap_expired(CH)
    assert not _is_green(bar), "epoch-stale rescan enabled a false green"


# ── Autocast interlock: never advance while any fence is up ─────────────── #

def test_autocast_interlock_holds_while_fence_up(bar):
    bar._btn_autocast.setChecked(True)
    bar._autocast_phase = "running"
    # All dots green but a fence is still up → must NOT arm the fire timer.
    bar._dot_interactive.set_busy(False)
    bar._dot_workspace.set_busy(False)
    bar._dot_workspace_xterm.set_busy(False)
    bar._awaiting_notify[CH] = True
    bar._on_dot_busy_changed(CH, False)
    assert not bar._autocast_fire_timer.isActive(), "autocast advanced with fence up"

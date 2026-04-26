"""Qt-side cooperative lock orchestrator for ``delivery.json`` (T-037).

This module is a thin Qt-aware wrapper around the canonical
``DeliveryLock`` from ``.claude/commands/delivery/_lib/lock.py`` (T-005),
loaded into the workflow-app process through
``workflow_app.delivery.lock_bridge`` so there is exactly ONE
implementation of the lock protocol in the whole repo.

Responsibilities of this service (and NOT of ``DeliveryLock`` itself):

* Own a ``QTimer`` that drives the heartbeat on the Qt event loop.
* Expose an ADT (``Acquired`` / ``Busy`` / ``LockFail``) so callers can
  pattern-match without ``try``/``except``.
* Emit Qt signals (``lock_acquired``, ``lock_released``, ``lock_lost``)
  so views can react (toasts, badges, dialogs).
* Be idempotent and never raise from ``release_and_stop()`` — it must be
  safe to call from ``MainWindow.closeEvent`` under every condition,
  including "never acquired" and "already expired externally".

Non-responsibilities (intentionally NOT in this module):

* Writing the ``locks`` block of ``delivery.json`` directly. Every
  mutation goes through ``DeliveryLock`` so invariants I-04 (null-all or
  set-all) and I-05 (ISO-8601 Z timestamps) are preserved by construction.
* Deciding whether to show a "wait or force" dialog — that is a UI
  concern for the per-module edit view shipped by T-038. T-037 only
  delivers the service + the auto-badge wiring in ``KanbanView``.
* Tracking the external holder across refreshes. ``KanbanView._populate``
  reads ``delivery.locks.holder`` from the already-loaded ``Delivery``
  model and drives ``set_lock_holder`` itself, reusing the existing
  ``QFileSystemWatcher``.

Canonical references:

* ``detailed.md §9.4`` (DCP-9.4 Locking cooperativo no workflow-app)
* ``detailed.md §5.2.10`` (cooperative lock protocol: TTL, heartbeat, CAS)
* ``detailed.md §10.5`` (concurrency mitigation workflow-app ↔ CLI)
* ``TASK-005`` lock protocol implementation
* ``TASK-037`` lock-aware workflow-app (this module)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import QObject, QTimer, Signal

from workflow_app.delivery import DeliveryLock, LockError

logger = logging.getLogger(__name__)


# ─── ADT ──────────────────────────────────────────────────────────────────── #


@dataclass(frozen=True)
class Acquired:
    """The caller now holds the lock."""

    holder: str
    acquired_at: str
    expires_at: str


@dataclass(frozen=True)
class Busy:
    """Another live holder owns the lock. ``holder`` is their id."""

    holder: str
    expires_at: str


@dataclass(frozen=True)
class LockFail:
    """Acquire failed for a reason other than contention (IO, CAS, bug)."""

    reason: str


AcquireResult = Union[Acquired, Busy, LockFail]


# ─── Service ──────────────────────────────────────────────────────────────── #


class LockService(QObject):
    """Qt orchestrator around :class:`DeliveryLock`.

    Usage (long-lock with heartbeat, typical for an edit flow)::

        service = LockService(parent=self)
        service.lock_lost.connect(self._on_lock_lost)
        result = service.try_acquire(wbs_root, purpose="workflow-app.edit")
        if isinstance(result, Acquired):
            ...  # open modal, let user edit
        elif isinstance(result, Busy):
            show_wait_dialog(result.holder, result.expires_at)
        else:
            show_error(result.reason)

        # on modal close OR on MainWindow.closeEvent:
        service.release_and_stop()

    Usage (read-only probe, for kanban refresh)::

        holder = service.read_current_holder(wbs_root)
        kanban_view.set_lock_holder(holder)

    Parameters
    ----------
    parent:
        Qt parent for ownership. ``MainWindow`` should pass ``self`` so
        the service (and its child ``QTimer``) are destroyed on app exit.
    """

    lock_acquired = Signal(str)  # emits `purpose`
    lock_released = Signal()
    lock_lost = Signal(str)  # emits `reason`

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._current_lock: Optional[DeliveryLock] = None
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setSingleShot(False)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat_tick)

    # ── Public API ─────────────────────────────────────────────────────── #

    def try_acquire(
        self,
        wbs_root: Path,
        purpose: str,
        wait: int = 5,
    ) -> AcquireResult:
        """Attempt to acquire the cooperative lock.

        On success, starts the heartbeat ``QTimer`` at
        ``DeliveryLock.heartbeat_interval`` seconds and emits
        :attr:`lock_acquired`. Returns :class:`Acquired` with the holder
        id and timestamps observed right after the write-then-CAS.

        On contention (live holder), returns :class:`Busy` with the
        offending holder and ``expires_at``. No timer, no signal.

        On IO error, race loss, bug, or double-acquire, returns
        :class:`LockFail`. No timer, no signal.

        Notes
        -----
        * ``wait=5`` matches the TASK-037 risk table ("app trava aguardando
          lock: Timeout 5s, mostrar erro"). Callers that need a different
          budget pass their own value.
        * Calling ``try_acquire`` twice without releasing in between is
          considered a programming error and returns :class:`LockFail`
          with ``reason="already holding a lock"`` (no automatic release
          of the previous lock — that would mask bugs).
        """
        if self._current_lock is not None:
            return LockFail(reason="already holding a lock")

        try:
            lock = DeliveryLock(wbs_root=wbs_root, purpose=purpose)
        except Exception as exc:  # noqa: BLE001 - constructor is pure, but be safe
            logger.exception("LockService: failed to construct DeliveryLock")
            return LockFail(reason=f"{type(exc).__name__}: {exc}")

        try:
            lock.acquire(wait=wait)
        except LockError as exc:
            snapshot = self._safe_status(lock)
            holder = snapshot.get("holder")
            expires_at = snapshot.get("expires_at") or ""
            if holder:
                return Busy(holder=holder, expires_at=expires_at)
            # Holder vanished between the failed acquire and the re-read
            # (lock was expired/released mid-flight). Surface as generic
            # failure so the caller can retry if they want.
            return LockFail(reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("LockService: unexpected error during acquire")
            return LockFail(reason=f"{type(exc).__name__}: {exc}")

        self._current_lock = lock
        # Heartbeat interval lives on the DeliveryLock instance (default
        # 60s per T-005). Convert to milliseconds for QTimer.
        self._heartbeat_timer.start(int(lock.heartbeat_interval * 1000))
        self.lock_acquired.emit(purpose)

        snap = self._safe_status(lock)
        return Acquired(
            holder=snap.get("holder") or lock.holder_id,
            acquired_at=snap.get("acquired_at") or "",
            expires_at=snap.get("expires_at") or "",
        )

    def release_and_stop(self) -> None:
        """Release the lock and stop the heartbeat.

        **Idempotent and exception-safe.** Meant to be called from
        ``MainWindow.closeEvent`` (see TASK-037 subtask "GIVEN app exit
        normal"). Calling it when no lock was ever acquired is a no-op.

        The underlying ``DeliveryLock.release`` is already a no-op if we
        are no longer the holder (TTL reclaimed, another process won the
        CAS), so this method never raises — worst case, we log and swallow.
        """
        if self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()
        lock = self._current_lock
        if lock is None:
            return
        self._current_lock = None
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            logger.exception("LockService: swallowed error during release")
        self.lock_released.emit()

    def is_held(self) -> bool:
        """Return ``True`` if ``try_acquire`` succeeded and we have not released."""
        return self._current_lock is not None

    def read_current_holder(self, wbs_root: Path) -> Optional[str]:
        """Return the current ``locks.holder`` as written on disk.

        Creates an ephemeral :class:`DeliveryLock` purely to delegate to
        ``DeliveryLock.status()``. Keeping this as a one-liner over the
        canonical class preserves the "one source of truth" invariant
        (no raw JSON reads of the ``locks`` block from Qt code).

        Returns ``None`` if ``delivery.json`` does not exist, is
        unreadable, has no holder, or any error occurs. This method never
        raises — callers (kanban refresh) must stay tolerant of a
        half-written file during an atomic rename.
        """
        try:
            probe = DeliveryLock(wbs_root=wbs_root, purpose="workflow-app.probe")
            snap = probe.status()
        except Exception:  # noqa: BLE001
            return None
        holder = snap.get("holder")
        return holder if isinstance(holder, str) and holder else None

    # ── Internals ──────────────────────────────────────────────────────── #

    def _on_heartbeat_tick(self) -> None:
        """QTimer callback. Extends the lock or surfaces a clean loss."""
        lock = self._current_lock
        if lock is None:
            # Defensive: timer fired after release. Stop it.
            self._heartbeat_timer.stop()
            return
        try:
            lock.heartbeat()
        except LockError as exc:
            # Not the holder anymore. Drop state cleanly; do NOT call
            # release() (Q4 of FASE A: release() would be semantically
            # misleading since we no longer own the lock).
            self._heartbeat_timer.stop()
            self._current_lock = None
            reason = str(exc)
            logger.warning("LockService: lock lost on heartbeat: %s", reason)
            self.lock_lost.emit(reason)
        except Exception as exc:  # noqa: BLE001
            self._heartbeat_timer.stop()
            self._current_lock = None
            reason = f"{type(exc).__name__}: {exc}"
            logger.exception("LockService: unexpected heartbeat failure")
            self.lock_lost.emit(reason)

    @staticmethod
    def _safe_status(lock: DeliveryLock) -> dict:
        """Return ``lock.status()`` but never propagate IO errors."""
        try:
            return dict(lock.status())
        except Exception:  # noqa: BLE001
            return {}


__all__ = [
    "Acquired",
    "AcquireResult",
    "Busy",
    "LockFail",
    "LockService",
]

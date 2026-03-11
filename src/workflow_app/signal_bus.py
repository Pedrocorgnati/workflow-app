"""
SignalBus — Global signal hub (Singleton).
Allows decoupled communication between components without direct references.

Usage:
    from workflow_app.signal_bus import signal_bus
    signal_bus.project_loaded.connect(my_handler)
    signal_bus.project_loaded.emit("meu-projeto")
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """Singleton global signal bus for Workflow App."""

    # ─── Config / Project ─────────────────────────────────────────────── #
    project_loaded = Signal(str)          # project_name
    project_cleared = Signal()

    # ─── Pipeline lifecycle ────────────────────────────────────────────── #
    pipeline_ready = Signal(list)         # list[CommandSpec]
    pipeline_started = Signal()
    pipeline_paused = Signal()
    pipeline_resumed = Signal()
    pipeline_completed = Signal()
    pipeline_cancelled = Signal()

    # ─── Command execution ─────────────────────────────────────────────── #
    command_started = Signal(int)         # command index
    command_completed = Signal(int)       # command index
    command_failed = Signal(int, str)     # command index, error message
    command_skipped = Signal(int)         # command index
    command_uncertain = Signal(int)       # command index (needs resume decision)

    # ─── Output / Streaming ───────────────────────────────────────────── #
    output_appended = Signal(str)         # raw vt100 text chunk
    output_cleared = Signal()

    # ─── Interactive mode ─────────────────────────────────────────────── #
    interactive_input_requested = Signal() # prompt Claude is waiting for user
    user_input_submitted = Signal(str)    # user's text response

    # ─── Metrics ──────────────────────────────────────────────────────── #
    metrics_updated = Signal(int, int)    # completed, total
    elapsed_tick = Signal(str)            # formatted HH:MM:SS

    # ─── Templates ────────────────────────────────────────────────────── #
    template_selected = Signal(list)      # list[CommandSpec]
    save_as_template_requested = Signal(list)  # list[CommandSpec]

    # ─── Notifications ────────────────────────────────────────────────── #
    toast_requested = Signal(str, str)    # message, type ("info"|"success"|"error"|"warning")

    # ─── History ──────────────────────────────────────────────────────── #
    history_panel_toggled = Signal()
    preferences_requested = Signal()



# Module-level singleton — always import `signal_bus`, never instantiate SignalBus directly
signal_bus = SignalBus()

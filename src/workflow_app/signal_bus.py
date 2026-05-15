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

    # --- Config / Project ---
    project_loaded = Signal(str)          # project_name
    project_cleared = Signal()

    # --- Pipeline lifecycle ---
    pipeline_ready = Signal(list)         # list[CommandSpec]
    pipeline_started = Signal()
    pipeline_paused = Signal()
    pipeline_resumed = Signal()
    pipeline_completed = Signal()
    pipeline_cancelled = Signal()

    # --- Pipeline status (id-based, for DB tracking) ---
    # (pipeline_id: int, status: str)
    pipeline_status_changed = Signal(int, str)

    # --- Command execution ---
    command_started = Signal(int)         # command index
    command_completed = Signal(int, bool)  # command index, success flag
    command_failed = Signal(int, str)     # command index, error message
    command_skipped = Signal(int)         # command index
    command_uncertain = Signal(int)       # command index (needs resume decision)

    # --- Command status (id-based, for DB tracking) ---
    # (command_execution_id: int, status: str)
    command_status_changed = Signal(int, str)

    # --- Output / Streaming ---
    output_cleared = Signal()
    # Chunk of text received from Claude process (pyte feed)
    output_chunk_received = Signal(str)

    # --- Interactive mode ---
    interactive_input_requested = Signal()  # prompt Claude is waiting for user
    user_input_submitted = Signal(str)    # user's text response

    # --- Metrics ---
    metrics_updated = Signal(int, int)    # completed, total
    elapsed_tick = Signal(str)            # formatted HH:MM:SS
    # MetricsSnapshot serialized as Python object (type-erased)
    metrics_snapshot = Signal(object)

    # --- Templates ---
    template_selected = Signal(list)      # list[CommandSpec]
    save_as_template_requested = Signal(list)  # list[CommandSpec]

    # --- Notifications ---
    toast_requested = Signal(str, str)    # message, type ("info"|"success"|"error"|"warning")

    # --- History ---
    history_panel_toggled = Signal()

    # --- SDK Adapter (module-08) ---
    # Emitted by _StopHook when agent terminates (command_name, exit_code)
    sdk_command_stopped = Signal(str, int)
    # Emitted by _NotificationHook with agent status ("thinking", "tool_use: X", "response")
    agent_status_updated = Signal(str)
    # Emitted by _PermissionHook when SDK requests user permission (request_data dict)
    permission_request_received = Signal(dict)

    # --- Tool Use (module-09/TASK-4) ---
    # Emitted by ToolUseHookMixin when a tool starts (tool_name)
    tool_use_started = Signal(str)
    # Emitted by ToolUseHookMixin when a tool finishes (tool_name, duration_ms)
    tool_use_completed = Signal(str, int)

    # --- Git ---
    # Git info updated (branch + last short commit)
    git_info_updated = Signal(str)

    # --- Tokens / Cost ---
    # (tokens_input: int, tokens_output: int, cost_usd: float)
    token_update = Signal(int, int, float)

    # --- Pipeline errors (module-11/TASK-2) ---
    # (pipeline_exec_id: int, error_message: str)
    pipeline_error_occurred = Signal(int, str)

    # --- Pipeline creation (module-04/TASK-4) ---
    # Emitted when a new command queue is confirmed by the user
    pipeline_created = Signal(list)           # list[CommandSpec]
    # Emitted when SYSTEM-PROGRESS.md is generated successfully
    system_progress_generated = Signal(str)   # path of generated file

    # --- Configuration (module-02/TASK-4) ---
    # Emitted when a project.json is loaded (absolute path)
    config_loaded = Signal(str)
    # Emitted when the project is unlinked
    config_unloaded = Signal()

    # --- Pipeline advance (module-12/TASK-1) ---
    # Emitted when interactive mode is ready for manual advance
    interactive_advance_ready = Signal(int)   # command_exec_id
    # Emitted by CommandQueueWidget when user clicks "Próximo"
    interactive_advance_triggered = Signal()
    # Emitted when all pipeline commands have completed
    pipeline_all_completed = Signal(int)      # pipeline_exec_id

    # --- Interactive flow (module-12/TASK-2) ---
    # Emitted by SDKWorker when Claude asks an interactive question
    interactive_prompt_received = Signal(str)  # prompt_text
    # Emitted when interactive mode ends (command completed)
    interactive_mode_ended = Signal()
    # Emitted when the active SDKWorker changes (for OutputPanel reference)
    current_worker_changed = Signal(object)   # SDKWorker instance (type-erased)

    # --- Queue expansion (module-12/TASK-5) ---
    # Emitted when new commands are appended to the queue
    queue_expanded = Signal(list)             # list[str] — command names
    # Emitted when a single command is appended
    command_added = Signal(str, int)          # command_name, position

    # --- Error recovery (module-12/TASK-6 correction) ---
    # Emitted when user requests retry of a failed command (0-based index)
    pipeline_retry_requested = Signal(int)    # command_index

    # --- MetricsBar actions (module-13/TASK-5 correction) ---
    dry_run_requested = Signal()              # user clicked [▤] Dry Run

    # --- Terminal (run command directly in persistent shell) ---
    run_command_in_terminal = Signal(str)           # sends text + Enter — interactive terminal only
    run_command_in_workspace_terminal = Signal(str) # sends text + Enter — workspace terminal only
    paste_text_in_terminal = Signal(str)            # text only (no Enter — inserts inline)
    paste_text_in_workspace_terminal = Signal(str)  # text only (no Enter) — workspace terminal
    submit_enter_to_terminal = Signal()             # bare Enter (\r) to interactive terminal
    submit_enter_to_workspace_terminal = Signal()   # bare Enter (\r) to workspace terminal
    # Blue-arrow Kimi dispatch — paste + (delay_ms) + Enter, tracked by
    # MetricsBar as a command dispatch (bumps workspace epoch + releases
    # idle lock). Use this instead of `run_command_in_workspace_terminal`
    # for the blue-arrow path because Kimi's Rich prompt swallows Enter
    # when the delay is too short. Caller picks the delay (1s default,
    # 3s when subsequent to /clear because the TUI repaint takes longer).
    kimi_blue_arrow_dispatched = Signal(str, int)   # prompt, delay_ms
    # Generic PTY sessions bound to a concrete terminal channel.
    # channel values used by the app: "interactive" | "workspace"
    terminal_output_chunk_received = Signal(str, str)  # channel, chunk
    terminal_session_started = Signal(str)             # channel
    terminal_session_finished = Signal(str)            # channel
    terminal_worker_changed = Signal(str, object)      # channel, runner

    # --- Instance selection (MetricsBar → CommandQueueWidget) ---
    # Emitted when user selects a CLI instance (e.g. "clauded", "clauded2")
    instance_selected = Signal(str)          # binary_name

    # --- Remote Server (workflow-mobile feature) ---
    # Emitted when user toggles the remote mode button (True=start, False=stop)
    remote_mode_toggle_requested = Signal(bool)
    # Emitted by RemoteServer when WebSocket server is listening ("IP:port")
    remote_server_started = Signal(str)
    # Emitted by RemoteServer when server shuts down
    remote_server_stopped = Signal()
    # Emitted when Android device connects
    remote_client_connected = Signal()
    # Emitted when Android device disconnects
    remote_client_disconnected = Signal()

    # --- DataTest debug mode ---
    datatest_toggled = Signal(bool)        # legado: True=show testid overlays, False=hide (mantido por compat; nao mais emitido pela UI)
    # Task 3 (loop 05-13-workflow-app-layout-2): toggle radio-like com 3 modos.
    # Modos: "off" (sem overlays), "all" (todos os testids), "body" (todos MENOS QAbstractButton),
    # "buttons" (APENAS QAbstractButton). Emitido pelos botoes DataTest/BodyTest/BtnTest.
    datatest_mode_changed = Signal(str)

    # --- Terminal focus (switch to output + focus terminal widget) ---
    focus_interactive_terminal = Signal()

    # --- Terminal activity / idle (status dots) ---
    # Emitted by OutputPanel._on_chunk() on every PTY data chunk — turns dot yellow.
    terminal_activity = Signal(str)   # channel ("interactive" | "workspace")
    # Emitted on the legacy heuristic path (terminal_session_finished) — starts a
    # 2s hardening window. Authoritative skill notify files no longer route
    # through this signal; they call MetricsBar._enter_authoritative_idle()
    # directly via QFileSystemWatcher and set the dot green immediately.
    terminal_force_idle = Signal(str) # channel ("interactive" | "workspace")

    # --- Autocast (header toggle) ---
    # Emitted by MetricsBar when the autocast loop wants to fire the next queue item.
    # CommandQueueWidget connects this to a programmatic click on `queue-btn-play-next`.
    autocast_step_requested = Signal()

    # Migration 2026-05-12: autocast buttons moved to play_bar (CommandQueueWidget).
    # Play bar widgets emit these; MetricsBar listens and drives the existing state
    # machine (dots + timers stay in metrics_bar). Bool carries the toggle state.
    autocast_toggle_requested = Signal(bool)
    schedule_autocast_requested = Signal()

    # MetricsBar emits while the schedule-autocast countdown is running so the
    # visible button on the play bar (CommandQueueWidget) can mirror label,
    # stylesheet and tooltip. Args: (label, stylesheet_qss, tooltip).
    schedule_autocast_visual_changed = Signal(str, str, str)

    # Emitted by MetricsBar AFTER the autocast state changed (including
    # programmatic stops via _on_autocast_arm_timeout). Play bar button uses
    # this to stay in sync with the state machine.
    autocast_state_changed = Signal(bool)


# Module-level singleton — always import `signal_bus`, never instantiate SignalBus directly
signal_bus = SignalBus()

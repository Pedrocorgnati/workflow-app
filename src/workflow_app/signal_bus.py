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
    command_completed = Signal(int)       # command index
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
    preferences_requested = Signal()

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

    # --- Autocast (module-12/TASK-1) ---
    # Emitted before autocast with the name of the next command
    autocast_advancing = Signal(str)          # next_command_name
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
    new_pipeline_requested = Signal()         # user clicked [+] New
    dry_run_requested = Signal()              # user clicked [▤] Dry Run

    # --- Terminal (run command directly in persistent shell) ---
    run_command_in_terminal = Signal(str)     # command name (sends text + Enter) — interactive terminal
    paste_text_in_terminal = Signal(str)      # text only (no Enter — inserts inline)
    # Generic PTY sessions bound to a concrete terminal channel.
    # channel values used by the app: "interactive" | "autocast"
    terminal_output_chunk_received = Signal(str, str)  # channel, chunk
    terminal_session_started = Signal(str)             # channel
    terminal_session_finished = Signal(str)            # channel
    terminal_worker_changed = Signal(str, object)      # channel, runner

    # --- Instance selection (MetricsBar → CommandQueueWidget) ---
    # Emitted when user selects a CLI instance (e.g. "clauded", "codex")
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
    datatest_toggled = Signal(bool)        # True=show testid overlays, False=hide

    # --- Terminal focus (switch to output + focus terminal widget) ---
    focus_interactive_terminal = Signal()


# Module-level singleton — always import `signal_bus`, never instantiate SignalBus directly
signal_bus = SignalBus()

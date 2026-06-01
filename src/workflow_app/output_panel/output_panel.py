"""
OutputPanel — Embedded terminal with PersistentShell + pyte rendering.

Architecture:
  - PersistentShell: always-on bash/zsh PTY session
      * Key events → shell stdin when no pipeline running
      * User can type "claude /cmd" directly, or use the sidebar
  - PtyRunner (via PipelineManager): spawns claude commands
      * While running: key events → claude PTY stdin instead
      * pyte renders TUI output (spinners, menus, cursor moves)
  - QTimer at 20fps: flushes pyte → TerminalCanvas (QPainter grid)
  - TerminalCanvas: pixel-perfect character grid, zero gaps between rows

Input:
  - Typing directly in the terminal forwards to PTY
  - Ctrl+Shift+V pastes clipboard content to PTY (with bracketed paste support)
  - Right-click → Colar also pastes
  - Interactive pipeline responses work the same way (keys routed to runner)
"""

from __future__ import annotations

import pathlib
import re
import time
from typing import Any

import pyte
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from workflow_app.app_instance import APP_SESSION_ID
from workflow_app.output_panel.enhanced_screen import EnhancedScreen
from workflow_app.output_panel.persistent_shell import PersistentShell
from workflow_app.output_panel.terminal_canvas import Cell, TerminalCanvas
from workflow_app.signal_bus import signal_bus
from workflow_app.terminal_helpers import HELPER_COMMANDS, is_helper_command


def _find_systemforge_root() -> str | None:
    candidate = pathlib.Path(__file__).resolve().parent
    while candidate != candidate.parent:
        if (
            (candidate / ".claude" / "commands").is_dir()
            and (candidate / "ai-forge").is_dir()
            and (candidate / "CLAUDE.md").is_file()
        ):
            return str(candidate)
        candidate = candidate.parent
    return None


_TERMINAL_COLS = 80
_TERMINAL_ROWS = 24

DEFAULT_MAX_LINES = 10_000

# Bracketed paste mode bit (DEC 2004)
_BRACKETED_PASTE_MODE = 2004 << 5

# Catalogo de erros fatais conhecidos do CLI (Claude Code / Anthropic).
# Quando bate, emitimos terminal_force_failed e o autocast aborta — sem
# isso, o CLI imprime a mensagem e morre, PTY vai amarelo->verde e o
# autocast interpreta como "comando completou" e detona a fila inteira.
# Regex compilado uma vez por modulo, case-insensitive, sem multiline.
_FATAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "AUTH_SUBSCRIPTION_DISABLED",
        re.compile(
            r"organization has disabled (?:Claude )?subscription access",
            re.IGNORECASE,
        ),
    ),
    (
        "AUTH_API_KEY_REQUIRED",
        re.compile(r"Use an Anthropic API key instead", re.IGNORECASE),
    ),
    (
        "AUTH_INVALID_API_KEY",
        re.compile(
            r"\b(invalid api key|authentication[_ ]error|unauthorized)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "AUTH_LOGIN_EXPIRED",
        re.compile(
            r"(login (?:expired|required|to continue)|please (?:run|log) ?in|please log[ -]?in)",
            re.IGNORECASE,
        ),
    ),
    (
        "CREDIT_BALANCE_LOW",
        re.compile(r"credit balance is too low", re.IGNORECASE),
    ),
    (
        "USAGE_LIMIT_REACHED",
        re.compile(
            r"(usage limit (?:reached|exceeded)|monthly limit|quota exceeded)",
            re.IGNORECASE,
        ),
    ),
    (
        "RATE_LIMIT",
        re.compile(
            r"(rate[ _-]?limit(?:ed)?|429 too many requests|too many requests)",
            re.IGNORECASE,
        ),
    ),
)


class OutputPanel(QWidget):
    """Terminal panel: persistent shell + optional pipeline runner overlay."""

    def __init__(
        self,
        parent: QWidget | None = None,
        workspace_mode: bool = False,
        channel_override: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace_mode = workspace_mode
        # Canal logico. Por padrao deriva de workspace_mode (T1=interactive,
        # T2=workspace). `channel_override` permite um terceiro painel pyte
        # (T3/Codex) declarar o canal "workspace_xterm" mantendo o wiring de
        # workspace_mode, sem colidir/ecoar com o T2 (ver _connect_signals).
        # O nome do canal e contrato com MetricsBar (dot _dot_workspace_xterm),
        # notify (terminal-notify-workspace-xterm.json) e recovery_prompt.
        default_channel = "workspace" if workspace_mode else "interactive"
        self._channel = channel_override or default_channel
        self.setObjectName("WorkspacePanel" if workspace_mode else "OutputPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("background-color: #18181B;")

        self._max_lines = DEFAULT_MAX_LINES
        self._pipeline_runner: object | None = None  # active PtyRunner, if any
        self._runner_active: bool = False
        self._cols: int = _TERMINAL_COLS
        self._rows: int = _TERMINAL_ROWS

        # ── pyte virtual terminal (EnhancedScreen with alt-screen support) ── #
        self._screen = EnhancedScreen(
            self._cols, self._rows, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(50)  # 20 fps
        self._render_timer.timeout.connect(self._flush_pyte)

        # ── Heuristic 2s idle timer (interactive + workspace_xterm) ─ #
        # Detects "PTY went silent for 2s" → fires terminal_force_idle.
        # Used by Claude (interactive/T1) and Codex (workspace_xterm/T3),
        # both of which go genuinely silent post-command. NOT used by the
        # plain workspace channel (Kimi/T2) — see `_on_chunk` gate.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(2_000)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

        # ── Resize debounce timer ──────────────────────────────────────── #
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)  # 150ms debounce
        self._resize_timer.timeout.connect(self._apply_pending_resize)
        self._pending_cols: int = self._cols
        self._pending_rows: int = self._rows

        # ── Persistent shell ──────────────────────────────────────────── #
        # Shell is created here but NOT started until showEvent fires with
        # real widget geometry. Starting early with fallback cols/rows makes
        # Claude Code (and any TUI) render its banner at the wrong width,
        # which then wraps/duplicates lines forever.
        # parent=self mete o QObject do shell na ownership tree do panel
        # (cleanup adicional via shutdown() em aboutToQuit — ver main_window.main()).
        self._shell: PersistentShell | None = None
        # Per-channel WF_CHANNEL_OVERRIDE binding. Injected at PTY spawn so
        # every Bash subprocess the embedded CLI starts (Claude in T1, Kimi
        # in T2) inherits the correct channel. Without this, the bash block
        # in `## FASE FINAL — Autocast contract` defaults to `interactive`
        # and the workspace listener never receives the workspace notify
        # (canonical bug: listener-workspace stuck yellow after a Kimi run).
        # Bound explicitly for both modes so a stale env from the parent
        # process can never bleed in. See ai-forge/rules/workflow-app-listeners.md §2.4.
        self._shell = PersistentShell(
            cols=self._cols,
            rows=self._rows,
            cwd=_find_systemforge_root(),
            extra_env={
                "WF_CHANNEL_OVERRIDE": self._channel,
                # Per-instance session ID so wf-notify.sh writes to this
                # instance's IPC subdirectory (~/.workflow-app/session-<pid>/).
                # Without this, every open workflow-app instance watches the
                # same notify files and fires the recovery prompt simultaneously
                # when any one instance encounters a failure.
                "WF_APP_SESSION_ID": APP_SESSION_ID,
            },
            parent=self,
        )
        self._shell.output_received.connect(self._on_chunk)
        self._shell_started: bool = False

        # Pattern matcher de falhas fatais (auth/credit/rate-limit). Guardamos
        # o ultimo reason emitido para nao disparar terminal_force_failed
        # repetidamente enquanto o mesmo erro permanecer na tela. Reset em
        # nova sessao do pipeline (_on_pipeline_started) e ao limpar pyte.
        self._last_failure_reason: str | None = None

        # Early-exit watcher (Camada 3): quando um dispatch programatico
        # acontece, registramos o instante e o volume de bytes recebidos
        # desde entao. Se o PTY vai para idle muito rapido com poucos bytes
        # — claro sinal de CLI que morreu cedo (auth/credit) sem casar com
        # nenhum pattern conhecido — dispara terminal_force_failed.
        self._dispatch_ts: float | None = None
        self._bytes_since_dispatch: int = 0

        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._terminal = TerminalCanvas()
        self._terminal.setProperty(
            "testid",
            {
                "interactive": "terminal-interactive-output",
                "workspace": "terminal-workspace-output",
                "workspace_xterm": "terminal-codex-output-canvas",
            }.get(self._channel, "terminal-interactive-output"),
        )
        self._terminal.raw_key_pressed.connect(self._on_raw_key)
        layout.addWidget(self._terminal, stretch=1)

        # Vertical scrollbar
        self._scrollbar = QScrollBar(Qt.Orientation.Vertical)
        self._scrollbar.setStyleSheet(
            "QScrollBar:vertical { background: #0D1117; width: 10px; }"
            "QScrollBar::handle:vertical { background: #3F3F46; min-height: 20px; border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #52525B; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #0D1117; }"
        )
        self._terminal.set_scrollbar(self._scrollbar)
        layout.addWidget(self._scrollbar)

        QTimer.singleShot(0, self._schedule_resize)

    def ensure_shell_started(self) -> None:
        """Force-start the persistent shell, idempotently, without a showEvent.

        Normalmente o shell so inicia no primeiro showEvent com geometria real
        (evita a quebra "banner renderizado a 220 cols, area visivel 130 cols"
        do Claude Code / qualquer TUI). Mas o T3 (Codex, canal workspace_xterm)
        nasce colapsado (sizes [1, 0]) e pode nunca receber um showEvent util,
        entao a rota imperativa MainWindow._xterm_inject_text chama este metodo
        antes de injetar. Geometria colapsada (recompute_grid == 0) cai no
        fallback 80x24 — start() nunca spawna a CLI com width 0.

        Idempotente: re-chamadas saem cedo via `_shell_started`.
        """
        if self._shell_started or self._shell is None:
            return

        layout = self.layout()
        if layout is not None:
            layout.activate()

        cols, rows = self._terminal.recompute_grid()
        if cols > 0 and rows > 0:
            self._cols = cols
            self._rows = rows
            try:
                self._screen.resize(lines=rows, columns=cols)
            except Exception:  # noqa: BLE001
                self._screen = EnhancedScreen(cols, rows, history=5000)
                self._stream = pyte.ByteStream(self._screen)
                self._history_cursor = 0
                self._has_pending_render = False
            self._shell.resize(cols, rows)
        self._shell.start()
        self._shell_started = True

    def showEvent(self, event) -> None:  # noqa: N802
        """Start the persistent shell only after real geometry is known.

        On the first show, force the layout to settle, recompute cols/rows
        from actual pixel size, apply that size synchronously to pyte + PTY,
        and only then spawn the shell. This avoids the Claude Code / TUI
        "banner rendered at 220 cols, visible area is 130 cols" breakage.
        """
        super().showEvent(event)
        self.ensure_shell_started()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_resize()

    def _schedule_resize(self) -> None:
        """Recalculate terminal geometry and apply atomically.

        Apply directly (no QTimer debounce): the 150ms window between Qt
        geometry update and PTY size creates an incoherence frame where
        TUIs render at the old width but receive new SIGWINCH soon after,
        triggering line-duplication and cursor desync. The `_resize_timer`
        is intentionally left instantiated to avoid legacy breakage but
        is no longer started here.
        """
        cols, rows = self._terminal.recompute_grid()
        if cols != self._cols or rows != self._rows:
            self._pending_cols = cols
            self._pending_rows = rows
            self._apply_pending_resize()

    def _apply_pending_resize(self) -> None:
        """Apply the pending resize atomically in a single frame.

        Order is shell -> screen -> recompute_grid -> update so the PTY
        SIGWINCH is delivered before pyte resizes its buffer. Inverting
        this (screen first) leaves pyte with a buffer the PTY hasn't
        acknowledged, so the next render flushes onto the wrong grid.
        """
        cols = self._pending_cols
        rows = self._pending_rows
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows

        # Resize shell PTY first (sends SIGWINCH so the TUI re-renders for
        # the new geometry before pyte processes the next chunk).
        if self._shell is not None:
            self._shell.resize(cols, rows)
        if self._pipeline_runner is not None:
            resize = getattr(self._pipeline_runner, "resize", None)
            if callable(resize):
                resize(cols, rows)

        # Then resize pyte screen (preserves buffer where possible).
        try:
            self._screen.resize(lines=rows, columns=cols)
        except Exception:  # noqa: BLE001
            self._screen = EnhancedScreen(cols, rows, history=5000)
            self._stream = pyte.ByteStream(self._screen)
            self._history_cursor = 0
            self._has_pending_render = False

        # Force the canvas to recompute its grid against the new cols/rows
        # and repaint in the same frame.
        if self._terminal is not None:
            self._terminal.recompute_grid()
            self._terminal.update()

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        signal_bus.terminal_output_chunk_received.connect(self._on_terminal_output_chunk)
        signal_bus.terminal_session_started.connect(self._on_terminal_session_started)
        signal_bus.terminal_session_finished.connect(self._on_terminal_session_finished)
        signal_bus.terminal_worker_changed.connect(self._on_terminal_worker_changed)
        if not self._workspace_mode:
            signal_bus.output_cleared.connect(self.clear)
            signal_bus.pipeline_started.connect(self._on_pipeline_started)
            signal_bus.pipeline_completed.connect(self._on_pipeline_completed)
            signal_bus.pipeline_cancelled.connect(self._on_pipeline_completed)
            signal_bus.output_chunk_received.connect(self._on_pipeline_chunk)
            signal_bus.current_worker_changed.connect(self.set_current_worker)
            signal_bus.command_status_changed.connect(self._on_command_status_changed)
            signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error)
            signal_bus.run_command_in_terminal.connect(self._run_shell_command)
            signal_bus.paste_text_in_terminal.connect(self._on_paste_text)
            signal_bus.submit_enter_to_terminal.connect(self._send_enter_to_shell)
        elif self._channel == "workspace":
            signal_bus.run_command_in_workspace_terminal.connect(self._run_shell_command)
            signal_bus.paste_text_in_workspace_terminal.connect(self._on_paste_text)
            signal_bus.submit_enter_to_workspace_terminal.connect(self._send_enter_to_shell)
            signal_bus.kimi_blue_arrow_dispatched.connect(self._run_kimi_blue_arrow)
        # T3 (workspace_xterm / Codex): NAO assina os sinais de dispatch do T2.
        # O texto chega pela rota imperativa MainWindow._xterm_inject_text
        # (-> _shell.send_raw direto), que tambem arma a janela de early-exit
        # via arm_dispatch_window. Assinar os sinais do T2 aqui faria o T3
        # ecoar todo comando/paste/Kimi-blue-arrow do T2 (bug de eco). Os
        # sinais de chunk/sessao (acima) ja sao filtrados por self._channel.

    # ─────────────────────────────────────────────────────── Key routing ─ #

    def _on_raw_key(self, data: bytes) -> None:
        """Route key to pipeline runner (if active) or persistent shell.

        Wraps clipboard paste in bracketed paste sequences if the shell
        has enabled bracketed paste mode (DEC 2004).
        """
        if self._runner_active and self._pipeline_runner is not None:
            send = getattr(self._pipeline_runner, "send_raw", None)
            if callable(send):
                send(data)
        elif self._shell is not None:
            self._shell.send_raw(data)

    def _on_paste_text(self, text: str) -> None:
        """Route pasted text to the active PTY session or the shell.

        Wraps in bracketed paste sequences (ESC[200~ ... ESC[201~) when the
        terminal has enabled DEC 2004 bracketed paste mode.
        """
        if not text:
            return
        data = text.encode("utf-8", errors="replace")

        # Wrap in bracketed paste if mode is active
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"

        if self._runner_active and self._pipeline_runner is not None:
            send = getattr(self._pipeline_runner, "send_raw", None)
            if callable(send):
                send(data)
                return
        if self._shell is not None:
            self._shell.send_raw(data)

    # Helpers — no notify file, brief output, must NOT trigger early-exit.
    # Canonical vocabulary lives in workflow_app.terminal_helpers; this is a
    # back-compat alias so existing references keep resolving.
    _HELPER_COMMANDS: tuple[str, ...] = HELPER_COMMANDS
    # Delay before the submitting Enter (\r) is sent as a standalone keypress
    # after a pasted command. Ink CLIs (Claude Code) buffer the bracketed
    # paste block and swallow a same-tick \r; 80ms proved too tight under
    # load and let directives stack unsubmitted in the prompt. A larger,
    # named delay makes the Enter land reliably. Ver workflow-app-listeners.md
    # §2.6b (anti command-stacking).
    _ENTER_SUBMIT_DELAY_MS: int = 250

    @staticmethod
    def _is_helper_command(cmd: str) -> bool:
        """Delegates to the canonical predicate (workflow_app.terminal_helpers)."""
        return is_helper_command(cmd)

    def _run_shell_command(self, command: str) -> None:
        """Send a command to the persistent shell, when available.

        Wraps the payload in bracketed paste markers (ESC[200~…ESC[201~) when
        DEC 2004 is active, then always schedules the submitting Enter (\r) as
        a separate write. Ink-based CLIs (Claude Code) buffer the paste block
        and swallow a trailing \r that arrives in the same chunk, so the queue
        run trigger would type the command but never submit it. A delayed
        singleShot guarantees the Enter lands as a standalone keypress in both
        BP and non-BP modes.
        """
        if self._shell is None:
            return
        data = command.encode("utf-8", errors="replace")
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._shell.send_raw(data)
        QTimer.singleShot(self._ENTER_SUBMIT_DELAY_MS, self._send_enter_to_shell)
        # Camada 3: marca o dispatch para o early-exit watcher. Reset do
        # ultimo reason tambem — novo dispatch, nova janela de erro.
        # Helpers (/clear, /model, /effort, cd, CLI launches) are exempt:
        # they finish fast by design and would false-trigger EARLY_EXIT —
        # vermelho sticky + autocast travado (workflow-app-listeners.md §16.1:
        # EARLY_EXIT fica fora de RECOVERY_REASONS, entao nao auto-recupera).
        if not self._is_helper_command(command):
            self._dispatch_ts = time.monotonic()
            self._bytes_since_dispatch = 0
            self._last_failure_reason = None
        else:
            # Disarma explicitamente: um _dispatch_ts stale de um comando
            # real anterior nao pode false-firar EARLY_EXIT durante o helper.
            self._dispatch_ts = None

    def arm_dispatch_window(self, command: str) -> None:
        """Arma a janela do early-exit watcher (Camada 3) para um dispatch
        imperativo externo, espelhando o bloco de `_run_shell_command`.

        Usado pelo T3 (Codex / canal workspace_xterm): o texto chega via
        MainWindow._xterm_inject_text -> _shell.send_raw direto, SEM passar por
        `_run_shell_command`, entao sem isto `_dispatch_ts` nunca seria setado
        e um Codex que morre cedo (auth/credit) iria para idle->verde silencioso
        em vez de vermelho (EARLY_EXIT). Helpers (/clear, /model, launcher
        codex/codex-high, cd) ficam isentos para nao false-firar EARLY_EXIT
        (workflow-app-listeners.md §16.1: EARLY_EXIT fica fora de
        RECOVERY_REASONS, entao nao auto-recupera).
        """
        if self._is_helper_command(command):
            # Disarma: um _dispatch_ts stale de um comando real anterior nao
            # pode false-firar EARLY_EXIT durante o helper.
            self._dispatch_ts = None
            return
        self._dispatch_ts = time.monotonic()
        self._bytes_since_dispatch = 0
        self._last_failure_reason = None

    def _send_enter_to_shell(self) -> None:
        """Send a bare \r to the persistent shell if it is still alive."""
        if self._shell is not None:
            self._shell.send_raw(b"\r")

    def _run_kimi_blue_arrow(self, prompt: str, delay_ms: int) -> None:
        """Blue-arrow Kimi dispatch — paste + delayed Enter.

        Kimi's Rich/textual prompt sometimes swallows Enter when it arrives
        too early (Ink CLIs buffer the paste block and an Enter on the same
        tick gets eaten before the /skill: line is fully composed). The
        delay is supplied by the caller — typically 1000ms, or 3000ms when
        the dispatch is subsequent to /clear (Kimi takes longer to render
        the prompt right after a clear because the TUI repaints fully).
        """
        if self._shell is None:
            return
        data = prompt.encode("utf-8", errors="replace")
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._shell.send_raw(data)
        QTimer.singleShot(delay_ms, self, self._send_enter_to_shell)

    def _on_terminal_output_chunk(self, channel: str, chunk: str) -> None:
        """Render a PTY chunk for the bound terminal channel."""
        if channel == self._channel:
            self._on_chunk(chunk)

    def _on_terminal_session_started(self, channel: str) -> None:
        """Attach this panel to an externally managed PTY session."""
        if channel != self._channel:
            return
        self._runner_active = True
        self._idle_timer.stop()
        # Disconnect shell output to prevent mixing with runner output
        if self._shell is not None:
            try:
                self._shell.output_received.disconnect(self._on_chunk)
            except RuntimeError:
                pass  # already disconnected
        self._reset_pyte()

    def _on_terminal_session_finished(self, channel: str) -> None:
        """Detach this panel from an externally managed PTY session."""
        if channel != self._channel:
            return
        self._render_timer.stop()
        if self._has_pending_render:
            self._flush_pyte()
        self._runner_active = False
        self._pipeline_runner = None
        self._reset_pyte()
        # Reconnect shell output after runner session ends
        if self._shell is not None:
            try:
                self._shell.output_received.connect(self._on_chunk)
            except RuntimeError:
                pass  # already connected

    def _on_terminal_worker_changed(self, channel: str, worker: object) -> None:
        """Update the PTY target for keyboard routing on this panel."""
        if channel == self._channel:
            self.set_current_worker(worker)

    # ─────────────────────────────────── pyte → TerminalCanvas rendering ─ #

    def _pyte_row_to_cells(self, row_dict: dict[int, Any]) -> list[Cell]:
        """Convert a pyte buffer row to a list of Cell objects."""
        if not row_dict:
            return [Cell.empty() for _ in range(self._cols)]
        max_col = max(row_dict.keys()) if row_dict else 0
        cells: list[Cell] = []
        col = 0
        while col <= max(max_col, self._cols - 1):
            ch = row_dict.get(col)
            if ch is not None:
                cell = Cell.from_pyte(ch)
                cells.append(cell)
                if cell.wide:
                    cells.append(None)  # type: ignore[arg-type]  # placeholder for wide char
                    col += 2
                else:
                    col += 1
            else:
                cells.append(Cell.empty())
                col += 1
        # Pad to cols
        while len(cells) < self._cols:
            cells.append(Cell.empty())
        return cells[:self._cols]

    def _on_chunk(self, chunk: str) -> None:
        """Feed a chunk (from shell or pipeline) to pyte and schedule render.

        Heuristic 2s idle timer is armed for the interactive channel (Claude
        Code, T1) AND the workspace_xterm channel (Codex, T3). Both go
        genuinely silent when a command finishes, so the 2s timer + soft fire
        correctly emit terminal_force_idle (dot green) when nothing else emits
        a notify file for that channel. This is the heuristic green path that
        MetricsBar documents for T1 + T3 (metrics_bar.py: "OutputPanel arm a
        2s idle timer on output"). Sem isto, o dot do T3 fica preso em amarelo
        (stuck-yellow) e o early-exit watcher do Codex nunca dispara.

        Workspace (Kimi, T2) does NOT use this heuristic: Kimi's input prompt
        emits subtle PTY bytes indefinitely (cursor, ANSI repaints), so a
        silence-based heuristic never fires AND collides with notify
        hardening. Workspace relies on the explicit 5s post-notify timer.
        """
        try:
            self._stream.feed(chunk.encode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return
        self._has_pending_render = True
        if not self._render_timer.isActive():
            self._render_timer.start()
        if not self._runner_active and self._channel in ("interactive", "workspace_xterm"):
            self._idle_timer.start()
        signal_bus.terminal_activity.emit(self._channel)
        if self._dispatch_ts is not None:
            self._bytes_since_dispatch += len(chunk)
        self._scan_chunk_for_fatal(chunk)

    # Camada 3: thresholds do early-exit watcher. Calibrados para o caso
    # "claude code morre por auth/credit em < 1s emitindo ~300 bytes".
    # Comandos reais do canonical loop (loop, dcp:*, execute-task) emitem
    # kilobytes ao longo de varios segundos; comandos triviais legitimos
    # (slash command que so imprime ack) raramente ficam abaixo dos dois
    # limites simultaneamente. Janela conservadora para minimizar falsos
    # positivos — se nao bate, idle segue caminho normal.
    _EARLY_EXIT_BYTES_THRESHOLD = 512   # crash real: 0-300 bytes; silencio normal: mais
    _EARLY_EXIT_TIME_THRESHOLD_S = 4.0  # crash real: < 2s; primeira tool call: > 4s tipicamente

    def _on_idle_timeout(self) -> None:
        """Callback do _idle_timer (2s de silencio do PTY).

        Caminho normal: emite terminal_force_idle (dot fica verde).
        Caminho early-exit: se houve um dispatch programatico recente e
        o PTY emitiu poucos bytes em pouco tempo, e a Camada 1 nao casou
        nada, emite terminal_force_failed com EARLY_EXIT — rede de
        seguranca para erros novos do CLI que ainda nao temos pattern.
        """
        if (
            self._dispatch_ts is not None
            and self._last_failure_reason is None
            and self._bytes_since_dispatch < self._EARLY_EXIT_BYTES_THRESHOLD
            and (time.monotonic() - self._dispatch_ts) < self._EARLY_EXIT_TIME_THRESHOLD_S
        ):
            self._last_failure_reason = "EARLY_EXIT"
            self._dispatch_ts = None
            signal_bus.terminal_force_failed.emit(self._channel, "EARLY_EXIT")
            return
        # Consome o dispatch (o comando rodou de verdade — proximo dispatch
        # reabre a janela). Sem isso, um dispatch antigo + silencio futuro
        # poderia disparar EARLY_EXIT espuriamente.
        self._dispatch_ts = None
        signal_bus.terminal_force_idle.emit(self._channel)

    def _scan_chunk_for_fatal(self, chunk: str) -> None:
        """Camada 1 do abort de autocast por erro fatal do CLI.

        Varre o chunk do PTY por padroes conhecidos de erro de auth,
        credito, rate-limit. Quando bate emite terminal_force_failed,
        que ativa o caminho canonico documentado em
        ai-forge/rules/workflow-app-listeners.md §3 (dot vermelho +
        autocast_abort_requested -> CommandQueueWidget desliga o botao).

        Idempotente por chunk: se o mesmo reason ja foi emitido nesta
        sessao do PTY, ignora — evita re-disparar enquanto a mensagem
        ainda esta na tela e o PTY emite ANSI repaints.
        """
        if not chunk:
            return
        for reason, pattern in _FATAL_PATTERNS:
            if not pattern.search(chunk):
                continue
            if self._last_failure_reason == reason:
                return
            self._last_failure_reason = reason
            signal_bus.terminal_force_failed.emit(self._channel, reason)
            return

    def _on_pipeline_chunk(self, chunk: str) -> None:
        """Chunk from the pipeline runner (separate signal from shell)."""
        self._on_chunk(chunk)

    def _flush_pyte(self) -> None:
        if not self._has_pending_render:
            return
        self._has_pending_render = False

        # ── 1. Append history lines that scrolled off ──────────────────── #
        history_top = list(self._screen.history.top)
        new_count = len(history_top) - self._history_cursor
        if new_count > 0:
            new_lines: list[list[Cell]] = []
            for line_dict in history_top[self._history_cursor:]:
                new_lines.append(self._pyte_row_to_cells(dict(line_dict)))
            self._terminal.append_scrollback(new_lines)
            self._history_cursor = len(history_top)

        # ── 2. Build visible buffer as Cell grid ───────────────────────── #
        term_cursor_row = self._screen.cursor.y
        term_cursor_col = self._screen.cursor.x

        visible_lines: list[list[Cell]] = []
        for row_idx in range(self._screen.lines):
            row = self._screen.buffer.get(row_idx) or {}
            visible_lines.append(self._pyte_row_to_cells(dict(row)))

        self._terminal.set_visible_lines(
            visible_lines,
            cursor_row=term_cursor_row,
            cursor_col=term_cursor_col,
        )
        self._terminal.scroll_to_bottom()

    # ─────────────────────────────────────────────────── Pipeline events ─ #

    def _on_pipeline_started(self) -> None:
        self._runner_active = True
        self._idle_timer.stop()
        self._last_failure_reason = None
        if self._shell is not None:
            try:
                self._shell.output_received.disconnect(self._on_chunk)
            except RuntimeError:
                pass
        self._reset_pyte()
        self._terminal.setFocus()

    def _on_pipeline_error(self, _exec_id: int, message: str) -> None:
        pass  # errors visible in the terminal output itself

    def _on_pipeline_completed(self) -> None:
        self._render_timer.stop()
        if self._has_pending_render:
            self._flush_pyte()
        self._runner_active = False
        self._pipeline_runner = None
        self._reset_pyte()
        if self._shell is not None:
            try:
                self._shell.output_received.connect(self._on_chunk)
            except RuntimeError:
                pass
        self._terminal.setFocus()

    def _on_command_status_changed(self, _cmd_exec_id: int, status: str) -> None:
        pass  # status visible in command queue sidebar

    def _reset_pyte(self) -> None:
        """Reset pyte state (keeps terminal canvas content intact)."""
        self._screen = EnhancedScreen(
            self._cols, self._rows, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False
        self._render_timer.stop()

    # ─────────────────────────────────────────────────────── Public API ─ #

    def append_output(self, text: str) -> None:
        """Feed text through pyte for proper rendering."""
        self._on_chunk(text)

    def clear(self) -> None:
        """Clear the terminal display and reset pyte."""
        self._terminal.clear_all()
        self._reset_pyte()

    def set_max_lines(self, max_lines: int) -> None:
        self._max_lines = max_lines

    def set_interactive_mode(self, active: bool) -> None:
        pass  # no-op: input handled directly via terminal keyboard

    def set_current_worker(self, worker: object) -> None:
        self._pipeline_runner = worker
        resize = getattr(worker, "resize", None)
        if callable(resize):
            resize(self._cols, self._rows)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Cleanup garantido do PTY shell + process group.

        Chamado em dois caminhos: (a) closeEvent (quando recebido pelo panel),
        (b) QApplication.aboutToQuit conectado em main_window.main() — este eh
        o caminho confiavel para teardown no fechamento do app, ja que widgets
        filhos nao recebem closeEvent garantido em todos os SOs.

        Mata o process group inteiro (start_new_session=True faz o shell ser
        lider de sessao). Sem isso, processos filhos do shell (claude, vim, etc)
        vazariam orfaos.

        Idempotente: re-chamadas saem cedo via `_shell is None`.
        """
        import os
        import signal as _sig

        self._render_timer.stop()
        self._resize_timer.stop()
        if self._shell is None:
            return
        proc = getattr(self._shell, "_proc", None)
        # SIGTERM no process group (cobre filhos do shell).
        if proc is not None and proc.poll() is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, _sig.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        # Cleanup interno (fecha FD, desliga notifier, terminate o subprocess).
        try:
            self._shell.terminate()
        except Exception:  # noqa: BLE001
            pass
        # Fallback: se ainda vivo apos terminate, SIGKILL no grupo + reap final.
        if proc is not None:
            try:
                proc.wait(timeout=0.5)
            except Exception:  # noqa: BLE001
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, _sig.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.wait(timeout=1.0)
                except Exception:  # noqa: BLE001
                    pass
        self._shell = None

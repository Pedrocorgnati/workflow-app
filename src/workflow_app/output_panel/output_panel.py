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

import functools
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

from workflow_app import dispatch_telemetry
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
#
# Severidade (3o campo) — fix dos falsos-VERMELHOS dos casos 004/010/013
# (blacksmith/listeners/debug.md). Um crash real de auth/credit/rate do CLI
# emite ~0-300 bytes em < 2s (a janela early-crash). As MESMAS palavras
# ("unauthorized", "rate-limit", "429", "usage limit") aparecem o tempo todo
# em conteudo BENIGNO que o agente renderiza (specs/codigo discutindo auth e
# rate-limiting). Por isso cada pattern carrega uma severidade:
#   "hard" -> frase muito especifica de morte do CLI; dispara em qualquer
#             chunk (improvavel em conteudo benigno).
#   "soft" -> palavra/expressao generica; so conta como fatal DENTRO da janela
#             early-crash (ver _scan_chunk_for_fatal). Fora dela e tratada como
#             conteudo, nao crash. O caminho autoritativo `wf-notify --status
#             failure` NAO passa por este scanner e nao e afetado.
_FATAL_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "AUTH_SUBSCRIPTION_DISABLED",
        re.compile(
            r"organization has disabled (?:Claude )?subscription access",
            re.IGNORECASE,
        ),
        "hard",
    ),
    (
        "AUTH_API_KEY_REQUIRED",
        re.compile(r"Use an Anthropic API key instead", re.IGNORECASE),
        "hard",
    ),
    (
        "AUTH_INVALID_API_KEY",
        re.compile(
            r"\b(invalid api key|authentication[_ ]error|unauthorized)\b",
            re.IGNORECASE,
        ),
        "soft",
    ),
    (
        "AUTH_LOGIN_EXPIRED",
        re.compile(
            r"(login (?:expired|required|to continue)|please (?:run|log) ?in|please log[ -]?in)",
            re.IGNORECASE,
        ),
        "soft",
    ),
    (
        "CREDIT_BALANCE_LOW",
        re.compile(r"credit balance is too low", re.IGNORECASE),
        "hard",
    ),
    (
        "USAGE_LIMIT_REACHED",
        re.compile(
            r"(usage limit (?:reached|exceeded)|monthly limit|quota exceeded)",
            re.IGNORECASE,
        ),
        "soft",
    ),
    (
        "RATE_LIMIT",
        re.compile(
            r"(rate[ _-]?limit(?:ed)?|429 too many requests|too many requests)",
            re.IGNORECASE,
        ),
        "soft",
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

        # Enter submissor com gate de eco (ver `_schedule_submit_enter`).
        # `_submit_epoch` invalida gate e reenvios pendentes assim que um
        # dispatch novo assume o painel — um `\r` atrasado de um comando
        # velho cairia em cima do comando novo.
        self._submit_epoch: int = 0
        # Espelho do radio Main LLM (`queue-div-main-llm`). So pesa no T1:
        # e ele que decide o piso do Enter (Claude/Ink aceita o paste em
        # ~250ms; kimi-code/qwen-code repintam a TUI inteira e precisam de
        # 1s, +2s na janela logo depois de um `/clear`).
        self._main_llm: str = "claude"
        # Head do dispatch ANTERIOR neste canal, para reconhecer a janela
        # "primeiro comando depois do /clear" — a mesma que
        # `_KIMI_AFTER_CLEAR_EXTRA_DELAY_MS` cobre no T2.
        self._last_dispatch_head: str | None = None

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
        # Eixo Main LLM: vale para os tres paineis assinarem (o valor so e
        # consumido quando `self._channel == "interactive"`), assim um panel
        # promovido a T1 nao nasce com o cache preso em "claude".
        signal_bus.main_llm_changed.connect(self._on_main_llm_changed)
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
    # Piso do Enter quando o T1 NAO e Claude. kimi-code e qwen-code sao
    # forks do gemini-cli (Ink/React): repintam a TUI inteira e so leem o
    # stdin quando o event loop do Node esta livre, entao 250ms chega no
    # meio do repaint. Espelha `_KIMI_BLUE_ARROW_DEFAULT_DELAY_MS` do
    # command_queue_widget, que ja resolvia isso no T2.
    _ENTER_SUBMIT_DELAY_SLOW_MS: int = 1_000
    # Extra na janela "primeiro comando depois do /clear": o repaint pos
    # clear e o mais caro de todos. Espelha
    # `_KIMI_AFTER_CLEAR_EXTRA_DELAY_MS` (T2).
    _ENTER_AFTER_CLEAR_EXTRA_MS: int = 2_000
    # Main LLMs que aceitam o piso curto. Codex fica de fora de proposito:
    # o T3 ja usa 1000ms em `MainWindow._xterm_inject_text` pelo mesmo
    # motivo (Ink engole Enter colado perto demais do paste).
    _FAST_ENTER_MAIN_LLMS: frozenset[str] = frozenset({"claude"})

    def _on_main_llm_changed(self, llm: str) -> None:
        """Cacheia qual CLI ocupa o T1 (fonte: radio `queue-div-main-llm`)."""
        if llm:
            self._main_llm = llm

    def _enter_submit_delay_ms(self, command: str) -> int:
        """Piso (nao teto) do Enter submissor para este dispatch.

        E so o PISO: o gate de eco (`_schedule_submit_enter`) pode adiar
        mais, se a TUI ainda nao renderizou o paste quando o piso vence.
        """
        if self._channel != "interactive":
            return self._ENTER_SUBMIT_DELAY_MS
        if self._main_llm in self._FAST_ENTER_MAIN_LLMS:
            return self._ENTER_SUBMIT_DELAY_MS
        delay = self._ENTER_SUBMIT_DELAY_SLOW_MS
        if self._last_dispatch_head == "/clear":
            delay += self._ENTER_AFTER_CLEAR_EXTRA_MS
        return delay

    @staticmethod
    def _dispatch_head(command: str) -> str | None:
        stripped = command.strip()
        if not stripped:
            return None
        return stripped.split(None, 1)[0].lower()

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
        # Novo dispatch: mata gate e reenvios pendentes do comando anterior.
        self._submit_epoch += 1
        if self._shell is None:
            dispatch_telemetry.record_pty_write(
                channel=self._channel, command=command,
                requested=len(command.encode("utf-8", errors="replace")),
                written=None, bracketed=False,
            )
            return
        data = command.encode("utf-8", errors="replace")
        bracketed = _BRACKETED_PASTE_MODE in self._screen.mode
        if bracketed:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        min_delay_ms = self._enter_submit_delay_ms(command)
        self._last_dispatch_head = self._dispatch_head(command)
        written = self._shell.send_raw(data)
        seq = dispatch_telemetry.record_pty_write(
            channel=self._channel, command=command,
            requested=len(data), written=written, bracketed=bracketed,
        )
        self._schedule_submit_enter(command, min_delay_ms=min_delay_ms)
        # A auditoria de eco tem que cair DEPOIS do Enter, senao um piso
        # longo (kimi/qwen pos-/clear) faria ela acusar "engolido" so por
        # ter olhado a tela cedo demais. Mesma formula do blue-arrow.
        self._schedule_echo_confirmation(
            seq, command,
            delay_ms=max(self._ECHO_CONFIRM_DELAY_MS, min_delay_ms + 1_250),
        )
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
        # A rota imperativa escreve no PTY sem passar por `_run_shell_command`,
        # entao a telemetria de write nao teria com o que casar. Abrimos o
        # registro aqui para o dispatch aparecer no log com a rota correta em
        # vez de virar `unattributed`.
        seq = dispatch_telemetry.open_dispatch(
            route="imperative-inject", channel=self._channel, command=command,
        )
        self._schedule_echo_confirmation(seq, command)
        if self._is_helper_command(command):
            # Disarma: um _dispatch_ts stale de um comando real anterior nao
            # pode false-firar EARLY_EXIT durante o helper.
            self._dispatch_ts = None
            return
        self._dispatch_ts = time.monotonic()
        self._bytes_since_dispatch = 0
        self._last_failure_reason = None

    def _send_enter_to_shell(self) -> None:
        """Slot dos sinais `submit_enter_to_*` — Enter avulso, sem gate."""
        self._write_enter("signal")

    def _write_enter(self, reason: str) -> None:
        """Send a bare \r to the persistent shell if it is still alive."""
        if self._shell is None:
            dispatch_telemetry.record_enter(
                channel=self._channel, written=None, reason=reason
            )
            return
        written = self._shell.send_raw(b"\r")
        dispatch_telemetry.record_enter(
            channel=self._channel, written=written, reason=reason
        )

    # ──────────────────── Enter submissor condicionado ao eco ───────── #
    # O Enter viajava como `singleShot` fixo de 250ms, sem nenhuma prova de
    # que a TUI do outro lado tinha renderizado o paste. Node so le o stdin
    # quando o event loop dele esta livre: durante o repaint completo que
    # vem depois de um `/clear` (ou durante streaming), o bloco de bracketed
    # paste e o `\r` sao drenados no MESMO tick, e o handler do submit
    # resolve o texto do buffer contra o closure PRE-paste (o React so
    # atualiza o state no re-render). O submit e descartado em silencio: o
    # `/clear` fica na linha e o item seguinte cola em cima, produzindo
    # `/clear /skill:...` — comando inexistente.
    #
    # Aqui o Enter passa a ser condicionado ao ECO. Depois do write fazemos
    # poll da tela do pyte procurando o texto colado e so mandamos `\r`
    # quando ele APARECE (houve render, logo o closure nao esta mais velho)
    # ou quando estoura o teto. Depois do Enter, conferimos se o texto
    # continua na linha do cursor; se continuar, o submit nao passou e
    # reenviamos. Enter em prompt vazio e no-op, entao o reenvio e seguro.
    _ENTER_GATE_POLL_MS: int = 50
    # Teto do gate, contado A PARTIR do piso. Estourou, manda o Enter do
    # mesmo jeito: pior caso = comportamento antigo, nunca um item mudo.
    _ENTER_GATE_TIMEOUT_MS: int = 4_000
    _ENTER_VERIFY_DELAY_MS: int = 700
    _ENTER_MAX_RESENDS: int = 2
    # Abaixo disto o token nao identifica o dispatch na tela. Bem mais
    # frouxo que `_ECHO_MIN_NEEDLE_CHARS` (8) de proposito: la um falso
    # positivo mentiria na telemetria; aqui ele so devolve o comportamento
    # antigo (Enter no piso), e `/clear` — o comando do bug — tem 6 chars.
    _SUBMIT_GATE_MIN_CHARS: int = 4
    _SUBMIT_GATE_MAX_CHARS: int = 12
    # Acima disto (ou com quebra de linha) a TUI NAO ecoa o texto: Claude
    # Code colapsa o bloco em `[Pasted text #1 +N lines]` e os forks do
    # gemini-cli fazem o mesmo. Esperar um eco que nunca vem so pagaria o
    # teto do gate em cada prompt longo (blue arrow do Kimi, seeds de
    # brainstorm), entao esses caem direto no piso — comportamento antigo.
    # Os dois bugs que este gate existe para matar vivem no dispatch de
    # UMA linha (`/clear`, `/skill:...`, `/slash-executor ...`).
    _SUBMIT_GATE_MAX_COMMAND_CHARS: int = 400
    # Quantas linhas acima do cursor ainda contam como "linha de prompt"
    # (a caixa de input do Ink quebra o paste em varias linhas).
    _SUBMIT_CURSOR_LOOKBACK_ROWS: int = 3

    @classmethod
    def _submit_gate_needle(cls, command: str) -> str | None:
        """Trecho do comando que procuramos na tela para liberar o Enter.

        None desliga o gate (Enter no piso, como antes do fix).
        """
        if "\n" in command or "\r" in command:
            return None
        if len(command) > cls._SUBMIT_GATE_MAX_COMMAND_CHARS:
            return None
        tokens = [t for t in command.split() if t]
        if not tokens:
            return None
        # Preferimos o ULTIMO token, e pelo FIM dele. E o token que fica
        # sob o cursor, e e ele que decide o estado do autocomplete das
        # TUIs do gemini-cli: com o token ainda pela metade na tela, o fzf
        # do `useCommandSuggestions` casa por subsequencia e deixa a lista
        # de sugestoes aberta — foi assim que um Enter virou "aceitar
        # sugestao" e duplicou o `/slash-executor`. Ver o sufixo na tela
        # prova que o token chegou INTEIRO ao render.
        candidate = tokens[-1]
        if len(candidate) < cls._SUBMIT_GATE_MIN_CHARS:
            candidate = max(tokens, key=len)
        if len(candidate) < cls._SUBMIT_GATE_MIN_CHARS:
            return None
        return candidate[-cls._SUBMIT_GATE_MAX_CHARS :]

    def _screen_rows(self) -> list[str] | None:
        try:
            return list(self._screen.display)
        except Exception:  # noqa: BLE001 — pyte indisponivel/instavel
            return None

    def _screen_needle_count(self, needle: str) -> int | None:
        """Ocorrencias do needle na tela visivel. None = indecidivel.

        Alem do blob por linhas, olhamos a versao "desdobrada" (linhas
        concatenadas sem o trailing space): a TUI quebra o paste em
        qualquer coluna e um token partido no wrap nao apareceria no
        primeiro blob.
        """
        rows = self._screen_rows()
        if rows is None:
            return None
        joined = "\n".join(r.rstrip() for r in rows)
        dewrapped = "".join(r.rstrip() for r in rows)
        return max(joined.count(needle), dewrapped.count(needle))

    def _needle_at_cursor(self, needle: str) -> bool:
        """O texto colado ainda esta na linha do prompt (= nao submeteu)?

        Buscamos SO na vizinhanca do cursor, nao na tela toda: depois de um
        submit bem-sucedido o comando continua visivel no transcript, mas
        sai da linha de input. Indecidivel conta como "submeteu" — no
        reenvio o falso negativo (nao reenviar) e mais barato que o falso
        positivo (um Enter extra em cima de um dialogo).
        """
        rows = self._screen_rows()
        if rows is None:
            return False
        try:
            cursor_y = int(self._screen.cursor.y)
        except Exception:  # noqa: BLE001 — pyte instavel
            return False
        top = max(0, cursor_y - self._SUBMIT_CURSOR_LOOKBACK_ROWS)
        window = rows[top : cursor_y + 1]
        if not window:
            return False
        joined = "\n".join(r.rstrip() for r in window)
        dewrapped = "".join(r.rstrip() for r in window)
        return needle in joined or needle in dewrapped

    def _schedule_submit_enter(self, command: str, *, min_delay_ms: int) -> None:
        """Arma o gate de eco do Enter submissor deste dispatch."""
        needle = self._submit_gate_needle(command)
        # Baseline ANTES do render: o gate exige que a contagem AUMENTE, e
        # nao que o needle exista. Sem isso, um `/clear` que ainda estivesse
        # ecoado na tela do ciclo anterior liberaria o Enter na hora.
        baseline = None if needle is None else self._screen_needle_count(needle)
        deadline = time.monotonic() + (
            min_delay_ms + self._ENTER_GATE_TIMEOUT_MS
        ) / 1000.0
        QTimer.singleShot(
            min_delay_ms,
            self,
            functools.partial(
                self._poll_submit_gate,
                needle, baseline, deadline, self._submit_epoch,
            ),
        )

    def _poll_submit_gate(
        self,
        needle: str | None,
        baseline: int | None,
        deadline: float,
        epoch: int,
    ) -> None:
        if epoch != self._submit_epoch:
            return  # dispatch mais novo assumiu o painel
        rendered = needle is None or baseline is None
        if not rendered:
            count = self._screen_needle_count(needle)
            rendered = count is None or count > baseline
        if not rendered and time.monotonic() < deadline:
            QTimer.singleShot(
                self._ENTER_GATE_POLL_MS,
                self,
                functools.partial(
                    self._poll_submit_gate, needle, baseline, deadline, epoch
                ),
            )
            return
        self._write_enter("gated" if rendered else "gate-timeout")
        if needle is not None:
            QTimer.singleShot(
                self._ENTER_VERIFY_DELAY_MS,
                self,
                functools.partial(self._verify_submitted, needle, epoch, 1),
            )

    def _verify_submitted(self, needle: str, epoch: int, attempt: int) -> None:
        """Reenvia o Enter enquanto o comando continuar na linha de prompt."""
        if epoch != self._submit_epoch or self._shell is None:
            return
        if not self._needle_at_cursor(needle):
            return  # saiu da linha de input: submeteu
        self._write_enter(f"resend-{attempt}")
        if attempt < self._ENTER_MAX_RESENDS:
            QTimer.singleShot(
                self._ENTER_VERIFY_DELAY_MS,
                self,
                functools.partial(
                    self._verify_submitted, needle, epoch, attempt + 1
                ),
            )

    # ─────────────────────────── Confirmacao de eco do dispatch ─────── #
    # Terceira perna da telemetria (ver `workflow_app.dispatch_telemetry`).
    # `emit` diz que a fila publicou; `pty_write` diz quantos bytes o PTY
    # aceitou. Nenhum dos dois prova que o CLI do outro lado RECEBEU o texto:
    # o bloco de bracketed paste pode ser descartado pela TUI enquanto ela
    # repinta (as duas ocorrencias do incidente 2026-08-24 aconteceram no
    # primeiro comando logo apos um `/clear`). Depois de um atraso curto,
    # procuramos um trecho distintivo do comando no buffer da tela: presente
    # = o terminal recebeu; ausente E zero bytes vindos do PTY = engolido.

    _ECHO_CONFIRM_DELAY_MS: int = 1500
    # Abaixo disto o token nao e distintivo (`/clear`, `haiku`, `--task`) e
    # um "nao achei na tela" nao significaria nada. Nesses casos registramos
    # UNKNOWN em vez de acusar um dispatch que provavelmente esta certo.
    _ECHO_MIN_NEEDLE_CHARS: int = 8

    @staticmethod
    def _echo_needle(command: str) -> str | None:
        """Maior token sem espaco do comando, quando distintivo o bastante."""
        tokens = [t.strip() for t in command.split()]
        if not tokens:
            return None
        longest = max(tokens, key=len)
        if len(longest) < OutputPanel._ECHO_MIN_NEEDLE_CHARS:
            return None
        return longest

    def _screen_contains(self, needle: str) -> bool | None:
        """Procura `needle` no buffer renderizado. None quando indecidivel.

        A TUI quebra linha em qualquer coluna, entao um token longo pode
        aparecer partido. Tentamos fatias progressivamente menores antes de
        concluir ausencia — e nunca abaixo de `_ECHO_MIN_NEEDLE_CHARS`, onde
        um match seria ruido.
        """
        try:
            lines = list(self._screen.display)
        except Exception:  # noqa: BLE001 — pyte indisponivel/instavel
            return None
        blob = "\n".join(lines)
        for size in (len(needle), 24, 16, self._ECHO_MIN_NEEDLE_CHARS):
            if size < self._ECHO_MIN_NEEDLE_CHARS or size > len(needle):
                continue
            if needle[:size] in blob:
                return True
        return False

    def _schedule_echo_confirmation(
        self, seq: int, command: str, *, delay_ms: int | None = None
    ) -> None:
        """Agenda a checagem de eco para depois do Enter submissor."""
        QTimer.singleShot(
            self._ECHO_CONFIRM_DELAY_MS if delay_ms is None else delay_ms,
            self,
            functools.partial(
                self._confirm_dispatch_echo, seq, command, time.monotonic()
            ),
        )

    def _confirm_dispatch_echo(
        self, seq: int, command: str, dispatched_at: float
    ) -> None:
        needle = self._echo_needle(command)
        echoed = None if needle is None else self._screen_contains(needle)
        dispatch_telemetry.record_echo(
            seq=seq,
            channel=self._channel,
            command=command,
            echoed=echoed,
            bytes_seen=self._bytes_since_dispatch,
            elapsed_ms=int((time.monotonic() - dispatched_at) * 1000),
            helper=self._is_helper_command(command),
        )

    def _run_kimi_blue_arrow(self, prompt: str, delay_ms: int) -> None:
        """Blue-arrow Kimi dispatch — paste + delayed Enter.

        Kimi's Rich/textual prompt sometimes swallows Enter when it arrives
        too early (Ink CLIs buffer the paste block and an Enter on the same
        tick gets eaten before the /skill: line is fully composed). The
        delay is supplied by the caller — typically 1000ms, or 3000ms when
        the dispatch is subsequent to /clear (Kimi takes longer to render
        the prompt right after a clear because the TUI repaints fully).
        """
        self._submit_epoch += 1
        if self._shell is None:
            dispatch_telemetry.record_pty_write(
                channel=self._channel, command=prompt,
                requested=len(prompt.encode("utf-8", errors="replace")),
                written=None, bracketed=False,
            )
            return
        data = prompt.encode("utf-8", errors="replace")
        bracketed = _BRACKETED_PASTE_MODE in self._screen.mode
        if bracketed:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._last_dispatch_head = self._dispatch_head(prompt)
        written = self._shell.send_raw(data)
        seq = dispatch_telemetry.record_pty_write(
            channel=self._channel, command=prompt,
            requested=len(data), written=written, bracketed=bracketed,
        )
        # `delay_ms` do caller vira o PISO; o gate de eco pode adiar mais e
        # o verify reenvia se o prompt do Kimi engolir o Enter mesmo assim.
        self._schedule_submit_enter(prompt, min_delay_ms=delay_ms)
        self._schedule_echo_confirmation(seq, prompt, delay_ms=delay_ms + 1250)

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
        signal_bus.terminal_output_observed.emit(self._channel, chunk)
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

        Padroes "soft" (palavras genericas de auth/rate/usage) so contam
        como crash DENTRO da janela early-crash — um crash real emite poucos
        bytes em < 2s. Fora dela, as mesmas palavras sao conteudo benigno
        renderizado (specs/codigo discutindo auth e rate-limiting) e NAO
        devem forcar vermelho (casos 004/010/013 de debug.md). Padroes "hard"
        (frases especificas de morte do CLI) permanecem incondicionais.
        """
        if not chunk:
            return
        in_early_crash_window = (
            self._dispatch_ts is not None
            and self._bytes_since_dispatch < self._EARLY_EXIT_BYTES_THRESHOLD
            and (time.monotonic() - self._dispatch_ts) < self._EARLY_EXIT_TIME_THRESHOLD_S
        )
        for reason, pattern, severity in _FATAL_PATTERNS:
            if severity == "soft" and not in_early_crash_window:
                continue
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

    def output_tail(self, max_lines: int = 40) -> str:
        """Texto plano das ultimas linhas visiveis do terminal deste canal.

        Fonte do `output_excerpt` do snapshot de recuperacao (ver
        `metrics_bar.recovery_context`). Le a tela renderizada do pyte, que ja
        e um grid de caracteres: o retorno sai SEM sequencias ANSI, sem
        precisar de um de-escaper proprio.

        Read-only por contrato: nao consome buffer, nao mexe em cursor, nao
        emite sinal. Pode ser chamado a qualquer momento, inclusive com o
        canal vermelho, e nunca levanta — falha de leitura vira string vazia,
        que o chamador traduz para `INDISPONIVEL`. Um snapshot de recuperacao
        nunca pode ser a causa de uma segunda falha.
        """
        try:
            rows = list(self._screen.display)
        except Exception:  # noqa: BLE001 - diagnostico nunca derruba o app
            return ""
        lines = [row.rstrip() for row in rows]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        if max_lines > 0 and len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines)

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

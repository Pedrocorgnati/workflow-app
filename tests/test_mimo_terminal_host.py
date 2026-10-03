"""Host de terminal da MiMo no workflow-app (area F3), testes 100% offline.

Tudo aqui roda com feed SINTETICO de bytes no EnhancedScreen/OutputPanel: o
CLI real nunca sobe, o PersistentShell do painel e trocado por um fake que so
registra writes e responde `hosts_cli`, e o sidecar de telemetria de dispatch
vai para o tmp_path do teste.

As frases-gatilho dos toasts fatais da MiMo sao montadas por CONCATENACAO: o
texto literal nunca aparece neste arquivo (nem nas fontes da area), entao
exibir este teste num painel que hospeda a MiMo nao vira falso vermelho.
`TestInvariants` trava isso.

Cobertura:
  - pyte: DSR privado (`CSI ? Ps n`) nao derruba o resto do chunk e o DSR
    5n/6n continua respondendo;
  - `_on_chunk` segue depois de uma excecao do feed (render, idle, atividade
    e scan de fatais) e loga uma vez so;
  - padroes fatais escopados por CLI: gate do host, toast fatiado por
    CUP/SGR, OSC e ESC de dois bytes entre as palavras, frase partida entre
    dois chunks, escape incompleto na fronteira, 429 retryable fora e match
    generico que curto-circuita o scan escopado;
  - latch por janela de erro: cada reason sai uma vez (toast repintado,
    dois reasons alternando, generico ja emitido no mesmo chunk do 401 da
    MiMo, EARLY_EXIT seguido de toast), todo disparo zera a cauda,
    `rearm_fatal_scan` e o dispatch real reabrem a janela, o launcher
    `mimod` rearma sem abrir a janela early-exit e os demais helpers nao;
  - gate de eco: a agulha atravessa a borda da caixa de input (contagem e
    cursor), inclusive ponta a ponta no event loop;
  - helper `mimod`, piso do Enter com a MiMo no Main e `hosts_cli` por
    basename.
"""
from __future__ import annotations

import inspect
import logging
import pathlib
import time

import pyte
import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from workflow_app import dispatch_telemetry
from workflow_app.metrics_bar.recovery_prompt import RECOVERY_REASONS
from workflow_app.output_panel.enhanced_screen import EnhancedScreen
from workflow_app.output_panel.output_panel import (
    _BRACKETED_PASTE_MODE,
    _CLI_FATAL_TAIL_CHARS,
    _CLI_LAUNCH_REARM_HEADS,
    _CLI_SCOPED_FATAL_PATTERNS,
    _FATAL_PATTERNS,
    OutputPanel,
)
from workflow_app.output_panel.persistent_shell import (
    PersistentShell,
    cli_name_in_exec_basenames,
)
from workflow_app.signal_bus import signal_bus
from workflow_app.terminal_helpers import HELPER_COMMANDS, is_helper_command

# Frases-gatilho montadas por concatenacao (ver docstring do modulo).
_KEY_TOAST = "Invalid " + "API Key: Please provide valid " + "API Key"
_STATUS_401 = "status " + "401 · non-" + "retryable"
_FREE_ENDED = "Free " + "API service " + "ended"
_MODEL_INVALID = "Model " + "xiaomi-token-plan-sgp/mimo-v2.6-pro is not " + "valid"
# Padroes genericos "hard" (Claude): mesma higiene de concatenacao.
_CREDIT_LOW = "Your credit " + "balance is too low to access the API."
_USE_API_KEY = "Use an " + "Anthropic API key " + "instead"
# A MiMo tenta de novo sozinha: nao e fatal.
_RETRYABLE_429 = "status 429 · retryable"

_PANEL_LOGGER = OutputPanel.__module__

# Ordem de HELPER_COMMANDS antes da MiMo: entradas novas vao so no FIM
# (metrics_bar deriva a ordem dos botoes persistida em QSettings dela).
_HELPERS_BEFORE_MIMO = (
    "/model", "/effort", "/clear", "cd",
    "clauded", "kimid", "codex", "codex-high", "qwened", "grokd",
)


class _FakeSignal:
    """`output_received` minimo: `_on_pipeline_started` desconecta dele."""

    def connect(self, slot) -> None:  # noqa: ANN001
        pass

    def disconnect(self, slot=None) -> None:  # noqa: ANN001
        pass


class FakeHostShell:
    """Substitui o PersistentShell: registra writes e responde `hosts_cli`.

    `hosted` simula o walk de `/proc` (basenames dos descendentes do PTY) e
    `error` simula `/proc` ilegivel. `hosts_calls` prova que o walk so
    acontece depois que um padrao escopado casou.
    """

    def __init__(
        self,
        hosted: tuple[str, ...] = ("mimo",),
        error: Exception | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.hosted = set(hosted)
        self.error = error
        self.hosts_calls: list[str] = []
        self.output_received = _FakeSignal()

    def send_raw(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def resize(self, cols: int, rows: int) -> None:  # PTY SIGWINCH, no-op
        pass

    def start(self) -> None:
        pass

    def terminate(self) -> None:
        pass

    def hosts_cli(self, cli: str) -> bool:
        self.hosts_calls.append(cli)
        if self.error is not None:
            raise self.error
        return cli in self.hosted

    @property
    def enters(self) -> int:
        return self.writes.count(b"\r")


@pytest.fixture(autouse=True)
def _telemetria_em_tmp(tmp_path, monkeypatch):
    """Sidecar de dispatch no tmp_path: nada vai para ~/.workflow-app/logs."""
    monkeypatch.setattr(dispatch_telemetry, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(
        dispatch_telemetry, "_JSONL_PATH", tmp_path / "dispatch-telemetry.jsonl"
    )
    dispatch_telemetry._reset_for_tests()
    yield
    dispatch_telemetry._reset_for_tests()


def _quiesce(panel: OutputPanel) -> None:
    """Desarma gate, reenvio e timers antes do close do pytest-qt.

    O idle de 2s de um T1 velho, com `_dispatch_ts` armado, emitiria
    EARLY_EXIT dentro do `waitUntil` de outro teste.
    """
    panel._submit_epoch += 1
    panel._dispatch_ts = None
    panel._idle_timer.stop()
    panel._render_timer.stop()


def _flush_deferred_deletes() -> None:
    """Executa o `deleteLater` que o pytest-qt agendou no teardown.

    Com o painel destruido morrem junto os `singleShot` de confirmacao de
    eco, que nao olham epoch e gravariam telemetria depois que o monkeypatch
    do sidecar ja foi desfeito.
    """
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _make_panel(qtbot, **kwargs) -> OutputPanel:  # noqa: ANN001, ANN003
    panel = OutputPanel(**kwargs)
    qtbot.addWidget(panel, before_close_func=_quiesce)
    panel._shell = FakeHostShell()
    return panel


@pytest.fixture()
def t1(qapp, qtbot):
    """Painel interativo (T1). Nunca recebe show(): nenhum PTY real sobe."""
    yield _make_panel(qtbot)
    _flush_deferred_deletes()


@pytest.fixture()
def t2(qapp, qtbot):
    """Painel workspace (T2), onde a MiMo roda como worker."""
    yield _make_panel(qtbot, workspace_mode=True)
    _flush_deferred_deletes()


@pytest.fixture()
def failed():
    """Captura `terminal_force_failed(channel, reason)` do signal_bus."""
    seen: list[tuple[str, str]] = []

    def _slot(channel: str, reason: str) -> None:
        seen.append((channel, reason))

    signal_bus.terminal_force_failed.connect(_slot)
    yield seen
    try:
        signal_bus.terminal_force_failed.disconnect(_slot)
    except (RuntimeError, TypeError):
        pass


def _paint(panel: OutputPanel, text: str) -> None:
    """Renderiza `text` na tela do pyte como a TUI faria."""
    panel._stream.feed(text.encode("utf-8"))


class TestPrivateDsr:
    """pyte 0.8.2 despacha `CSI ? Ps n` como `report_device_status(Ps,
    private=True)`, mas a base so aceita `mode`: o TypeError resetava o
    parser e o RESTO do chunk se perdia. O primeiro chunk da MiMo traz
    `?996n` antes de `?2004h`, entao o bracketed paste nunca ligava."""

    @staticmethod
    def _screen() -> tuple[EnhancedScreen, pyte.ByteStream, list[str]]:
        screen = EnhancedScreen(80, 24, history=100)
        replies: list[str] = []
        screen.write_process_input = replies.append
        return screen, pyte.ByteStream(screen), replies

    def test_private_dsr_keeps_the_rest_of_the_chunk(self):
        screen, stream, replies = self._screen()
        stream.feed(b"\x1b[?996n\x1b[?2004hHELLO")
        assert _BRACKETED_PASTE_MODE in screen.mode
        assert screen.display[0].startswith("HELLO")
        assert replies == []  # variante privada: ignorada, sem resposta

    def test_cursor_position_report_still_answers(self):
        _screen, stream, replies = self._screen()
        stream.feed(b"\x1b[6n")
        stream.feed(b"\x1b[5;7H\x1b[6n")
        assert replies == ["\x1b[1;1R", "\x1b[5;7R"]

    def test_status_report_still_answers(self):
        _screen, stream, replies = self._screen()
        stream.feed(b"\x1b[5n")
        assert replies == ["\x1b[0n"]

    def test_extra_dsr_params_do_not_drop_the_chunk(self):
        screen, stream, replies = self._screen()
        stream.feed(b"\x1b[6;1nAFTER")
        assert replies == ["\x1b[1;1R"]
        assert screen.display[0].startswith("AFTER")

    def test_panel_wraps_the_first_dispatch_in_bracketed_paste(self, t1):
        t1._on_chunk("\x1b[?996n\x1b[?2004h")
        t1._run_shell_command("/loop --task x")
        assert t1._shell.writes[0] == b"\x1b[200~/loop --task x\x1b[201~"


class _ExplodingStream:
    """Stream do pyte que sempre levanta no feed (parser quebrado)."""

    def __init__(self) -> None:
        self.calls = 0

    def feed(self, data: bytes) -> None:
        self.calls += 1
        raise TypeError("feed sintetico quebrado")


class TestOnChunkSurvivesFeedError:
    """Defesa em profundidade: uma excecao no feed do pyte nao pode engolir
    render, idle, atividade nem o scan de fatais do chunk."""

    def test_render_idle_and_activity_still_run(self, t1):
        t1._stream = _ExplodingStream()
        seen: list[str] = []

        def _on_activity(channel: str) -> None:
            seen.append(channel)

        signal_bus.terminal_activity.connect(_on_activity)
        try:
            t1._on_chunk("qualquer coisa")
        finally:
            signal_bus.terminal_activity.disconnect(_on_activity)
        assert t1._has_pending_render is True
        assert t1._render_timer.isActive()
        assert t1._idle_timer.isActive()
        assert seen == [t1._channel]

    def test_generic_fatal_scan_still_runs(self, t1, failed):
        t1._stream = _ExplodingStream()
        t1._on_chunk(_CREDIT_LOW)
        assert failed == [(t1._channel, "CREDIT_BALANCE_LOW")]

    def test_cli_scoped_scan_still_runs(self, t2, failed):
        t2._stream = _ExplodingStream()
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    def test_logs_the_first_failure_only(self, t1, caplog):
        stream = _ExplodingStream()
        t1._stream = stream
        with caplog.at_level(logging.WARNING, logger=_PANEL_LOGGER):
            t1._on_chunk("a")
            t1._on_chunk("b")
        records = [r for r in caplog.records if r.name == _PANEL_LOGGER]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert stream.calls == 2


class TestCliScopedFatalPatterns:
    """Toast fatal da MiMo: escopado pelo CLI que o PTY hospeda e casado
    sobre o texto sem ANSI (cauda + chunk), sem depender da janela
    early-crash. `_dispatch_ts` fica None aqui: os padroes genericos "soft"
    nem entram no jogo."""

    def test_fires_when_the_pty_hosts_mimo(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]
        assert t2._shell.hosts_calls == ["mimo"]

    def test_fires_on_the_interactive_channel_too(self, t1, failed):
        t1._on_chunk("\x1b[31m" + _STATUS_401 + "\x1b[0m")
        assert failed == [("interactive", "AUTH_INVALID_API_KEY")]

    @pytest.mark.parametrize(
        "make_shell",
        [
            lambda: FakeHostShell(hosted=()),
            lambda: FakeHostShell(hosted=("kimi",)),
            lambda: FakeHostShell(error=OSError("proc sumiu")),
            lambda: FakeHostShell(error=ValueError("comm fora de utf-8")),
            lambda: None,
        ],
        ids=["sem-cli", "outro-cli", "proc-oserror", "proc-valueerror", "sem-shell"],
    )
    def test_stays_quiet_without_the_host(self, t2, failed, make_shell):
        t2._shell = make_shell()
        t2._on_chunk(_KEY_TOAST)
        assert failed == []
        assert t2._last_failure_reason is None

    def test_benign_chunk_never_walks_proc(self, t2, failed):
        t2._on_chunk("\x1b[2K\x1b[32mcompilando modulo 3\x1b[0m ...")
        assert failed == []
        assert t2._shell.hosts_calls == []

    def test_toast_sliced_by_cup_and_sgr(self, t2, failed):
        parts: list[str] = []
        col = 2
        for word in _KEY_TOAST.split(" "):
            parts.append(f"\x1b[3;{col}H\x1b[38;2;255;80;80m{word}\x1b[0m")
            col += len(word) + 1
        chunk = "".join(parts)
        # Cru, nenhum padrao casa: so o scan sem ANSI enxerga a frase.
        assert not any(p.search(chunk) for _, _, p in _CLI_SCOPED_FATAL_PATTERNS)
        t2._on_chunk(chunk)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    @pytest.mark.parametrize(
        "escape",
        ["\x1b]0;mimo\x07", "\x1b]2;mimo\x1b\\", "\x1bM"],
        ids=["osc-bel", "osc-st", "esc-dois-bytes"],
    )
    def test_osc_and_two_byte_escape_between_words(self, t2, failed, escape):
        # Titulo de janela (OSC terminado em BEL ou ST) e ESC de dois bytes
        # (RI) entre as palavras do toast saem inteiros antes do match.
        head, sep, rest = _KEY_TOAST.partition(" ")
        t2._on_chunk(head + sep + escape + rest)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    def test_status_split_across_two_chunks(self, t2, failed):
        t2._on_chunk("\x1b[2K" + _STATUS_401[:9])
        assert failed == []
        t2._on_chunk(_STATUS_401[9:] + "\x1b[0m")
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    def test_incomplete_escape_at_the_chunk_boundary(self, t2, failed):
        # O SGR partido na fronteira sobrevive na cauda e completa no
        # chunk seguinte; nada de lixo `8;5;9m` colado no meio da frase.
        t2._on_chunk("\x1b[38;5;9m" + _FREE_ENDED[:5] + "\x1b[3")
        assert failed == []
        t2._on_chunk("8;5;9m" + _FREE_ENDED[5:] + "\x1b[0m")
        assert failed == [("workspace", "AUTH_API_KEY_REQUIRED")]

    @pytest.mark.parametrize(
        "phrase", [_FREE_ENDED, _MODEL_INVALID], ids=["free-ended", "model-invalid"]
    )
    def test_key_required_phrases(self, t2, failed, phrase):
        t2._on_chunk(phrase)
        assert failed == [("workspace", "AUTH_API_KEY_REQUIRED")]

    @pytest.mark.parametrize(
        "in_window", [False, True], ids=["fora-da-janela", "dentro-da-janela"]
    )
    def test_retryable_429_does_not_fire(self, t2, failed, in_window):
        if in_window:
            t2._dispatch_ts = time.monotonic()
            t2._bytes_since_dispatch = 0
        t2._on_chunk("\x1b[33m" + _RETRYABLE_429 + "\x1b[0m retrying in 4s")
        assert failed == []
        assert t2._shell.hosts_calls == []

    def test_generic_match_short_circuits_the_scoped_scan(self, t2, failed):
        # Padrao generico "hard" casou: o scan escopado nem roda (nem o walk
        # em /proc), mesmo com uma frase da MiMo no mesmo chunk.
        t2._on_chunk(_CREDIT_LOW + " " + _FREE_ENDED)
        assert failed == [("workspace", "CREDIT_BALANCE_LOW")]
        assert t2._shell.hosts_calls == []


class TestLatchAndRearm:
    """O latch guarda os reasons ja emitidos na janela de erro: cada um sai
    uma vez so, com o toast repintado ou alternando com outro reason;
    `rearm_fatal_scan` reabre a janela."""

    def test_same_toast_twice_emits_once(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]
        # Com o latch fechado o padrao nem chega a olhar `/proc` de novo.
        assert t2._shell.hosts_calls == ["mimo"]

    def test_a_different_reason_still_fires(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        # O disparo zera a cauda: a frase nao sobra para o proximo chunk.
        assert t2._cli_fatal_tail == ""
        t2._on_chunk(_FREE_ENDED)
        assert t2._cli_fatal_tail == ""
        # Repaints benignos depois dos dois toasts: com as duas frases na
        # cauda cada chunk trocaria o latch e reemitiria (ping-pong).
        for _ in range(4):
            t2._on_chunk("x")
        assert failed == [
            ("workspace", "AUTH_INVALID_API_KEY"),
            ("workspace", "AUTH_API_KEY_REQUIRED"),
        ]

    def test_rearm_reopens_latch_and_tail(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk("repaint qualquer")
        assert t2._cli_fatal_tail
        t2.rearm_fatal_scan()
        assert t2._last_failure_reason is None
        assert t2._cli_fatal_tail == ""
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")] * 2

    def test_generic_fire_does_not_revive_the_stale_toast(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        # Repaint do toast ja emitido: a frase fica na cauda do scan escopado.
        t2._on_chunk("\x1b[H" + _KEY_TOAST)
        assert _KEY_TOAST in t2._cli_fatal_tail
        # Disparo GENERICO de outro reason tambem zera a cauda.
        t2._on_chunk(_CREDIT_LOW)
        assert t2._cli_fatal_tail == ""
        # Com um slot so, o primeiro chunk benigno reemitia o 401 pela cauda.
        for _ in range(4):
            t2._on_chunk("x")
        assert failed == [
            ("workspace", "AUTH_INVALID_API_KEY"),
            ("workspace", "CREDIT_BALANCE_LOW"),
        ]

    def test_alternating_repaints_emit_each_reason_once(self, t2, failed):
        # Toast escopado e frase generica repintados em chunks alternados,
        # sem dispatch no meio: cada troca reemitia com o latch de um slot.
        for _ in range(3):
            t2._on_chunk("\x1b[H" + _KEY_TOAST)
            t2._on_chunk("\x1b[H" + _CREDIT_LOW)
        assert failed == [
            ("workspace", "AUTH_INVALID_API_KEY"),
            ("workspace", "CREDIT_BALANCE_LOW"),
        ]

    def test_two_generic_reasons_alternating_emit_once_each(self, t2, failed):
        for _ in range(3):
            t2._on_chunk(_CREDIT_LOW)
            t2._on_chunk(_USE_API_KEY)
        assert failed == [
            ("workspace", "CREDIT_BALANCE_LOW"),
            ("workspace", "AUTH_API_KEY_REQUIRED"),
        ]
        # Nenhuma frase da MiMo casou: o walk em /proc nunca rodou.
        assert t2._shell.hosts_calls == []

    def test_latched_generic_does_not_hide_the_mimo_toast(self, t2, failed):
        t2._on_chunk(_CREDIT_LOW)
        # A frase generica ja emitida volta no mesmo chunk do 401 da MiMo:
        # o generico nao curto-circuita mais o scan escopado.
        t2._on_chunk(_CREDIT_LOW + " " + _KEY_TOAST)
        for _ in range(3):
            t2._on_chunk("x")
        assert failed == [
            ("workspace", "CREDIT_BALANCE_LOW"),
            ("workspace", "AUTH_INVALID_API_KEY"),
        ]
        assert t2._shell.hosts_calls == ["mimo"]

    def test_rearm_forgets_every_reason_of_the_window(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk(_CREDIT_LOW)
        t2.rearm_fatal_scan()
        assert t2._fired_reasons == set()
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk(_CREDIT_LOW)
        assert failed == [
            ("workspace", "AUTH_INVALID_API_KEY"),
            ("workspace", "CREDIT_BALANCE_LOW"),
        ] * 2

    def test_direct_latch_reset_reopens_the_whole_window(self, t2, failed):
        # Idioma dos testes de autocast: zerar o atributo direto, sem rearm.
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk(_CREDIT_LOW)
        t2._last_failure_reason = None
        t2._on_chunk(_KEY_TOAST)
        # Sem descartar os nomes da janela velha, este nao sairia.
        t2._on_chunk(_CREDIT_LOW)
        assert failed == [
            ("workspace", "AUTH_INVALID_API_KEY"),
            ("workspace", "CREDIT_BALANCE_LOW"),
        ] * 2

    def test_early_exit_shares_the_window(self, t2, failed):
        t2._run_shell_command("/loop --task x")
        t2._on_idle_timeout()  # poucos bytes, logo depois do dispatch
        # O toast que chega depois do EARLY_EXIT ainda sai, uma vez so.
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk(_KEY_TOAST)
        assert failed == [
            ("workspace", "EARLY_EXIT"),
            ("workspace", "AUTH_INVALID_API_KEY"),
        ]
        assert t2._fired_reasons == {"EARLY_EXIT", "AUTH_INVALID_API_KEY"}

    @pytest.mark.parametrize("launch", ["mimod", "MIMOD", "  mimod  "])
    def test_mimod_launch_rearms_without_the_early_exit_window(
        self, t2, failed, launch
    ):
        t2._on_chunk(_KEY_TOAST)
        t2._run_shell_command(launch)
        assert t2._last_failure_reason is None
        assert t2._dispatch_ts is None
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")] * 2

    def test_mimod_via_imperative_dispatch_also_rearms(self, t2, failed):
        t2._on_chunk(_KEY_TOAST)
        t2._dispatch_ts = time.monotonic()  # stale de um comando real anterior
        t2.arm_dispatch_window("mimod")
        assert t2._last_failure_reason is None
        assert t2._dispatch_ts is None

    @pytest.mark.parametrize("via", ["_run_shell_command", "arm_dispatch_window"])
    @pytest.mark.parametrize("helper", ["/clear", "/clear ", "/model opus", "cd foo"])
    def test_other_helpers_keep_the_latch(self, t2, failed, via, helper):
        t2._on_chunk(_KEY_TOAST)
        getattr(t2, via)(helper)
        assert t2._last_failure_reason == "AUTH_INVALID_API_KEY"
        t2._on_chunk(_KEY_TOAST)
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    @pytest.mark.parametrize("via", ["_run_shell_command", "arm_dispatch_window"])
    def test_real_dispatch_rearms_and_opens_the_window(self, t2, failed, via):
        t2._on_chunk(_KEY_TOAST)
        # Repaint do toast com o latch fechado: a frase vai para a cauda.
        t2._on_chunk("\x1b[H" + _KEY_TOAST)
        assert _KEY_TOAST in t2._cli_fatal_tail
        getattr(t2, via)("/loop --task x")
        assert t2._last_failure_reason is None
        assert t2._cli_fatal_tail == ""
        assert t2._dispatch_ts is not None
        # Primeiro chunk benigno do comando novo: a cauda velha nao
        # redispara o vermelho.
        t2._on_chunk("x")
        assert failed == [("workspace", "AUTH_INVALID_API_KEY")]

    @pytest.mark.parametrize("reset", ["_reset_pyte", "_on_pipeline_started", "clear"])
    def test_screen_reset_rearms(self, t2, failed, reset):
        t2._on_chunk(_KEY_TOAST)
        t2._on_chunk("repaint qualquer")
        getattr(t2, reset)()
        assert t2._last_failure_reason is None
        assert t2._cli_fatal_tail == ""

    def test_tail_is_bounded_and_ansi_free(self, t2):
        t2._on_chunk("\x1b[31m" + "x" * (3 * _CLI_FATAL_TAIL_CHARS) + "\x1b[0m")
        assert len(t2._cli_fatal_tail) == _CLI_FATAL_TAIL_CHARS
        assert "\x1b" not in t2._cli_fatal_tail

    def test_osc_payload_never_reaches_the_tail(self, t2):
        # O payload do OSC (titulo de janela) sai junto com o escape.
        t2._on_chunk("\x1b]0;titulo-da-janela\x07ok")
        assert t2._cli_fatal_tail == "ok"
        t2._on_chunk("\x1b]2;outro\x1b\\\x1bM!")
        assert t2._cli_fatal_tail == "ok!"


_F3_SOURCES = {
    "output_panel": inspect.getfile(OutputPanel),
    "enhanced_screen": inspect.getfile(EnhancedScreen),
    "persistent_shell": inspect.getfile(PersistentShell),
    "terminal_helpers": inspect.getfile(is_helper_command),
    "este_teste": __file__,
}


class TestInvariants:
    """Contratos que o resto do app assume sobre os catalogos de padroes."""

    def test_generic_patterns_keep_arity_three(self):
        for entry in _FATAL_PATTERNS:
            assert len(entry) == 3
            assert entry[2] in {"hard", "soft"}

    def test_cli_reasons_reuse_generic_ones_outside_recovery(self):
        generic = {reason for reason, _, _ in _FATAL_PATTERNS}
        scoped = {reason for _, reason, _ in _CLI_SCOPED_FATAL_PATTERNS}
        assert scoped <= generic
        assert not scoped & RECOVERY_REASONS

    def test_cli_names_are_process_basenames(self):
        for cli, _, _ in _CLI_SCOPED_FATAL_PATTERNS:
            assert cli
            assert cli == cli.strip().lower()
            assert "/" not in cli

    @pytest.mark.parametrize(
        "path", list(_F3_SOURCES.values()), ids=list(_F3_SOURCES)
    )
    def test_sources_never_carry_a_trigger_phrase(self, path):
        text = pathlib.Path(path).read_text(encoding="utf-8")
        hits = [reason for _, reason, p in _CLI_SCOPED_FATAL_PATTERNS if p.search(text)]
        assert hits == []


# Dispatch de uma linha que a caixa de input da MiMo quebra no meio da
# agulha do gate (o fim do ultimo token).
_GATED_COMMAND = "/skill:slash-executor /loop --task blacksmith/x/LOOP-CONFIG.json"
_WRAP_AT = _GATED_COMMAND.index("IG.json")
_NEEDLE = OutputPanel._submit_gate_needle(_GATED_COMMAND)


def _paint_input_box(panel: OutputPanel, *, right_border: bool) -> None:
    """Desenha o paste em duas linhas da caixa de input (borda + padding)."""
    rows = [
        "┃  " + _GATED_COMMAND[:_WRAP_AT],
        "┃  " + _GATED_COMMAND[_WRAP_AT:],
    ]
    if right_border:
        rows = [row.ljust(panel._cols - 1) + "┃" for row in rows]
    _paint(panel, f"\x1b[20;1H{rows[0]}\x1b[21;1H{rows[1]}")


class TestNeedleThroughTuiBorder:
    """A borda `┃` da caixa de input partia a agulha do gate de eco no wrap:
    o Enter so saia no teto do gate. `_deborder_rows` tira a borda antes da
    contagem e da checagem do cursor."""

    def test_the_wrap_splits_the_needle(self):
        assert _NEEDLE == "-CONFIG.json"
        assert _GATED_COMMAND[_WRAP_AT:] == "IG.json"

    @pytest.mark.parametrize(
        "right_border", [False, True], ids=["borda-esquerda", "duas-bordas"]
    )
    def test_count_sees_through_the_border(self, t2, right_border):
        _paint_input_box(t2, right_border=right_border)
        rows = t2._screen_rows()
        # Sem tirar a borda nenhum dos blobs antigos acha a agulha.
        assert _NEEDLE not in "\n".join(r.rstrip() for r in rows)
        assert _NEEDLE not in "".join(r.rstrip() for r in rows)
        assert t2._screen_needle_count(_NEEDLE) == 1

    @pytest.mark.parametrize(
        "right_border", [False, True], ids=["borda-esquerda", "duas-bordas"]
    )
    def test_cursor_check_sees_through_the_border(self, t2, right_border):
        _paint_input_box(t2, right_border=right_border)
        assert t2._needle_at_cursor(_NEEDLE) is True

    def test_cursor_check_clears_after_the_submit(self, t2):
        _paint_input_box(t2, right_border=True)
        # Depois do submit a TUI esvazia a caixa: nada de reenvio.
        _paint(t2, "\x1b[20;1H\x1b[2K\x1b[21;1H\x1b[2K┃  ")
        assert t2._needle_at_cursor(_NEEDLE) is False

    def test_gate_releases_the_enter_on_the_bordered_echo(self, t2, qtbot):
        t2._run_shell_command(_GATED_COMMAND)
        assert t2._shell.enters == 0
        _paint_input_box(t2, right_border=True)
        # Metade do teto do gate: o Enter saiu pelo eco, nao pelo timeout.
        qtbot.waitUntil(
            lambda: t2._shell.enters >= 1,
            timeout=OutputPanel._ENTER_GATE_TIMEOUT_MS // 2,
        )

    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            (["┃  abc", "┃  def"], "abcdef"),
            (["  ┃ abc   ┃", "┃ def ┃  "], "abcdef"),
            (["│ abc", "║ def"], "abcdef"),
            (["", "┃", "┃  x"], "x"),
        ],
        ids=["esquerda", "duas-bordas", "outras-bordas", "linhas-vazias"],
    )
    def test_deborder_rows(self, rows, expected):
        assert OutputPanel._deborder_rows(rows) == expected

    def test_deborder_without_a_box_is_the_dewrapped_blob(self):
        rows = ["> /loop --task x   ", "  continua  ", ""]
        assert OutputPanel._deborder_rows(rows) == "".join(r.rstrip() for r in rows)


class TestMimodHelper:
    """`mimod` sobe a MiMo: helper (sem janela early-exit) que rearma o latch."""

    def test_mimod_goes_after_the_existing_helpers(self):
        size = len(_HELPERS_BEFORE_MIMO)
        assert HELPER_COMMANDS[:size] == _HELPERS_BEFORE_MIMO
        assert HELPER_COMMANDS[size] == "mimod"

    @pytest.mark.parametrize("cmd", ["mimod", "MIMOD", "  mimod  "])
    def test_mimod_is_a_helper(self, cmd):
        assert is_helper_command(cmd) is True

    def test_rearm_heads_are_helpers(self):
        assert _CLI_LAUNCH_REARM_HEADS <= set(HELPER_COMMANDS)


class TestMimoEnterFloor:
    """Com a MiMo no Main, o T1 usa o piso lento; o T2 segue o piso base."""

    def test_mimo_is_not_a_fast_enter_llm(self):
        assert "mimo" not in OutputPanel._FAST_ENTER_MAIN_LLMS

    def test_workspace_keeps_the_base_floor(self, t2):
        t2._main_llm = "mimo"
        t2._last_dispatch_head = "/clear"
        assert t2._enter_submit_delay_ms("/loop") == OutputPanel._ENTER_SUBMIT_DELAY_MS

    def test_clear_with_a_trailing_space_opens_the_after_clear_window(self, t1):
        t1._main_llm = "mimo"
        t1._run_shell_command("/clear ")
        assert t1._last_dispatch_head == "/clear"
        assert t1._enter_submit_delay_ms("/loop --task x") == (
            OutputPanel._ENTER_SUBMIT_DELAY_SLOW_MS
            + OutputPanel._ENTER_AFTER_CLEAR_EXTRA_MS
        )


class TestHostsCliBasename:
    """`hosts_cli` casa pelo basename: o `mimod` faz exec e vira `mimo`."""

    def test_exec_keeps_the_basename(self):
        assert cli_name_in_exec_basenames("mimo", ["/opt/mimo/bin/mimo"]) is True

    def test_launcher_name_is_not_the_cli(self):
        assert cli_name_in_exec_basenames("mimo", ["mimod", "zsh"]) is False

    def test_unstarted_shell_hosts_nothing(self, qapp):
        shell = PersistentShell()
        assert shell.pid() is None
        assert shell.hosts_cli("mimo") is False

    def test_hosts_cli_reads_the_descendants(self, qapp):
        shell = PersistentShell()
        shell.descendant_exec_basenames = lambda: frozenset({"zsh", "mimo"})
        assert shell.hosts_cli("mimo") is True
        assert shell.hosts_cli("kimi") is False

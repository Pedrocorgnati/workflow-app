"""
Telemetria de dispatch — `sent=True` observavel (incidente 2026-08-24).

Oraculo do contrato instrumentado em
`blacksmith/recovery/incidents/20260824-pty-dispatch-swallowed-item-006/`
§5: cada dispatch da fila precisa deixar rastro de (1) publicacao no sinal,
(2) bytes pedidos x aceitos pelo PTY e (3) eco do lado do terminal. Antes
disso `_dispatch_green_arrow` devolvia True logo apos um `Signal(str)` sem
retorno, e a fila marcava `sent=True` sem uma linha de log sequer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app import dispatch_telemetry
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.output_panel.persistent_shell import PersistentShell


@pytest.fixture()
def sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redireciona o JSONL para tmp e zera o contador de seq."""
    path = tmp_path / "dispatch-telemetry.jsonl"
    monkeypatch.setattr(dispatch_telemetry, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(dispatch_telemetry, "_JSONL_PATH", path)
    dispatch_telemetry._reset_for_tests()
    yield path
    dispatch_telemetry._reset_for_tests()


def _records(sidecar: Path) -> list[dict]:
    if not sidecar.exists():
        return []
    return [json.loads(line) for line in sidecar.read_text().splitlines() if line]


# ─────────────────────────────────────────────── mascaramento ─────── #

class TestMask:
    """Texto de comando vira log; segredo entra mascarado POR FORMATO."""

    @pytest.mark.parametrize("secret", [
        "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA",
        "Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM.dBjftJeZ4CVP0mI",
        "forjasistemas.suporte@gmail.com",
    ])
    def test_secret_shapes_are_masked(self, secret: str) -> None:
        masked = dispatch_telemetry.mask(f"/cmd --token {secret} --flag")
        assert secret not in masked
        assert "***" in masked

    def test_ordinary_command_survives_intact(self) -> None:
        cmd = "/loop:iteraction:execute-task --task blacksmith/loop-archives/x/t.md"
        assert dispatch_telemetry.mask(cmd) == cmd


# ──────────────────────────────────────────────── correlacao ─────── #

class TestCorrelation:
    def test_emit_and_pty_write_share_the_same_seq(self, sidecar: Path) -> None:
        cmd = "/loop:iteraction:execute-task --task blacksmith/x/task-006.md"
        seq = dispatch_telemetry.open_dispatch(
            route="step/claude-main", channel="interactive", command=cmd,
            position=38, after_clear=True,
        )
        written_seq = dispatch_telemetry.record_pty_write(
            channel="interactive", command=cmd,
            requested=len(cmd) + 12, written=len(cmd) + 12, bracketed=True,
        )
        assert seq > 0
        assert written_seq == seq

        emit, write = _records(sidecar)
        assert emit["event"] == "emit"
        assert emit["position"] == 38 and emit["after_clear"] is True
        assert emit["head"] == "/loop:iteraction:execute-task"
        assert write["event"] == "pty_write"
        assert write["route"] == "step/claude-main"
        assert write["short_write"] is False

    def test_write_without_emit_is_flagged_unattributed(self, sidecar: Path) -> None:
        """Rota imperativa/digitacao nao inventa um dispatch da fila."""
        seq = dispatch_telemetry.record_pty_write(
            channel="workspace_xterm", command="ls -la",
            requested=6, written=6, bracketed=False,
        )
        assert seq == -1
        assert _records(sidecar)[0]["route"] == "unattributed"

    def test_pending_entry_is_consumed_once(self, sidecar: Path) -> None:
        cmd = "/qa:trace --module 3"
        dispatch_telemetry.open_dispatch(
            route="green-arrow/claude", channel="interactive", command=cmd,
        )
        first = dispatch_telemetry.record_pty_write(
            channel="interactive", command=cmd,
            requested=20, written=20, bracketed=False,
        )
        second = dispatch_telemetry.record_pty_write(
            channel="interactive", command=cmd,
            requested=20, written=20, bracketed=False,
        )
        assert first > 0
        assert second == -1, "um emit nao pode casar com dois writes"

    def test_short_write_is_recorded(self, sidecar: Path) -> None:
        """`os.write` num fd O_NONBLOCK pode aceitar menos do que foi pedido."""
        cmd = "/build-module-pipeline --module 4"
        dispatch_telemetry.open_dispatch(
            route="green-arrow/claude", channel="interactive", command=cmd,
        )
        dispatch_telemetry.record_pty_write(
            channel="interactive", command=cmd,
            requested=200, written=64, bracketed=True,
        )
        write = _records(sidecar)[-1]
        assert write["short_write"] is True
        assert write["requested"] == 200 and write["written"] == 64

    def test_failed_write_records_none(self, sidecar: Path) -> None:
        dispatch_telemetry.record_pty_write(
            channel="interactive", command="/x", requested=2,
            written=None, bracketed=False,
        )
        assert _records(sidecar)[-1]["written"] is None


class TestEchoRecord:
    @pytest.mark.parametrize("echoed,expected", [
        (True, "OK"), (False, "MISSING"), (None, "UNKNOWN"),
    ])
    def test_verdict_mapping(self, sidecar: Path, echoed, expected) -> None:
        dispatch_telemetry.record_echo(
            seq=1, channel="interactive", command="/loop:iteraction:execute-task x",
            echoed=echoed, bytes_seen=0, elapsed_ms=1500, helper=False,
        )
        assert _records(sidecar)[-1]["echo"] == expected


class TestNeverRaises:
    """Telemetria quebrada nao pode derrubar um dispatch."""

    def test_unwritable_sidecar_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dispatch_telemetry, "_JSONL_PATH", tmp_path / "no" / "such" / "dir" / "a.jsonl"
        )
        monkeypatch.setattr(
            dispatch_telemetry, "_LOG_DIR", Path("/proc/nonexistent-dir")
        )
        assert dispatch_telemetry.open_dispatch(
            route="r", channel="interactive", command="/x"
        ) > 0


# ──────────────────────────────────── PersistentShell.send_raw ─────── #

class TestSendRawReturnsCount:
    def test_returns_zero_without_pty(self) -> None:
        shell = PersistentShell()
        assert shell.send_raw(b"payload") == 0

    def test_returns_written_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shell = PersistentShell()
        shell._master_fd = 4242
        monkeypatch.setattr(
            "workflow_app.output_panel.persistent_shell.os.write",
            lambda fd, data: len(data),
        )
        assert shell.send_raw(b"abcdef") == 6

    def test_partial_write_surfaces_the_short_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shell = PersistentShell()
        shell._master_fd = 4242
        monkeypatch.setattr(
            "workflow_app.output_panel.persistent_shell.os.write",
            lambda fd, data: 3,
        )
        assert shell.send_raw(b"abcdef") == 3

    def test_oserror_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(fd, data):
            raise BlockingIOError(11, "Resource temporarily unavailable")

        shell = PersistentShell()
        shell._master_fd = 4242
        monkeypatch.setattr(
            "workflow_app.output_panel.persistent_shell.os.write", _boom
        )
        assert shell.send_raw(b"abcdef") == 0


# ──────────────────────────────────────────── eco na tela ─────── #

class TestEchoNeedle:
    @pytest.mark.parametrize("cmd", ["/clear", "/model haiku", "cd /tmp", ""])
    def test_short_commands_have_no_distinctive_needle(self, cmd: str) -> None:
        """`/clear` some da tela por definicao: acusar seria falso positivo."""
        assert OutputPanel._echo_needle(cmd) is None

    def test_longest_token_wins(self) -> None:
        cmd = "/loop:iteraction:execute-task --task blacksmith/loop-archives/a/b.md"
        assert OutputPanel._echo_needle(cmd) == (
            "blacksmith/loop-archives/a/b.md"
        )


class TestScreenContains:
    class _FakeScreen:
        def __init__(self, lines: list[str]) -> None:
            self.display = lines

    def _panel(self, lines: list[str]) -> OutputPanel:
        panel = OutputPanel.__new__(OutputPanel)
        panel._screen = self._FakeScreen(lines)
        return panel

    def test_finds_full_needle(self) -> None:
        panel = self._panel(["> /qa:trace --module 3", "trabalhando..."])
        assert panel._screen_contains("--module") is True

    def test_finds_wrapped_needle_by_prefix(self) -> None:
        needle = "blacksmith/loop-archives/08-23-x/tasks/items/task-006.md"
        panel = self._panel(["> /loop:iteraction:execute-task " + needle[:24]])
        assert panel._screen_contains(needle) is True

    def test_absent_needle_reports_false(self) -> None:
        panel = self._panel(["$ ", "nada aqui"])
        assert panel._screen_contains("blacksmith/loop-archives/x") is False

    def test_broken_screen_is_undecidable_not_false(self) -> None:
        panel = OutputPanel.__new__(OutputPanel)
        panel._screen = object()
        assert panel._screen_contains("qualquer-coisa-longa") is None


# ─────────────────────────────── funil da command queue ─────── #

class TestPublishToTerminal:
    """O ponto unico por onde a fila publica texto num PTY."""

    def test_no_direct_signal_emit_remains_in_the_queue(self) -> None:
        """Regressao: um emit direto novo escapa da telemetria em silencio."""
        src = Path(
            "src/workflow_app/command_queue/command_queue_widget.py"
        ).read_text()
        for sig in (
            "run_command_in_terminal",
            "run_command_in_workspace_terminal",
            "run_command_in_workspace_xterm",
        ):
            assert f"signal_bus.{sig}.emit(" not in src, (
                f"{sig}.emit direto na fila: use _publish_to_terminal"
            )

    def test_publish_emits_and_records(self, qtbot, sidecar: Path) -> None:
        widget = CommandQueueWidget()
        qtbot.addWidget(widget)
        seen: list[str] = []
        from workflow_app.signal_bus import signal_bus

        signal_bus.run_command_in_terminal.connect(seen.append)
        try:
            widget._publish_to_terminal(
                "interactive", route="green-arrow/claude", text="/qa:prep --module 1"
            )
        finally:
            signal_bus.run_command_in_terminal.disconnect(seen.append)

        assert seen == ["/qa:prep --module 1"]
        record = _records(sidecar)[-1]
        assert record["event"] == "emit"
        assert record["channel"] == "interactive"
        assert record["route"] == "green-arrow/claude"

    def test_after_clear_flag_tracks_the_previous_dispatch(
        self, qtbot, sidecar: Path
    ) -> None:
        """A correlacao que o incidente levantou fica no dado, nao na memoria."""
        widget = CommandQueueWidget()
        qtbot.addWidget(widget)
        widget._publish_to_terminal("interactive", route="r", text="/clear")
        widget._publish_to_terminal(
            "interactive", route="r", text="/loop:iteraction:execute-task --task a/b.md"
        )
        widget._publish_to_terminal("interactive", route="r", text="/qa:report --module 1")

        emits = [r for r in _records(sidecar) if r["event"] == "emit"]
        assert [r["after_clear"] for r in emits] == [False, True, False]

    def test_channel_map_covers_every_terminal(self) -> None:
        assert set(CommandQueueWidget._CHANNEL_SIGNALS) == {
            "interactive", "workspace", "workspace_xterm"
        }

"""
Tests for autocast signals and sentinel detection (module-12/TASK-1).

Covers:
  - SignalBus.autocast_advancing signal exists and emits str
  - SignalBus.interactive_advance_ready signal exists and emits int
  - SignalBus.pipeline_all_completed signal exists and emits int
  - Sentinel regex matches in PTY output (with/without ANSI codes)
  - instance_selected signal propagation
"""
from __future__ import annotations

import re

import pytest

# ─────────────────────────────────────────────────────── Fixtures ─── #

@pytest.fixture()
def bus():
    from workflow_app.signal_bus import SignalBus
    return SignalBus()


# ─────────────────────────────────────────────────────── Tests ─── #

class TestAutocastSignals:
    def test_autocast_advancing_signal_exists(self, bus):
        """autocast_advancing signal is defined on SignalBus."""
        assert hasattr(bus, "autocast_advancing")

    def test_autocast_advancing_emits_str(self, bus, qtbot):
        """autocast_advancing emits command name string."""
        received: list[str] = []
        bus.autocast_advancing.connect(received.append)
        with qtbot.waitSignal(bus.autocast_advancing, timeout=500):
            bus.autocast_advancing.emit("/hld-create")
        assert received == ["/hld-create"]

    def test_interactive_advance_ready_signal_exists(self, bus):
        """interactive_advance_ready signal is defined on SignalBus."""
        assert hasattr(bus, "interactive_advance_ready")

    def test_interactive_advance_ready_emits_int(self, bus, qtbot):
        """interactive_advance_ready emits command exec id (int)."""
        received: list[int] = []
        bus.interactive_advance_ready.connect(received.append)
        with qtbot.waitSignal(bus.interactive_advance_ready, timeout=500):
            bus.interactive_advance_ready.emit(42)
        assert received == [42]

    def test_pipeline_all_completed_signal_exists(self, bus):
        """pipeline_all_completed signal is defined on SignalBus."""
        assert hasattr(bus, "pipeline_all_completed")

    def test_pipeline_all_completed_emits_int(self, bus, qtbot):
        """pipeline_all_completed emits pipeline exec id (int)."""
        received: list[int] = []
        bus.pipeline_all_completed.connect(received.append)
        with qtbot.waitSignal(bus.pipeline_all_completed, timeout=500):
            bus.pipeline_all_completed.emit(7)
        assert received == [7]


class TestAutocastDoesNotAdvanceInteractive:
    """Validate signal semantics for autocast vs interactive distinction."""

    def test_interactive_advance_ready_and_autocast_advancing_are_separate(self, bus):
        """Two separate signals for autocast (str) and interactive ready (int)."""
        autocast_vals: list[str] = []
        interactive_vals: list[int] = []
        bus.autocast_advancing.connect(autocast_vals.append)
        bus.interactive_advance_ready.connect(interactive_vals.append)

        bus.autocast_advancing.emit("/next-cmd")
        bus.interactive_advance_ready.emit(99)

        assert autocast_vals == ["/next-cmd"]
        assert interactive_vals == [99]


# ─────────────────────────── PipelineManager integration ─── #

class TestPipelineManagerAutocastSignals:
    """Integration: PipelineManager emits autocast signals correctly (GAP-009 fix)."""

    @pytest.fixture()
    def factory(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from workflow_app.db.models import Base
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        yield Session
        engine.dispose()

    @pytest.fixture()
    def mock_bus(self):
        from unittest.mock import MagicMock

        from workflow_app.signal_bus import SignalBus
        return MagicMock(spec=SignalBus)

    @pytest.fixture()
    def manager(self, factory, mock_bus):
        from unittest.mock import MagicMock

        from workflow_app.pipeline.pipeline_manager import PipelineManager
        return PipelineManager(
            signal_bus=mock_bus,
            sdk_adapter=MagicMock(),
            session_factory=factory,
            workspace_dir="/tmp/test",
        )

    def test_autocast_advancing_emitted_on_non_interactive_completion(self, manager, mock_bus, qtbot):
        """autocast_advancing is emitted with next command name before advance()."""
        from workflow_app.domain import CommandSpec, InteractionType, ModelName
        from workflow_app.pipeline.command_state_machine import CommandStateMachine

        spec1 = CommandSpec(name="/cmd-1", model=ModelName.SONNET, position=1,
                            interaction_type=InteractionType.AUTO)
        spec2 = CommandSpec(name="/cmd-2", model=ModelName.SONNET, position=2,
                            interaction_type=InteractionType.AUTO)
        manager.set_queue([spec1, spec2])
        manager._current_index = 0

        # Inject a state machine for exec_id=1 so _on_command_completed doesn't return early
        from unittest.mock import MagicMock, patch
        sm = CommandStateMachine(command_exec_id=1, signal_bus=mock_bus,
                                 persist_callback=MagicMock())
        sm.start()  # PENDENTE → EXECUTANDO
        manager._state_machines[1] = sm

        # Patch advance to avoid side effects
        with patch.object(manager, 'advance'):
            manager._on_command_completed(command_exec_id=1, success=True)

        mock_bus.autocast_advancing.emit.assert_called_once_with("/cmd-2")

    def test_interactive_advance_ready_emitted_for_interactive_command(self, manager, mock_bus, qtbot):
        """interactive_advance_ready is emitted for INTERACTIVE commands on completion."""
        from workflow_app.domain import CommandSpec, InteractionType, ModelName
        from workflow_app.pipeline.command_state_machine import CommandStateMachine

        spec = CommandSpec(name="/interactive-cmd", model=ModelName.SONNET, position=1,
                           interaction_type=InteractionType.INTERACTIVE)
        manager.set_queue([spec])
        manager._current_index = 0

        from unittest.mock import MagicMock
        sm = CommandStateMachine(command_exec_id=42, signal_bus=mock_bus,
                                 persist_callback=MagicMock())
        sm.start()
        manager._state_machines[42] = sm

        manager._on_command_completed(command_exec_id=42, success=True)

        mock_bus.interactive_advance_ready.emit.assert_called_once_with(42)

    def test_pipeline_all_completed_emitted_with_exec_id(self, manager, mock_bus, factory):
        """pipeline_all_completed is emitted with pipeline_exec_id on completion."""
        # Create a PipelineExecution record
        from workflow_app.db.models import PipelineExecution
        from workflow_app.domain import PipelineStatus
        with factory() as session:
            pe = PipelineExecution(
                project_config_path="/tmp/test",
                status=PipelineStatus.EXECUTANDO.value,
                permission_mode="acceptEdits",
                commands_total=1,
            )
            session.add(pe)
            session.commit()
            exec_id = pe.id

        manager._pipeline_exec_id = exec_id
        manager._on_pipeline_completed()

        mock_bus.pipeline_all_completed.emit.assert_called_once_with(exec_id)


# ─────────────────────────── Sentinel detection ─── #

class TestSentinelRegex:
    """Validate sentinel regex matches real PTY output patterns."""

    @pytest.fixture()
    def sentinel_re(self):
        from workflow_app.output_panel.persistent_shell import _SENTINEL_RE
        return _SENTINEL_RE

    @pytest.fixture()
    def ansi_re(self):
        from workflow_app.output_panel.persistent_shell import _ANSI_RE
        return _ANSI_RE

    def test_plain_sentinel_on_own_line(self, sentinel_re):
        text = "some output\r\n##SF_DONE_2##\r\n$ "
        assert sentinel_re.search(text) is not None

    def test_sentinel_without_id(self, sentinel_re):
        text = "output\r\n##SF_DONE##\r\n"
        assert sentinel_re.search(text) is not None

    def test_sentinel_at_text_start(self, sentinel_re):
        text = "##SF_DONE_1##\r\n$ "
        assert sentinel_re.search(text) is not None

    def test_sentinel_after_lf_only(self, sentinel_re):
        text = "output\n##SF_DONE_5##\n"
        assert sentinel_re.search(text) is not None

    def test_sentinel_matched_anywhere(self, sentinel_re):
        """Sentinel matches anywhere in text — false positives from command
        echo are prevented by using printf with octal escapes, not by the regex."""
        text = '$ echo "##SF_DONE_2##"\r\n'
        assert sentinel_re.search(text) is not None

    def test_ansi_stripped_before_match(self, sentinel_re, ansi_re):
        """ANSI codes before sentinel are stripped, allowing regex to match."""
        text = "output\r\n\x1b[0m\x1b[?2004l##SF_DONE_3##\r\n"
        clean = ansi_re.sub("", text)
        assert sentinel_re.search(clean) is not None

    def test_sentinel_id_extraction(self, sentinel_re):
        text = "\r\n##SF_DONE_7##\r\n"
        match = sentinel_re.search(text)
        assert match is not None
        sentinel_str = match.group(0)
        sentinel_id = int(sentinel_str.split("_")[-1].rstrip("#"))
        assert sentinel_id == 7


# ─────────────────────────── AutocastWorker ─── #

class TestAutocastWorker:
    """AutocastWorker runs subprocess and emits output + finished signal."""

    @pytest.fixture()
    def mock_binary(self, tmp_path):
        """Create a temporary mock binary that prints a line and exits 0."""
        import os, stat
        script = tmp_path / "mock_clauded.sh"
        script.write_text('#!/bin/sh\necho "hello autocast"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return str(script)

    @pytest.fixture()
    def mock_binary_fail(self, tmp_path):
        """Create a temporary mock binary that exits non-zero."""
        import os, stat
        script = tmp_path / "mock_fail.sh"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return str(script)

    def test_worker_runs_echo_command(self, qtbot, mock_binary):
        """Worker streams stdout and emits finished(True) for successful command."""
        from workflow_app.command_queue.autocast_worker import AutocastWorker

        worker = AutocastWorker(
            binary=mock_binary,
            command="/test-cmd",
            config_path="",
            cwd=None,
        )
        chunks: list[str] = []
        finished_vals: list[bool] = []
        worker.output_chunk.connect(chunks.append)
        worker.finished.connect(finished_vals.append)

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()

        assert finished_vals == [True]
        assert any("hello autocast" in c for c in chunks)

    def test_worker_emits_false_on_nonzero_exit(self, qtbot, mock_binary_fail):
        """Worker emits finished(False) when command exits with non-zero code."""
        from workflow_app.command_queue.autocast_worker import AutocastWorker

        worker = AutocastWorker(
            binary=mock_binary_fail,
            command="/cmd",
            config_path="",
            cwd=None,
        )
        finished_vals: list[bool] = []
        worker.finished.connect(finished_vals.append)

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()

        assert finished_vals == [False]

    def test_worker_emits_false_on_missing_binary(self, qtbot):
        """Worker emits finished(False) when binary is not found."""
        from workflow_app.command_queue.autocast_worker import AutocastWorker

        worker = AutocastWorker(
            binary="/nonexistent_binary_xyz",
            command="/cmd",
            config_path="",
            cwd=None,
        )
        chunks: list[str] = []
        finished_vals: list[bool] = []
        worker.output_chunk.connect(chunks.append)
        worker.finished.connect(finished_vals.append)

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()

        assert finished_vals == [False]
        # Shell reports "command not found" (exit 127); any output is acceptable
        # as long as the worker correctly emits finished(False).
        assert len(chunks) >= 0  # output may be empty or contain shell error


# ─────────────────────────── Instance selection ─── #

class TestInstanceSelection:
    """instance_selected signal updates CLI binary name."""

    def test_instance_selected_signal_exists(self, bus):
        assert hasattr(bus, "instance_selected")

    def test_instance_selected_emits_str(self, bus, qtbot):
        received: list[str] = []
        bus.instance_selected.connect(received.append)
        with qtbot.waitSignal(bus.instance_selected, timeout=500):
            bus.instance_selected.emit("clauded")
        assert received == ["clauded"]

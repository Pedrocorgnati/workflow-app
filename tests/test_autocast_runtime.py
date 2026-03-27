from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from workflow_app.command_queue.autocast_cli import build_launch_plan, resolve_instance_profile
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, CommandStatus, InteractionType, ModelName
from workflow_app.signal_bus import signal_bus


class FakeRunner(QObject):
    output_received = Signal(str)
    command_completed = Signal(str, bool)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.started: list[dict] = []
        self.terminated = False

    def start_process(self, *, argv, command_name, cwd=None, env_overrides=None) -> None:
        self.started.append(
            {
                "argv": list(argv),
                "command_name": command_name,
                "cwd": cwd,
                "env_overrides": dict(env_overrides or {}),
            }
        )

    def terminate(self) -> None:
        self.terminated = True

    def resize(self, _cols: int, _rows: int) -> None:
        pass

    def send_raw(self, _data: bytes) -> None:
        pass


def _spec(
    name: str,
    *,
    interaction: InteractionType = InteractionType.AUTO,
    model: ModelName = ModelName.SONNET,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=interaction,
        position=1,
        config_path=".claude/project.json",
    )


def test_resolve_instance_profile_for_clauded2_sets_dedicated_env():
    profile = resolve_instance_profile("clauded2")
    assert profile.executable == "claude"
    assert profile.prefix_args == ("--dangerously-skip-permissions",)
    assert profile.env_overrides["CLAUDE_CONFIG_DIR"].endswith(".claude-email2")


def test_build_launch_plan_for_auto_command_uses_print_mode():
    plan = build_launch_plan(_spec("/prd-create"), "clauded")
    assert plan.channel == "interactive"
    assert plan.argv[:3] == (
        "claude",
        "--dangerously-skip-permissions",
        "-p",
    )
    assert plan.argv[-2:] == ("--model", "sonnet")


def test_build_launch_plan_rejects_codex_instances():
    try:
        build_launch_plan(_spec("/prd-create"), "codex")
    except ValueError as exc:
        assert "não suporta" in str(exc)
    else:
        raise AssertionError("codex should be rejected for workflow slash commands")


def test_autocast_advances_only_after_runner_completion(qapp, qtbot):
    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.show()

    specs = [
        CommandSpec("/cmd-1", ModelName.SONNET, InteractionType.AUTO, position=1, config_path=".claude/project.json"),
        CommandSpec("/cmd-2", ModelName.OPUS, InteractionType.AUTO, position=2, config_path=".claude/project.json"),
    ]
    widget.load_pipeline(specs)

    created: list[FakeRunner] = []

    def _make_runner() -> FakeRunner:
        runner = FakeRunner()
        created.append(runner)
        return runner

    widget._create_autocast_runner = _make_runner  # type: ignore[method-assign]

    widget._start_autocast()

    assert widget._autocast_active is True
    assert len(created) == 1
    assert widget._items[0]._status == CommandStatus.EXECUTANDO
    assert widget._items[1]._status == CommandStatus.PENDENTE

    created[0].command_completed.emit("/cmd-1", True)
    qtbot.waitUntil(lambda: len(created) == 2)

    assert widget._items[0]._status == CommandStatus.CONCLUIDO
    assert widget._items[1]._status == CommandStatus.EXECUTANDO

    created[1].command_completed.emit("/cmd-2", True)
    qtbot.waitUntil(lambda: widget._autocast_active is False)

    assert widget._items[1]._status == CommandStatus.CONCLUIDO


def test_autocast_interactive_command_binds_to_interactive_terminal(qapp, qtbot):
    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.show()

    spec = CommandSpec(
        "/interactive-cmd",
        ModelName.HAIKU,
        InteractionType.INTERACTIVE,
        position=1,
        config_path=".claude/project.json",
    )
    widget.load_pipeline([spec])

    runner = FakeRunner()
    widget._create_autocast_runner = lambda: runner  # type: ignore[method-assign]

    started_channels: list[str] = []
    focused: list[bool] = []
    signal_bus.terminal_session_started.connect(started_channels.append)
    signal_bus.focus_interactive_terminal.connect(lambda: focused.append(True))

    widget._start_autocast()

    assert started_channels[-1] == "interactive"
    assert focused == [True]
    assert runner.started[0]["argv"][2] == "/interactive-cmd"
    assert widget._items[0]._status == CommandStatus.EXECUTANDO


def test_autocast_stop_terminates_runner_and_restores_pending(qapp, qtbot):
    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.show()

    widget.load_pipeline([_spec("/cmd-stop")])
    runner = FakeRunner()
    widget._create_autocast_runner = lambda: runner  # type: ignore[method-assign]

    widget._start_autocast()
    assert widget._items[0]._status == CommandStatus.EXECUTANDO

    widget._stop_autocast()

    assert runner.terminated is True
    assert widget._items[0]._status == CommandStatus.PENDENTE
    assert widget._autocast_active is False


def test_autocast_marks_error_and_stops_on_failed_exit(qapp, qtbot):
    widget = CommandQueueWidget()
    qtbot.addWidget(widget)
    widget.show()

    widget.load_pipeline([_spec("/cmd-fail")])
    runner = FakeRunner()
    widget._create_autocast_runner = lambda: runner  # type: ignore[method-assign]

    widget._start_autocast()
    runner.error_occurred.emit("boom")
    runner.command_completed.emit("/cmd-fail", False)

    qtbot.waitUntil(lambda: widget._autocast_active is False)
    assert widget._items[0]._status == CommandStatus.ERRO

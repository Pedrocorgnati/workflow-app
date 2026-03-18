"""Tests for SDKWorker bidirectional interactive session (module-09/TASK-3)."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.sdk.sdk_worker import SDKWorker


@pytest.fixture()
def interactive_spec() -> CommandSpec:
    return CommandSpec(
        name="/interview",
        model=ModelName.SONNET,
        interaction_type=InteractionType.INTERACTIVE,
        position=0,
    )


def test_interactive_flow(qapp, qtbot, interactive_spec):
    """SDKWorker emits interactive_prompt, waits for input, then completes."""

    class FakeChunk:
        type = "interactive_prompt"
        text = "Qual é o nome do projeto?"

    async def fake_interactive(**kwargs):
        yield "Iniciando entrevista...\n"
        yield FakeChunk()
        yield "Obrigado pela resposta!\n"

    adapter = MagicMock()
    adapter.run_command = fake_interactive
    adapter.send_input = AsyncMock()

    worker = SDKWorker(interactive_spec, workspace_dir="/tmp/project")
    worker.set_sdk_adapter(adapter)

    prompts: list[str] = []
    worker.interactive_prompt.connect(prompts.append)

    completed: list[tuple] = []
    worker.command_completed.connect(lambda name, ok: completed.append((name, ok)))

    def send_after_prompt(question: str) -> None:
        # Simulate user typing after receiving the prompt
        worker.send_user_input("Meu Projeto")

    worker.interactive_prompt.connect(send_after_prompt)

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()

    assert prompts == ["Qual é o nome do projeto?"]
    assert completed == [("/interview", True)]


def test_interactive_timeout(qapp, qtbot, interactive_spec):
    """SDKWorker emits error_occurred after timeout (mocked to 0.15s)."""

    class FakePrompt:
        type = "interactive_prompt"
        text = "Responda rápido"

    async def fake_timeout_run(**kwargs):
        yield FakePrompt()

    adapter = MagicMock()
    adapter.run_command = fake_timeout_run
    adapter.send_input = AsyncMock()

    worker = SDKWorker(interactive_spec, workspace_dir="/tmp/project")
    worker.set_sdk_adapter(adapter)

    # Override _wait_for_user_input with a very short timeout
    async def fast_timeout(self_inner):
        await asyncio.sleep(0.15)
        raise asyncio.TimeoutError()

    worker._wait_for_user_input = types.MethodType(fast_timeout, worker)

    errors: list[str] = []
    worker.error_occurred.connect(errors.append)

    completed: list[tuple] = []
    worker.command_completed.connect(lambda name, ok: completed.append((name, ok)))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()

    assert any("Timeout" in e or "TimeoutError" in e for e in errors)
    assert completed == [("/interview", False)]


def test_non_interactive_spec_uses_streaming_path(qapp, qtbot):
    """CommandSpec with AUTO interaction_type uses _execute_streaming (not interactive)."""

    auto_spec = CommandSpec(
        name="/prd-create",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=0,
    )

    # A prompt chunk should NOT trigger interactive_prompt signal in AUTO mode
    class FakePromptChunk:
        type = "interactive_prompt"
        text = "Should not happen"

    async def fake_run(**kwargs):
        yield "plain text\n"
        yield FakePromptChunk()

    adapter = MagicMock()
    adapter.run_command = fake_run

    worker = SDKWorker(auto_spec, workspace_dir="/tmp")
    worker.set_sdk_adapter(adapter)

    prompts: list[str] = []
    worker.interactive_prompt.connect(prompts.append)

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()

    # In streaming mode, interactive_prompt should NOT be emitted
    assert prompts == []

"""Tests for SDKWorker (module-09/TASK-1)."""

from __future__ import annotations

import asyncio
import gc

import pytest

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.sdk.sdk_worker import SDKWorker


@pytest.fixture()
def command_spec() -> CommandSpec:
    return CommandSpec(
        name="/prd-create",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=0,
    )


def test_sdk_worker_emits_output(qapp, qtbot, command_spec):
    """SDKWorker emits output_received for each chunk from the mock SDKAdapter."""

    async def fake_run_command(**kwargs):
        for chunk in ["chunk-a", "chunk-b", "chunk-c"]:
            yield chunk

    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter.run_command = fake_run_command

    worker = SDKWorker(command_spec, workspace_dir="/tmp/project")
    worker.set_sdk_adapter(adapter)

    received: list[str] = []
    worker.output_received.connect(received.append)

    completed: list[tuple] = []
    worker.command_completed.connect(lambda name, ok: completed.append((name, ok)))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()

    assert received == ["chunk-a", "chunk-b", "chunk-c"]
    assert completed == [("/prd-create", True)]


def test_sdk_worker_emits_error_on_exception(qapp, qtbot, command_spec):
    """SDKWorker emits error_occurred and command_completed(False) on exception."""

    async def bad_run_command(**kwargs):
        raise RuntimeError("SDK falhou")
        yield  # makes it an async generator

    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter.run_command = bad_run_command

    worker = SDKWorker(command_spec, workspace_dir="/tmp/project")
    worker.set_sdk_adapter(adapter)

    errors: list[str] = []
    worker.error_occurred.connect(errors.append)

    completed: list[tuple] = []
    worker.command_completed.connect(lambda name, ok: completed.append((name, ok)))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()

    assert len(errors) == 1
    assert "SDK falhou" in errors[0]
    assert completed == [("/prd-create", False)]


def test_sdk_worker_not_gc_while_running(qapp, qtbot, command_spec):
    """Worker kept in a list is not GC-collected before finished is emitted."""
    workers: list[SDKWorker] = []

    async def slow_run_command(**kwargs):
        await asyncio.sleep(0.05)
        yield "ok"

    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter.run_command = slow_run_command

    worker = SDKWorker(command_spec, workspace_dir="/tmp/project")
    worker.set_sdk_adapter(adapter)
    workers.append(worker)
    worker.finished.connect(lambda: workers.remove(worker))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()
        gc.collect()  # force GC during execution — worker is still in workers[]

    assert len(workers) == 0  # removed after finished


def test_sdk_worker_model_conversion(qapp, qtbot):
    """SDKWorker converts ModelName (Opus/Sonnet/Haiku) to ModelType correctly."""
    from workflow_app.domain import ModelType

    received_models: list[ModelType] = []

    async def capturing_adapter(**kwargs):
        received_models.append(kwargs.get("model"))
        yield "ok"

    from unittest.mock import MagicMock

    for model_name in (ModelName.HAIKU, ModelName.SONNET, ModelName.OPUS):
        spec = CommandSpec(name="/test", model=model_name, position=0)
        adapter = MagicMock()
        adapter.run_command = capturing_adapter

        worker = SDKWorker(spec, workspace_dir="/tmp")
        worker.set_sdk_adapter(adapter)

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()

    assert len(received_models) == 3
    # ModelName values are title-case ("Haiku"); ModelType values are lower-case ("haiku")
    for model_type in received_models:
        assert isinstance(model_type, ModelType)
    assert set(received_models) == {ModelType.HAIKU, ModelType.SONNET, ModelType.OPUS}

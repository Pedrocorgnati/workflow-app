"""
Tests for SDKAdapter core (module-08/TASK-1/ST003 + TASK-5 audit).

Covers:
  - Streaming chunks via mocked _stream_query
  - is_running state management
  - cancel_current() stops iteration
  - SDKExecutionError propagation
  - permission_mode and workspace_dir passed to _stream_query
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from workflow_app.domain import ModelType
from workflow_app.errors import SDKExecutionError
from workflow_app.sdk.sdk_adapter import (
    SDKAdapter,
)


def _make_async_gen(*chunks: str):
    """Return an async generator that yields the given string chunks."""

    async def _gen(**kwargs):
        for chunk in chunks:
            yield chunk

    return _gen


class TestSDKAdapterRunCommand:
    def test_sdk_adapter_runs_command_mock(self):
        """Verifies chunk streaming via mocked _stream_query."""
        adapter = SDKAdapter()

        async def mock_stream(**kwargs):
            yield "Analisando INTAKE..."
            yield "PRD criado com sucesso."

        async def collect():
            chunks = []
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for chunk in adapter.run_command("prd-create", ModelType.SONNET):
                    chunks.append(chunk)
            return chunks

        result = asyncio.run(collect())
        assert result == ["Analisando INTAKE...", "PRD criado com sucesso."]

    def test_is_running_false_after_completion(self):
        adapter = SDKAdapter()

        async def mock_stream(**kwargs):
            yield "done"

        async def run():
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for _ in adapter.run_command("prd-create", ModelType.SONNET):
                    assert adapter.is_running is True
            assert adapter.is_running is False

        asyncio.run(run())

    def test_cancel_stops_iteration(self):
        adapter = SDKAdapter()
        chunks_received = []

        async def mock_stream(**kwargs):
            for i in range(10):
                yield f"chunk-{i}"

        async def run():
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for chunk in adapter.run_command("prd-create", ModelType.SONNET):
                    chunks_received.append(chunk)
                    if len(chunks_received) == 2:
                        adapter.cancel_current()

        asyncio.run(run())
        assert len(chunks_received) <= 4  # margin for timing

    def test_sdk_execution_error_propagates(self):
        adapter = SDKAdapter()

        async def mock_stream(**kwargs):
            raise RuntimeError("API timeout")
            yield  # make it a generator

        async def run():
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for _ in adapter.run_command("prd-create", ModelType.SONNET):
                    pass

        with pytest.raises(SDKExecutionError, match="prd-create"):
            asyncio.run(run())

    def test_permission_mode_passed_to_stream_query(self):
        adapter = SDKAdapter()
        received_kwargs: dict = {}

        async def mock_stream(**kwargs):
            received_kwargs.update(kwargs)
            yield "ok"

        async def run():
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for _ in adapter.run_command(
                    "prd-create",
                    ModelType.SONNET,
                    permission_mode="autoAccept",
                ):
                    pass

        asyncio.run(run())
        assert received_kwargs.get("permission_mode") == "autoAccept"

    def test_workspace_dir_passed_to_stream_query(self):
        """workspace_dir should be forwarded to _stream_query."""
        adapter = SDKAdapter()
        received_kwargs: dict = {}

        async def mock_stream(**kwargs):
            received_kwargs.update(kwargs)
            yield "ok"

        async def run():
            with patch.object(adapter, "_stream_query", side_effect=mock_stream):
                async for _ in adapter.run_command(
                    "prd-create",
                    ModelType.SONNET,
                    workspace_dir="/tmp/test-workspace",
                ):
                    pass

        asyncio.run(run())
        assert received_kwargs.get("workspace_dir") == "/tmp/test-workspace"


class TestSDKAdapterState:
    """Tests for is_running and cancel_current state management."""

    def test_is_running_false_initially(self):
        adapter = SDKAdapter()
        assert adapter.is_running is False

    def test_current_command_none_initially(self):
        adapter = SDKAdapter()
        assert adapter.current_command is None

    def test_sdk_client_initially_none(self):
        adapter = SDKAdapter()
        assert adapter._sdk_client is None

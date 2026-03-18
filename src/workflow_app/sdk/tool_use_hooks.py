"""
ToolUseHookMixin — Non-blocking hooks for tool-use events (module-09/TASK-4).

Mixin that adds PreToolUse and PostToolUse tracking to SDKWorker.
Logs to ExecutionLog (DB) and emits tool_use_started / tool_use_completed
via SignalBus for MetricsBar to update counters in real-time.

All exceptions are swallowed silently — hook failures must never interrupt
pipeline execution.

Requirements (set via SDKWorker.set_execution_context):
  - self._session_factory: sessionmaker
  - self._pipeline_id: int
  - self._command_exec_id: Optional[int]
  - self._signal_bus: SignalBus instance
"""

from __future__ import annotations

import sys
import time


class ToolUseHookMixin:
    """Mixin of PreToolUse/PostToolUse hooks for SDKWorker.

    All attributes are injected optionally — missing attributes are caught
    silently, making the mixin safe even when set_execution_context()
    has not been called.
    """

    def on_pre_tool_use(
        self,
        tool_name: str,
        input_summary: str,
    ) -> float | None:
        """Called before each tool use. Returns monotonic start timestamp."""
        start_time = time.monotonic()

        try:
            from workflow_app.db.models import ExecutionLog  # noqa: PLC0415

            with self._session_factory() as session:
                log = ExecutionLog(
                    pipeline_id=self._pipeline_id,
                    command_execution_id=self._command_exec_id,
                    level="info",
                    message=f"[PRE] tool={tool_name} input={input_summary[:200]}",
                )
                session.add(log)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            print(
                f"[ToolUseHookMixin] pre_tool_use falhou: {exc}",
                file=sys.stderr,
            )

        try:
            self._signal_bus.tool_use_started.emit(tool_name)
        except Exception:  # noqa: BLE001
            pass

        return start_time

    def on_post_tool_use(
        self,
        tool_name: str,
        output_summary: str,
        start_time: float | None = None,
    ) -> None:
        """Called after each tool use completes."""
        duration_ms = 0
        if start_time is not None:
            duration_ms = int((time.monotonic() - start_time) * 1000)

        try:
            from workflow_app.db.models import ExecutionLog  # noqa: PLC0415

            with self._session_factory() as session:
                log = ExecutionLog(
                    pipeline_id=self._pipeline_id,
                    command_execution_id=self._command_exec_id,
                    level="info",
                    message=(
                        f"[POST] tool={tool_name} "
                        f"output={output_summary[:200]} "
                        f"duration_ms={duration_ms}"
                    ),
                )
                session.add(log)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            print(
                f"[ToolUseHookMixin] post_tool_use falhou: {exc}",
                file=sys.stderr,
            )

        try:
            self._signal_bus.tool_use_completed.emit(tool_name, duration_ms)
        except Exception:  # noqa: BLE001
            pass

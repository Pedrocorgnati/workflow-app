"""Registry of local actions (in-process Python callables) for the pipeline.

A local action is an alternative to a slash command paste: instead of forwarding
the spec to Claude via PTY, the pipeline manager invokes a Python callable
registered here under a stable string id (`local_action_id`). The callable
receives the originating CommandSpec and returns a bool (True == success).

This module is intentionally framework-free: no Qt imports, no logger setup,
no UI references. It is consumed by `pipeline_manager.PipelineManager` to
dispatch `CommandSpec` instances whose `kind == "local-action"`.
"""

from __future__ import annotations

from typing import Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from workflow_app.domain import CommandSpec

LocalActionCallable = Callable[["CommandSpec"], bool]

_local_actions: Dict[str, LocalActionCallable] = {}


def register_local_action(action_id: str, callable_: LocalActionCallable) -> None:
    """Register a callable under `action_id`. Overwrites any prior registration."""
    if not isinstance(action_id, str) or not action_id:
        raise ValueError("action_id must be a non-empty string")
    if not callable(callable_):
        raise TypeError(f"callable_ for {action_id!r} is not callable")
    _local_actions[action_id] = callable_


def unregister_local_action(action_id: str) -> None:
    """Remove `action_id` from the registry if present (idempotent)."""
    _local_actions.pop(action_id, None)


def get_local_action(action_id: str) -> LocalActionCallable | None:
    """Return the registered callable, or None when unknown."""
    return _local_actions.get(action_id)


def dispatch_local_action(action_id: str | None, spec: "CommandSpec") -> bool:
    """Invoke the local action registered under `action_id` with `spec`.

    Returns the boolean returned by the callable, or False when:
    - `action_id` is None / empty / not registered
    - the callable raises an exception
    """
    if not action_id:
        return False
    handler = _local_actions.get(action_id)
    if handler is None:
        return False
    try:
        result = handler(spec)
    except Exception:
        return False
    return bool(result)


def clear_registry() -> None:
    """Test-only: wipe the registry between cases."""
    _local_actions.clear()

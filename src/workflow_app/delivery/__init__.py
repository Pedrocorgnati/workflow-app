"""workflow_app.delivery — Qt-side bridge to `.claude/commands/delivery/_lib`.

This package re-exports the canonical `DeliveryLock` class from the CLI-side
lock module (`.claude/commands/delivery/_lib/lock.py`). There is no
duplication of logic: `lock_bridge.py` loads the upstream module dynamically
via `importlib.util`, following the repo-root detection precedent in
`workflow_app/sdk/process_runner.py:57-67`.

Consumers (per PROGRESS.md / TASKS-INDEX.md):
  - T-035 Reader delivery.json (pydantic v2)
  - T-036 Kanban por estados DCP
  - T-037 Lock-aware (read-only quando ocupado)
  - T-038 Visao por modulo
  - T-050 Workflow-app DCP cleanup + botoes Build/Specific-Flow
"""

from __future__ import annotations

from .lock_bridge import DeliveryLock, LockError

__all__ = ["DeliveryLock", "LockError"]

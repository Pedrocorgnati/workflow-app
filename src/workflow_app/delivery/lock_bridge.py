"""Qt-side loader for the canonical `DeliveryLock` class (TASK-005).

The cooperative lock protocol (DCP-5.2.10, DCP-9.4) is implemented once in
`.claude/commands/delivery/_lib/lock.py`. This bridge loads that module at
import time via `importlib.util` so the workflow-app and the CLI share the
**exact same class** — no re-implementation, no wrapper. Using `importlib`
(instead of `sys.path` manipulation + a regular import) keeps the upstream
package self-contained and avoids leaking `_lib` into `sys.modules` under a
name that might collide with other consumers.

Root detection mirrors `workflow_app/sdk/process_runner.py:_find_systemforge_root`:
walk up from this file looking for a directory that contains both
`.claude/commands/` and `CLAUDE.md`.

Usage (Qt long-lock with heartbeat)::

    from workflow_app.delivery import DeliveryLock, LockError

    lock = DeliveryLock(wbs_root, purpose="workflow-app.edit")
    try:
        lock.acquire(wait=5)
    except LockError as exc:
        show_dialog(str(exc))
        return

    timer = QTimer(self)
    timer.timeout.connect(self._heartbeat_safe)
    timer.start(lock.heartbeat_interval * 1000)

    def _heartbeat_safe(self):
        try:
            lock.heartbeat()
        except LockError:
            timer.stop()
            show_dialog("Lock perdido — outra instancia assumiu o delivery.json")
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType


class LockBridgeError(RuntimeError):
    """Raised when the bridge cannot locate `_lib/atomic_write.py` / `_lib/lock.py`."""


def _find_systemforge_root() -> pathlib.Path:
    """Walk up from this file to find the SystemForge repo root.

    Mirrors `workflow_app/sdk/process_runner.py:_find_systemforge_root`:
    look for a directory that has both `.claude/commands/` and `CLAUDE.md`.
    """
    candidate = pathlib.Path(__file__).resolve().parent
    while candidate != candidate.parent:
        if (
            (candidate / ".claude" / "commands").is_dir()
            and (candidate / "CLAUDE.md").is_file()
        ):
            return candidate
        candidate = candidate.parent
    raise LockBridgeError(
        "SystemForge root nao encontrado a partir de "
        f"{pathlib.Path(__file__).resolve()}. "
        "lock_bridge.py exige que .claude/commands/ e CLAUDE.md existam no repo."
    )


def _load_module(name: str, path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LockBridgeError(f"Falha ao carregar spec de {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_delivery_lock() -> tuple[type, type]:
    """Load and return `(DeliveryLock, LockError)` from the CLI _lib package.

    `lock.py` imports `from .atomic_write import atomic_write_json`, so we
    must load `atomic_write.py` first under the same synthetic package so
    the relative import resolves.
    """
    root = _find_systemforge_root()
    lib_dir = root / ".claude" / "commands" / "delivery" / "_lib"
    lock_path = lib_dir / "lock.py"
    atomic_path = lib_dir / "atomic_write.py"

    if not lock_path.is_file():
        raise LockBridgeError(f"lock.py nao encontrado em {lock_path}")
    if not atomic_path.is_file():
        raise LockBridgeError(f"atomic_write.py nao encontrado em {atomic_path}")

    pkg_name = "_delivery_lib_bridge"
    if pkg_name not in sys.modules:
        pkg_spec = importlib.util.spec_from_loader(pkg_name, loader=None)
        if pkg_spec is None:
            raise LockBridgeError("Falha ao criar spec do pacote sintetico")
        pkg = importlib.util.module_from_spec(pkg_spec)
        pkg.__path__ = [str(lib_dir)]  # marker do pacote
        sys.modules[pkg_name] = pkg

    # Load atomic_write first so `from .atomic_write import ...` resolves.
    if f"{pkg_name}.atomic_write" not in sys.modules:
        _load_module(f"{pkg_name}.atomic_write", atomic_path)

    if f"{pkg_name}.lock" not in sys.modules:
        _load_module(f"{pkg_name}.lock", lock_path)

    lock_mod = sys.modules[f"{pkg_name}.lock"]
    return lock_mod.DeliveryLock, lock_mod.LockError


DeliveryLock, LockError = _load_delivery_lock()

__all__ = ["DeliveryLock", "LockError", "LockBridgeError"]

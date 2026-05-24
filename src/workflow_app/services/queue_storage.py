"""Atomic read/write helpers for queue_root storage.

Separates queue state from the main project.json into a dedicated file
under output/wbs/pipeline-position/{slug}.json, as decided in TASK-2.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_queue_root(path: str | os.PathLike) -> dict:
    """Read queue_root from disk.

    Returns an empty dict if the file is missing or corrupt.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_queue_root(path: str | os.PathLike, data: dict) -> None:
    """Atomically write queue_root to disk (tmp + os.replace + fsync).

    Creates parent directories on demand. On failure the temporary file
    is removed and the original path is left untouched.
    """
    p = Path(path)
    if p.is_dir():
        raise IsADirectoryError(
            f"queue_root resolveu para um diretorio, nao um arquivo: {p}. "
            "Causa provavel: campo queue_root vazio no config colapsando para "
            "project_dir. Verifique 'queue_root' em basic_flow ou rode com um "
            "config que tenha o fallback canonico aplicado."
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

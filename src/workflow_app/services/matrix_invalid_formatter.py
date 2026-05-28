"""Verbose formatter for `MATRIX_INVALID` surfaced by the in-memory matrix
load path of the DCP queue derivation (`_derive_queue_from_matrix_inmemory`).

Anti Zero Silencio (CLAUDE.md Tier 2): when `DCP-COMMAND-MATRIX.json` exists
but fails Pydantic validation (or JSON parse), the operator must see a
red popup with: schema version (attempted), offender path, latest
`.bak-{ISO_UTC}` next to the file, and the canonical migration command.

Loop 05-27-dcp-flow-structured-fix item 019 (= source TASK-018) flipped the
behavior to FAIL-CLOSED: the popup is now critical (red) and the DCP Execute
path aborts without falling back to `SPECIFIC-FLOW.json`. The previous
MATRIX_WARNING (yellow) variant from item 018 (= source TASK-017) was
replaced in-place.

This module is pure (no Qt imports) so it can be unit tested without an
event loop. Mirror sibling: `delivery_invalid_formatter.py`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_MIGRATION_CMD = (
    "python3 ai-forge/scripts/migrate-matrix-to-v1-0-1.py "
    "<DCP-COMMAND-MATRIX.json>"
)

_FIX_FOOTER = (
    "Fix sugerido: rode o comando de migracao acima OU regenere via "
    "`[DCP: Build Module Pipeline]`. O loader grava `.bak-{ISO_UTC}` "
    "antes de qualquer reescrita."
)

_BAK_RE = re.compile(r"\.bak-\d{8}T\d{6}Z$")


def discover_latest_bak(matrix_path: Any) -> str | None:
    """Locate the most recent `.bak-{ISO_UTC}` next to `matrix_path`.

    Returns the absolute path string of the latest backup (by filename
    timestamp, which sorts chronologically) or None when no `.bak-*` exists
    in the same directory. Filesystem errors degrade to None.
    """
    try:
        p = Path(str(matrix_path))
        parent = p.parent
        if not parent.exists() or not parent.is_dir():
            return None
        prefix = p.name + ".bak-"
        candidates: list[str] = []
        for entry in os.listdir(parent):
            if entry.startswith(prefix) and _BAK_RE.search(entry):
                candidates.append(entry)
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return str(parent / candidates[0])
    except OSError:
        return None


def extract_schema_version(matrix_path: Any) -> str | None:
    """Best-effort read of `schema_version` from raw JSON before Pydantic.

    Returns the literal value when readable, None otherwise. Used to label
    the popup even when the rest of the document fails validation.
    """
    try:
        raw = Path(str(matrix_path)).read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            v = data.get("schema_version")
            if isinstance(v, str) and v:
                return v
    except (OSError, json.JSONDecodeError):
        return None
    return None


def format_matrix_invalid_popup(
    matrix_path: Any,
    exc_class: str,
    exc_msg: str,
    schema_version_attempted: str | None = None,
    latest_bak: str | None = None,
) -> tuple[str, str]:
    """Format the red MATRIX_INVALID popup body for an invalid matrix.

    Returns (display_text, clipboard_text):

    - display_text: pt-BR body to render in `QMessageBox.Icon.Critical`.
      Shows version (when readable), offender path, latest `.bak-{ISO_UTC}`
      sibling (when present), and the canonical migration command.
    - clipboard_text: same content prefixed with a canonical header,
      suitable for pasting into a bug report. Keeps raw exception class +
      message so the operator can correlate logs.

    The function never raises and never assumes Pydantic was the failure
    class — `exc_class`/`exc_msg` are reported verbatim so JSON parse
    errors and ValidationError converge on the same popup shape.
    """
    path_str = str(matrix_path)
    version_label = schema_version_attempted or "(indisponivel)"
    bak_label = latest_bak or "(nenhum .bak-{ISO_UTC} encontrado nesta pasta)"

    body_lines = [
        "DCP-COMMAND-MATRIX.json invalido. DCP Execute ABORTADO (sem fallback).",
        "",
        f"Versao tentada:   {version_label}",
        f"Offender:         {path_str}",
        f"Backup mais recente: {bak_label}",
        "",
        "Falha:",
        f"  {exc_class}: {exc_msg}",
        "",
        "Comando de migracao:",
        f"  {_MIGRATION_CMD}",
        "",
        _FIX_FOOTER,
    ]
    clipboard_lines = [
        "Copiar erros - DCP-COMMAND-MATRIX.json invalido (MATRIX_INVALID)",
        f"Path: {path_str}",
        f"schema_version (tentado): {version_label}",
        f"latest .bak: {bak_label}",
        f"exc_class: {exc_class}",
        f"exc_msg: {exc_msg}",
        "",
        f"Migration: {_MIGRATION_CMD}",
        "",
        _FIX_FOOTER,
    ]
    return "\n".join(body_lines), "\n".join(clipboard_lines)


__all__ = [
    "format_matrix_invalid_popup",
    "discover_latest_bak",
    "extract_schema_version",
]

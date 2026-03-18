"""
SHA-256 hasher for CLAUDE.md versioning (module-05/TASK-4).

Provides deterministic hashing of CLAUDE.md to detect when factory
templates need to be refreshed.
"""

from __future__ import annotations

import hashlib
import os


def compute_hash(claude_md_path: str | None) -> str | None:
    """Compute SHA-256 hash of a CLAUDE.md file.

    Args:
        claude_md_path: absolute or relative path to CLAUDE.md

    Returns:
        64-char hex string (e.g. "a3f2b1...") or None if file
        not found or unreadable.

    Notes:
        - Reads in binary mode for deterministic hashing across OS
        - Normalizes line endings (CRLF → LF) to avoid Windows/Linux divergence
    """
    if not claude_md_path or not os.path.isfile(claude_md_path):
        return None

    try:
        sha256 = hashlib.sha256()
        with open(claude_md_path, "rb") as f:
            content = f.read().replace(b"\r\n", b"\n")
            sha256.update(content)
        return sha256.hexdigest()
    except OSError:
        return None


def find_claude_md(start_dir: str | None = None) -> str | None:
    """Search for CLAUDE.md by walking up the directory tree.

    Looks up to 6 levels above start_dir. Returns first match or None.

    Args:
        start_dir: starting directory (default: directory of this file)
    """
    if start_dir is None:
        start_dir = os.path.dirname(os.path.abspath(__file__))

    current = os.path.abspath(start_dir)
    for _ in range(6):
        candidate = os.path.join(current, "CLAUDE.md")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return None

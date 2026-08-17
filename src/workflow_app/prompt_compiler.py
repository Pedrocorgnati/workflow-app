"""Prompt compiler - transforms slash commands into executable prompt text.

Pure Python module (no Qt dependencies). Resolves command names to
``.claude/commands/**/*.md`` file paths, reads the markdown, strips YAML
frontmatter, and returns the body as executable prompt text plus metadata.

Supports two command shapes (D-32):

- **Top-level**: ``/adr-create`` -> ``.claude/commands/adr-create.md``
- **Namespaced**: ``/android:accessibility`` -> ``.claude/commands/android/accessibility.md``

The colon ``:`` in a command name maps to a directory separator on disk.

Security: resolved paths are validated against the repo root to prevent
path traversal (e.g. ``/foo:../../etc/passwd`` must be refused).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Regex for YAML frontmatter: ---\n...\n--- at the start of the file.
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)

# Commands directory relative to repo root.
_COMMANDS_DIR = ".claude/commands"


@dataclass(frozen=True)
class CompiledPrompt:
    """Result of compiling a slash command into executable prompt text.

    Attributes:
        prompt_text: The executable prompt body (frontmatter stripped,
            arguments appended when provided).
        command_path: Resolved absolute path to the ``.md`` file.
        content_hash: SHA-256 hex digest of the raw file content (before
            frontmatter stripping). Useful for cache invalidation.
        metadata: Frontmatter fields as a dict, empty when no frontmatter
            or when the file has no valid YAML block.
        command_name: Normalised command name (always starts with ``/``).
        arguments: The arguments string passed to :meth:`PromptCompiler.compile`.
    """

    prompt_text: str
    command_path: str
    content_hash: str
    metadata: dict = field(default_factory=dict)
    command_name: str = ""
    arguments: str = ""


class CommandNotFoundError(FileNotFoundError):
    """Raised when a command name cannot be resolved to an existing file."""


class PathTraversalError(ValueError):
    """Raised when the resolved path escapes the repo root."""


class PromptCompiler:
    """Compile slash commands into executable prompt text.

    Parameters:
        repo_root: Absolute or relative path to the repository root.
            Must contain the ``.claude/commands/`` directory.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._commands_root = self._repo_root / _COMMANDS_DIR

    @property
    def repo_root(self) -> Path:
        """Return the resolved repository root."""
        return self._repo_root

    @property
    def commands_root(self) -> Path:
        """Return the resolved commands directory."""
        return self._commands_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_command_path(self, command_name: str) -> Path:
        """Resolve a command name to its ``.md`` file path.

        Conversion rules:

        1. Strip leading ``/``.
        2. Replace ``:`` with ``/`` (namespace separator).
        3. Append ``.md``.
        4. Join under ``.claude/commands/``.
        5. Validate the result is inside the repo root.

        Parameters:
            command_name: Slash command name, e.g. ``/adr-create`` or
                ``/android:accessibility``.

        Returns:
            Resolved :class:`~pathlib.Path` to the command file.

        Raises:
            CommandNotFoundError: If the file does not exist.
            PathTraversalError: If the resolved path escapes the repo root.
        """
        # Step 1: strip leading /
        raw = command_name.lstrip("/")

        # Step 2: colon -> directory separator
        parts = raw.split(":")
        relative = "/".join(parts)

        # Step 3: append .md
        if not relative.endswith(".md"):
            relative += ".md"

        # Step 4: join under commands root
        resolved = (self._commands_root / relative).resolve()

        # Step 5: security check - must be inside repo root
        if not self._is_inside(resolved, self._repo_root):
            raise PathTraversalError(
                f"Resolved path escapes repo root: "
                f"{resolved} is not inside {self._repo_root}"
            )

        if not resolved.is_file():
            raise CommandNotFoundError(
                f"Command file not found: {resolved} "
                f"(resolved from '{command_name}')"
            )

        return resolved

    def compile(
        self,
        command_name: str,
        arguments: str = "",
    ) -> CompiledPrompt:
        """Compile a command into an executable prompt.

        Parameters:
            command_name: Slash command (e.g. ``/adr-create``,
                ``/loop:iteraction:execute-task``).
            arguments: Optional arguments to append after the prompt body.
                Passed literally (no variable substitution).

        Returns:
            A :class:`CompiledPrompt` with the prompt text, metadata,
            content hash and resolved path.

        Raises:
            CommandNotFoundError: If the command file does not exist.
            PathTraversalError: If the resolved path escapes the repo root.
        """
        resolved = self.resolve_command_path(command_name)
        raw_content = resolved.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        # Strip frontmatter
        body = _strip_frontmatter(raw_content)

        # Parse frontmatter metadata (lightweight - no yaml dependency)
        metadata = _parse_frontmatter_raw(raw_content)

        # Build final prompt text
        prompt_text = body.rstrip("\n")
        if arguments.strip():
            prompt_text = f"{prompt_text}\n\n{arguments}"

        return CompiledPrompt(
            prompt_text=prompt_text,
            command_path=str(resolved),
            content_hash=content_hash,
            metadata=metadata,
            command_name=_normalise_name(command_name),
            arguments=arguments,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_inside(child: Path, parent: Path) -> bool:
        """Return True if *child* is strictly inside *parent*."""
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from *content*, return the body.

    If no frontmatter is found, return *content* unchanged.
    """
    match = _FRONTMATTER_RE.match(content)
    if match:
        return content[match.end():]
    return content


def _parse_frontmatter_raw(content: str) -> dict:
    """Extract frontmatter key-value pairs with a lightweight parser.

    This intentionally avoids a full YAML dependency. It handles the
    common cases: ``key: value`` and ``key: "value"`` on single lines.
    Multi-line YAML values (lists, nested maps) are returned as raw
    strings.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    block = content[match.start():match.end()]
    # Remove the opening and closing ---
    lines = block.split("\n")
    # First line is ---, last non-empty is ---
    yaml_lines = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        yaml_lines.append(line)

    result: dict = {}
    for line in yaml_lines:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Coerce booleans and null
        if value.lower() == "true":
            value = True  # noqa: F841
        elif value.lower() == "false":
            value = False  # noqa: F841
        elif value.lower() == "null" or value == "":
            value = None  # noqa: F841
        result[key] = value

    return result


def _normalise_name(command_name: str) -> str:
    """Ensure the command name starts with exactly one ``/``."""
    return "/" + command_name.lstrip("/")

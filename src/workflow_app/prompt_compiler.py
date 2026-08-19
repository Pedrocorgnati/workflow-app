"""Prompt compiler - compiles slash commands into a hybrid prompt envelope.

Pure Python module (no Qt dependencies). Resolves command names to
``.claude/commands/**/*.md`` file paths, reads the markdown and emits a
**hybrid prompt by verified reference** (decision D-36), not a full-body
injection.

The compiled ``prompt_text`` carries, as readable text:

1. the command name, the resolved ``command_path`` and the ``content_hash``
   of the raw file (the same values exposed as dataclass fields);
2. the literal arguments (no variable substitution);
3. an explicit reading protocol telling the target runtime to open the file
   and verify the hash **before** executing, and to stop and report when the
   hashes diverge instead of silently running a different version;
4. the complete frontmatter block;
5. only the *essential slices* of the body - see :func:`_essential_slices`
   for the criterion and the effective regexes.

Everything else stays on disk and is read lazily by the target runtime.
The premise verified by D-36 is that every target (Grok, Qwen, Kimi, Codex)
is a local CLI with filesystem access.

Revoked contract: until item 007 of loop ``08-17-systemforge-multillm-gaps-refactor``
this module returned the whole body (frontmatter stripped) with the arguments
appended, and neither ``command_path`` nor ``content_hash`` reached the prompt
text. That behaviour is gone; the tests that asserted it were rewritten, not
deleted.

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

# Markdown heading of level 2..6, outside fenced code blocks.
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)$")

# Fenced code block delimiter (``` or more backticks).
_FENCE_RE = re.compile(r"^\s*```")

# Essential-slice criterion (D-36). See _essential_slices for the rationale.
_ESSENTIAL_ARGUMENTS_RE = re.compile(
    r"(argumento|configuracao alternativa|resolucao de (escopo|argumento|configuracao))",
    re.IGNORECASE,
)
_ESSENTIAL_PREFLIGHT_RE = re.compile(
    r"(fase 0|fase pre-0|pre-flight|pre-requisito)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompiledPrompt:
    """Result of compiling a slash command into executable prompt text.

    Attributes:
        prompt_text: The hybrid envelope (D-36): header with command name,
            ``command_path`` and ``content_hash`` as text, literal arguments,
            reading protocol, complete frontmatter and the essential slices of
            the body. It is **not** the full body any more.
        command_path: Resolved absolute path to the ``.md`` file. Also travels
            inside ``prompt_text``.
        content_hash: SHA-256 hex digest of the raw file content (before
            frontmatter stripping). Useful for cache invalidation, and also
            travels inside ``prompt_text`` as the input of the hash check the
            target runtime performs before executing (D-36).
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
        """Compile a command into a hybrid prompt envelope (D-36).

        The returned ``prompt_text`` is **not** the whole command body. It is
        an envelope carrying the command name, the resolved path, the content
        hash, the literal arguments, the reading protocol, the complete
        frontmatter and only the essential slices of the body
        (see :func:`_essential_slices`). The target runtime opens the file and
        verifies the hash before executing.

        Parameters:
            command_name: Slash command (e.g. ``/adr-create``,
                ``/loop:iteraction:execute-task``).
            arguments: Optional arguments carried in the envelope.
                Passed literally (no variable substitution).

        Returns:
            A :class:`CompiledPrompt` with the envelope text, metadata,
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

        # Build the hybrid envelope (D-36) instead of injecting the whole body.
        prompt_text = _build_envelope(
            command_name=_normalise_name(command_name),
            command_path=str(resolved),
            content_hash=content_hash,
            arguments=arguments,
            frontmatter_block=_extract_frontmatter_block(raw_content),
            slices=_essential_slices(body),
        )

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


# Reading protocol injected verbatim into every envelope (D-36, ST003).
# It is the contract that makes the hybrid compilation safe: the target opens
# the file, re-hashes it and refuses to run a version that drifted from the
# one that was compiled.
_READING_PROTOCOL = """\
PROTOCOLO DE LEITURA (obrigatorio - leia antes de executar qualquer passo)

1. Este envelope NAO contem o comando inteiro. Ele traz apenas o frontmatter
   completo, os argumentos literais e os trechos essenciais recortados mais
   abaixo. O restante do comando permanece no arquivo indicado em "Arquivo".
2. Abra o arquivo indicado em "Arquivo" e leia-o integralmente antes de
   executar.
3. Recalcule o SHA-256 do conteudo lido e compare com o valor do campo
   "SHA-256" deste envelope.
4. Se os hashes divergirem, PARE. Nao execute a versao nova em silencio:
   reporte que o arquivo mudou entre a compilacao e a execucao, nomeando os
   dois hashes (o do envelope e o recalculado agora). Divergencia de hash e
   erro observavel, nunca silencio.
5. Se os hashes baterem, execute o corpo do arquivo usando os argumentos
   literais declarados neste envelope."""


def _extract_frontmatter_block(content: str) -> str:
    """Return the raw YAML frontmatter block, delimiters included.

    Returns an empty string when *content* has no frontmatter. Unlike
    :func:`_parse_frontmatter_raw` this preserves the block byte-for-byte,
    because D-36 requires the **complete** frontmatter inside the envelope
    (the lightweight parser flattens lists and nested maps).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return ""
    return content[match.start():match.end()].rstrip("\n")


def _essential_slices(body: str) -> list[tuple[str, str]]:
    """Return the essential sections of *body*, in order of appearance.

    **Criterion (D-36, item 007 of loop 08-17).** The hybrid envelope injects
    integrally only what the target cannot act without before it has read the
    file. Three families qualify:

    1. **Complete frontmatter** - always, no filter. Handled outside this
       function by :func:`_extract_frontmatter_block`, because the frontmatter
       is not part of the body.
    2. **Arguments section** - any level 2..6 heading matching
       ``(argumento|configuracao alternativa|resolucao de
       (escopo|argumento|configuracao))``, case-insensitive
       (:data:`_ESSENTIAL_ARGUMENTS_RE`).
    3. **FASE 0 / pre-flight** - any level 2..6 heading matching
       ``(fase 0|fase pre-0|pre-flight|pre-requisito)``, case-insensitive
       (:data:`_ESSENTIAL_PREFLIGHT_RE`).

    The effective regexes are part of the criterion, not an implementation
    detail: a narrower regex measurably changes the coverage. Measured over
    the 658 files in ``.claude/commands/**/*.md`` on 2026-08-18, the regexes
    above match an arguments section in 440 files and a FASE 0 / pre-flight
    section in 314; dropping ``configuracao alternativa`` and ``resolucao de
    *`` drops those to 349 and 276.

    A section spans from its heading to the next heading of the same or
    shallower level, or to the end of the body. Headings inside fenced code
    blocks (```` ``` ````) are ignored, so a markdown example inside a command
    never becomes a section, and never terminates one. Nested essential
    headings are not emitted twice: a heading already contained in an emitted
    slice is skipped.

    **DA-01 - nothing matches.** Then nothing is injected and the caller emits
    an envelope with no body at all. This is the common case (218 of the 658
    files have no arguments section under any of the regexes above) and it is
    deliberate: under D-36 the target has filesystem access, so path, hash,
    frontmatter, arguments and the reading protocol are sufficient.

    **DA-02 - ``## FASE FINAL`` is not essential.** 612 of the 658 commands
    carry that block, and it is the handshake that unblocks the workflow-app
    queue, but ``ai-forge/MCP/agents/executor-de-slash-commands-rules.md``
    (Passo 3, item 5) forbids a non-Claude executor from running the target's
    block and requires the executor itself to emit the final notify exactly
    once. Injecting it here would push the target into precisely the false
    positive that rule exists to prevent. The reading protocol covers the
    case: the target opens the file and sees the block there.

    Returns:
        List of ``(heading_line, section_text)`` tuples, in order of
        appearance. Empty when no section matches. Pure function, no I/O.
    """
    lines = body.split("\n")
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), line))

    slices: list[tuple[str, str]] = []
    covered_until = -1
    for position, (index, level, heading_line) in enumerate(headings):
        if index <= covered_until:
            # Already inside a slice emitted by an outer essential heading.
            continue
        if not _is_essential_heading(heading_line):
            continue
        end = len(lines)
        for next_index, next_level, _ in headings[position + 1:]:
            if next_level <= level:
                end = next_index
                break
        section = "\n".join(lines[index:end]).rstrip("\n")
        if section.strip():
            slices.append((heading_line.strip(), section))
            covered_until = end - 1
    return slices


def _is_essential_heading(heading_line: str) -> bool:
    """Return True when *heading_line* matches the essential-slice criterion.

    Criterion and effective regexes are documented in :func:`_essential_slices`.
    """
    match = _HEADING_RE.match(heading_line)
    text = match.group(2) if match else heading_line
    return bool(
        _ESSENTIAL_ARGUMENTS_RE.search(text)
        or _ESSENTIAL_PREFLIGHT_RE.search(text)
    )


def _build_envelope(
    command_name: str,
    command_path: str,
    content_hash: str,
    arguments: str,
    frontmatter_block: str,
    slices: list[tuple[str, str]],
) -> str:
    """Assemble the hybrid envelope text (D-36).

    Order is fixed: header (name, path, hash, arguments), reading protocol,
    complete frontmatter, essential slices. ``command_path`` and
    ``content_hash`` appear as plain substrings, which is what the target
    needs in order to run the hash check described in the protocol.
    """
    parts: list[str] = []

    header = [
        "=== COMANDO COMPILADO - envelope hibrido por referencia verificada (D-36) ===",
        f"Comando: {command_name}",
        f"Arquivo: {command_path}",
        f"SHA-256: {content_hash}",
        f"Argumentos: {arguments.strip() if arguments.strip() else '(nenhum)'}",
    ]
    parts.append("\n".join(header))
    parts.append(_READING_PROTOCOL)

    if frontmatter_block:
        parts.append(
            "--- FRONTMATTER (integral) ---\n" + frontmatter_block
        )
    else:
        parts.append("--- FRONTMATTER (integral) ---\n(o arquivo nao tem frontmatter)")

    if slices:
        names = ", ".join(heading for heading, _ in slices)
        body_parts = [
            f"--- TRECHOS ESSENCIAIS ({len(slices)} secao(oes): {names}) ---"
        ]
        body_parts.extend(section for _, section in slices)
        parts.append("\n\n".join(body_parts))
    else:
        parts.append(
            "--- TRECHOS ESSENCIAIS (nenhum) ---\n"
            "Nenhuma secao essencial foi reconhecida neste comando. Leia o "
            "arquivo indicado em \"Arquivo\" por inteiro, conforme o protocolo "
            "acima."
        )

    return "\n\n".join(parts).rstrip("\n")


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

"""Validation of SPECIFIC-FLOW.json command entries against the filesystem.

Loop 06-09 (phantom "task N nao existe"): `_enqueue_specific_flow` historically
re-enqueued whatever `commands[]` the JSON carried, verbatim. Flow files
generated before the 06-08 fix (per-task expansion synthesized from a stale
`loop_multiplier` instead of enumerating real `TASK-*.md` files) keep phantom
entries like `/execute-task .../TASK-4.md` forever, and the generator's
pre-decomposition stub can leak a literal `TASK-{k}` placeholder. Neither was
caught before dispatch — the error only fired at slash-command runtime.

This module is the pure (Qt-free) validation pass the widget runs at load time:

- **Placeholder guard** — an unresolved `{token}` in the command name means the
  producer never rendered the entry (generator stub / renderer drift). The
  command would be unrunnable; drop it.
- **Task existence guard** — every `TASK-<int|decimal>.md` path referenced by
  the command name must exist on disk. Resolution candidates per reference:
  absolute path as-is; relative path joined to `project_dir` (mirrors
  `_resolve_wbs_root`); basename inside `flow_path.parent` when the flow file
  sits at its canonical per-module location (`.../modules/{cm_id}/`).
  Unverifiable references (relative path with no resolution context) are kept
  — fail-open — to avoid false drops; verifiably-missing ones are dropped.

Dropped entries are returned to the caller, which MUST surface them to the
operator (Zero Silencio) — the queue silently shrinking would be as opaque as
the phantom errors this replaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Same shape as the canonical executable-task pattern (templating.py /
# task_enum.py), embedded in a longer rendered command line. `[^\s,;]*` keeps
# the path prefix attached to the basename without swallowing separators.
_TASK_REF_RE = re.compile(r"(?P<ref>[^\s,;]*TASK-\d+(?:\.\d+)?\.md)\b")

# Unresolved canonical placeholder, e.g. `{task}`, `{k}`, `{module_path}`.
# Conservative: single brace-delimited identifier — rendered slash commands
# never legitimately carry one (see queue_derivation._render drift guard).
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

# Placeholder colado a um ref de TASK (`TASK-{k}`, `TASK-{k}.md`): a assinatura
# exata do stub pre-decomposicao de generator._list_tasks. Usado pelo modo
# `task-only`: filas arbitrarias restauradas de snapshot carregam comandos de
# texto-livre legitimos com `{ident}` (ex.: prompt /mcp:codex com
# `output/wbs/{slug}/...`, observado em pipeline-position reais) que o LLM
# receptor resolve contextualmente — drop la seria falso positivo.
_TASK_PLACEHOLDER_RE = re.compile(r"TASK-\{[A-Za-z_][A-Za-z0-9_]*\}")


@dataclass(frozen=True)
class DroppedCommand:
    """One commands[] entry rejected at load time, with the operator-facing reason."""

    name: str
    reason: str


@dataclass(frozen=True)
class FlowValidationResult:
    """Outcome of `validate_flow_commands` — valid entries + visible drops."""

    valid: list = field(default_factory=list)
    dropped: list = field(default_factory=list)


def _task_ref_candidates(
    ref: str,
    *,
    cm_id: str,
    project_dir: Optional[Path],
    flow_path: Optional[Path],
) -> list[Path]:
    """Filesystem candidates where `ref` may legitimately live.

    Empty list means the reference is unverifiable in this context (the caller
    must keep the entry — fail-open).
    """
    p = Path(ref)
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    elif project_dir is not None:
        candidates.append(Path(project_dir) / p)
    # Canonical per-module flow location: the flow file lives next to the
    # TASK specs it references, so the basename must exist alongside it.
    if flow_path is not None and Path(flow_path).parent.name == cm_id:
        candidates.append(Path(flow_path).parent / p.name)
    return candidates


def validate_flow_commands(
    commands: list,
    *,
    cm_id: str,
    project_dir: Optional[Path] = None,
    flow_path: Optional[Path] = None,
    placeholder_mode: str = "strict",
) -> FlowValidationResult:
    """Split `commands[]` into loadable entries and visible drops.

    Entries that are not dicts or carry no usable `name` pass through unchanged
    (the widget already skips them downstream); this pass only rejects entries
    that WOULD dispatch but are provably broken: unresolved placeholder in the
    name, or a referenced TASK file that verifiably does not exist on disk.

    `placeholder_mode` calibra a guarda de placeholder ao produtor:

    - ``"strict"`` (default, load do SPECIFIC-FLOW.json): QUALQUER `{ident}`
      derruba — o produtor (generator/derivation) renderiza todos os
      placeholders, entao um sobrevivente e drift por definicao.
    - ``"task-only"`` (restore de snapshot de fila): so `TASK-{ident}` derruba
      (assinatura do stub do gerador). Snapshots cobrem filas arbitrarias
      (intake-review, loop, prompts MCP manuais) onde `{slug}`-style em texto
      livre e legitimo e resolvido contextualmente pelo LLM receptor.
    """
    strict_placeholders = placeholder_mode != "task-only"
    valid: list[Any] = []
    dropped: list[DroppedCommand] = []

    for cmd in commands:
        if not isinstance(cmd, dict):
            valid.append(cmd)
            continue
        name = str(cmd.get("name", "") or "").strip()
        if not name:
            valid.append(cmd)
            continue

        _guard_re = _PLACEHOLDER_RE if strict_placeholders else _TASK_PLACEHOLDER_RE
        leftover = _guard_re.search(name)
        if leftover:
            dropped.append(DroppedCommand(
                name=name,
                reason=(
                    f"placeholder nao resolvido {leftover.group(0)!r} — entrada "
                    "gerada sem render (stub pre-decomposicao ou drift do "
                    "gerador). Regenere via [DCP: Build Module Pipeline]."
                ),
            ))
            continue

        missing: list[str] = []
        for m in _TASK_REF_RE.finditer(name):
            ref = m.group("ref")
            candidates = _task_ref_candidates(
                ref, cm_id=cm_id, project_dir=project_dir, flow_path=flow_path,
            )
            if not candidates:
                continue  # unverifiable here — keep (fail-open)
            if not any(c.exists() for c in candidates):
                missing.append(ref)
        if missing:
            dropped.append(DroppedCommand(
                name=name,
                reason=(
                    "TASK inexistente no disco: " + ", ".join(missing) + ". "
                    "Flow stale (gerado por contagem, pre-fix 06-08) ou tasks "
                    "removidas. Regenere via [DCP: Build Module Pipeline] e/ou "
                    "rode /dcp:matrix-mark-loops."
                ),
            ))
            continue

        valid.append(cmd)

    return FlowValidationResult(valid=valid, dropped=dropped)


__all__ = [
    "DroppedCommand",
    "FlowValidationResult",
    "validate_flow_commands",
]

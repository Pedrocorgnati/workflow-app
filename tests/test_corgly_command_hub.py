"""Integration contract for the SystemForge-owned Corgly command catalog."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget


SYSTEMFORGE_ROOT = Path(__file__).resolve().parents[3]
COMMAND_ROOT = SYSTEMFORGE_ROOT / ".claude" / "commands" / "corgly"
LEGACY_ROOT = SYSTEMFORGE_ROOT / "corgly-classes" / ".claude" / "commands"
RESOLVER = COMMAND_ROOT / "_shared" / "resolve_corgly_context.py"
KIMI_MATRIX = SYSTEMFORGE_ROOT / "blacksmith" / "claude-to-kimi" / "corgly-command-matrix.md"

COMMANDS: tuple[tuple[str, str], ...] = (
    ("class-create.md", "/corgly:class-create"),
    ("class-generate.md", "/corgly:class-generate"),
    ("class-review.md", "/corgly:class-review"),
    ("class-update.md", "/corgly:class-update"),
    ("cmd/autocast-put.md", "/corgly:cmd:autocast-put"),
    ("dual-update.md", "/corgly:dual-update"),
    ("funny-rebase.md", "/corgly:funny-rebase"),
    ("grammar-adjust.md", "/corgly:grammar-adjust"),
    ("mcp/codex.md", "/corgly:mcp:codex"),
    ("mcp/grok.md", "/corgly:mcp:grok"),
    ("mcp/kimi.md", "/corgly:mcp:kimi"),
    ("questions-rebase.md", "/corgly:questions-rebase"),
    ("tools/auq-interview.md", "/corgly:tools:auq-interview"),
)

LEGACY_SLUGS = (
    "class-create",
    "class-generate",
    "class-review",
    "class-update",
    "dual-update",
    "funny-rebase",
    "grammar-adjust",
    "questions-rebase",
    "cmd:autocast-put",
    "mcp:codex",
    "mcp:grok",
    "mcp:kimi",
    "tools:auq-interview",
)


def _command_markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if "_shared" not in path.relative_to(root).parts
    )


def test_catalog_has_exactly_the_thirteen_canonical_commands() -> None:
    expected = [COMMAND_ROOT / rel for rel, _slash in COMMANDS]
    assert _command_markdown_files(COMMAND_ROOT) == sorted(expected)
    assert all(path.is_file() and path.stat().st_size > 0 for path in expected)


def test_legacy_command_tree_has_no_markdown_source_of_truth() -> None:
    assert not list(LEGACY_ROOT.rglob("*.md"))
    assert not (SYSTEMFORGE_ROOT / ".claude" / "command" / "corgly").exists()


def test_all_corgly_slugs_resolve_from_the_parent_repository(monkeypatch) -> None:
    monkeypatch.chdir(SYSTEMFORGE_ROOT / "corgly-classes")
    for rel, slash in COMMANDS:
        resolved = CommandQueueWidget._resolve_claude_command_file(slash[1:])
        assert resolved is not None
        assert resolved.resolve() == (COMMAND_ROOT / rel).resolve()


def test_migrated_commands_have_no_legacy_roots_or_unnamespaced_cross_refs() -> None:
    old_slash = re.compile(
        r"(?<![\w$])/(?!(?:corgly|skill):)(?:"
        + "|".join(map(re.escape, LEGACY_SLUGS))
        + r")\b(?!-progress\.md)"
    )
    violations: list[str] = []
    for command_file in _command_markdown_files(COMMAND_ROOT):
        body = command_file.read_text(encoding="utf-8")
        if "/home/pedro/Aulas" in body or "/home/pedro/corgly-classes" in body:
            violations.append(f"{command_file}: legacy absolute root")
        if old_slash.search(body):
            violations.append(f"{command_file}: unnamespaced Corgly cross-reference")
        if "${corgly_root}/corgly:" in body or ".claude/commands/corgly:" in body:
            violations.append(f"{command_file}: slash namespace leaked into a file path")
        if "## KIMI QUICKSTART" not in body:
            violations.append(f"{command_file}: missing KIMI QUICKSTART")
        if (
            "resolver=../.claude/commands/corgly/_shared/resolve_corgly_context.py"
            not in body
        ):
            violations.append(f"{command_file}: missing corgly-root resolver fallback")
    assert not violations, "\n".join(violations)


def test_context_resolver_reports_parent_and_corgly_roots() -> None:
    proc = subprocess.run(
        [sys.executable, str(RESOLVER), "--json"],
        cwd=SYSTEMFORGE_ROOT / "corgly-classes",
        check=True,
        capture_output=True,
        text=True,
    )
    assert f'"systemforge_root": "{SYSTEMFORGE_ROOT}"' in proc.stdout
    assert f'"corgly_root": "{SYSTEMFORGE_ROOT / "corgly-classes"}"' in proc.stdout


def test_quickstart_locator_works_from_parent_and_corgly_roots() -> None:
    shell = """
if [ -f .claude/commands/corgly/_shared/resolve_corgly_context.py ]; then
  resolver=.claude/commands/corgly/_shared/resolve_corgly_context.py
elif [ -f ../.claude/commands/corgly/_shared/resolve_corgly_context.py ]; then
  resolver=../.claude/commands/corgly/_shared/resolve_corgly_context.py
else
  exit 3
fi
eval "$(python3 "$resolver" --sh)"
printf '%s\\n%s\\n' "$systemforge_root" "$corgly_root"
"""
    expected = f"{SYSTEMFORGE_ROOT}\n{SYSTEMFORGE_ROOT / 'corgly-classes'}\n"
    for cwd in (SYSTEMFORGE_ROOT, SYSTEMFORGE_ROOT / "corgly-classes"):
        proc = subprocess.run(
            ["bash", "-c", shell],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        assert proc.stdout == expected


def test_all_slugs_render_for_kimi_and_codex() -> None:
    for _rel, slash in COMMANDS:
        kimi = CommandQueueWidget.render_for_llm(slash, "kimi", mode="insert")
        qwen = CommandQueueWidget.render_for_llm(slash, "qwen", mode="insert")
        codex = CommandQueueWidget.render_for_llm(slash, "codex", mode="insert")
        assert kimi.text == f"/skill:slash-executor {slash}"
        assert kimi.abort_reason is None
        assert qwen.text == f"/slash-executor {slash}"
        assert qwen.abort_reason is None
        assert codex.text is not None and f"Command: {slash}" in codex.text
        assert codex.abort_reason is None


def test_autocast_scope_is_parent_owned_corgly_only() -> None:
    body = (COMMAND_ROOT / "cmd" / "autocast-put.md").read_text(encoding="utf-8")
    assert "$command_root/**" in body
    assert "$systemforge_root/ai-forge/templates/" in body
    assert "Nunca aplicar mudancas em comandos fora de `$command_root/**`" in body


def test_mcp_configs_have_all_providers_without_old_root() -> None:
    for path in (
        SYSTEMFORGE_ROOT / ".claude" / ".mcp.json",
        SYSTEMFORGE_ROOT / "corgly-classes" / ".mcp.json",
    ):
        raw = path.read_text(encoding="utf-8")
        config = json.loads(raw)
        assert {"kimi", "codex", "grok"} <= set(config["mcpServers"])
        assert "/home/pedro/Aulas" not in raw


def test_each_command_declares_single_executor_finalization_contract() -> None:
    for command_file in _command_markdown_files(COMMAND_ROOT):
        body = command_file.read_text(encoding="utf-8")
        assert body.count("## KIMI QUICKSTART") == 1
        assert "Finalize uma unica vez" in body


def test_executor_render_has_one_final_notify_owner_per_provider() -> None:
    slash = "/corgly:class-review"
    kimi = CommandQueueWidget.render_for_llm(slash, "kimi", mode="insert")
    codex = CommandQueueWidget.render_for_llm(
        slash,
        "codex",
        listener_channel="workspace_xterm",
        mode="insert",
    )
    assert kimi.text == f"/skill:slash-executor {slash}"
    assert codex.text is not None
    assert codex.text.count("emit exactly one semantic final notify") == 1
    assert "DO NOT execute that literal target block" in codex.text


def test_kimi_matrix_has_exactly_thirteen_complete_command_rows() -> None:
    rows = [
        line
        for line in KIMI_MATRIX.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\| \d+ \| `/corgly:", line)
    ]
    assert len(rows) == 13
    assert {f"`{slash}`" for _rel, slash in COMMANDS} == {
        row.split("|")[2].strip() for row in rows
    }
    for row in rows:
        columns = [column.strip() for column in row.strip("|").split("|")]
        assert len(columns) == 7
        assert columns[2] in {"safe", "parcial", "conflito"}
        assert columns[5].isdigit()
        assert columns[3] and columns[4] and columns[6]

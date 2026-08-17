"""Bidirectional parity tests for Kimi wrappers (C-52, R-51, R-52).

Axis 1 (command -> wrapper): every invocable command in .claude/commands/**/*.md
has a wrapper in .agents/skills/*.md OR is in the denylist with justification.

Axis 2 (wrapper -> command): every wrapper in .agents/skills/*.md points to an
existing command in .claude/commands/**/*.md OR is in the allowlist of universal
executors / internal helpers.
"""

from __future__ import annotations

import json
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
DENYLIST_PATH = REPO_ROOT / "ai-forge" / "scripts" / "_kimi_wrapper_denylist.json"
GENERATOR_PATH = REPO_ROOT / "ai-forge" / "scripts" / "gen-kimi-wrappers.py"

_EXCLUDED_DIR_PARTS = frozenset({"_lib", "_scripts", "__pycache__", "_shared"})
_EXCLUDED_FILENAMES = frozenset({"README.md"})


def _load_generator_module():
    spec = importlib.util.spec_from_file_location(
        "gen_kimi_wrappers", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discover_invocable_commands() -> set[str]:
    """Discover invocable command names from .claude/commands/**/*.md."""
    commands = set()
    for p in COMMANDS_DIR.rglob("*.md"):
        rel = p.relative_to(COMMANDS_DIR)
        parts = rel.parts
        if any(part in _EXCLUDED_DIR_PARTS for part in parts[:-1]):
            continue
        if rel.name in _EXCLUDED_FILENAMES:
            continue
        if "__pycache__" in parts:
            continue
        cmd_name = str(rel.with_suffix("")).replace("/", ":")
        commands.add(cmd_name)
    return commands


def _discover_wrappers() -> set[str]:
    """Discover wrapper names from .agents/skills/*.md."""
    wrappers = set()
    for p in SKILLS_DIR.glob("*.md"):
        wrappers.add(p.stem)
    return wrappers


def _wrapper_command_path(wrapper_name: str) -> str | None:
    content = (SKILLS_DIR / f"{wrapper_name}.md").read_text(encoding="utf-8")
    match = re.search(
        r"<COMMAND_FILE_PATH>\s*([^\n<]+?)\s*</COMMAND_FILE_PATH>",
        content,
    )
    return match.group(1).strip() if match else None


def _load_denylist() -> dict:
    """Load the denylist JSON."""
    if not DENYLIST_PATH.exists():
        pytest.skip("Denylist file not found")
    with open(DENYLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestCommandToWrapperParity:
    """Axis 1: every invocable command has wrapper OR is in denylist."""

    def test_command_to_wrapper_parity(self):
        commands = _discover_invocable_commands()
        wrappers = _discover_wrappers()
        denylist = _load_denylist()
        denied = {e["command"] for e in denylist.get("commands_without_wrapper", [])}

        missing = []
        for cmd in sorted(commands):
            if cmd in wrappers:
                continue
            if cmd in denied:
                continue
            missing.append(cmd)

        assert not missing, (
            f"{len(missing)} commands without wrapper and not in denylist. "
            f"Run gen-kimi-wrappers.py or add to denylist with justification. "
            f"First 10: {missing[:10]}"
        )


class TestCommandDiscovery:
    """Filesystem discovery and tier inference required by ST002."""

    def test_discover_commands_excludes_lib(self, tmp_path, monkeypatch):
        commands_dir = tmp_path / ".claude" / "commands"
        (commands_dir / "_lib").mkdir(parents=True)
        (commands_dir / "_scripts").mkdir()
        (commands_dir / "public").mkdir()
        (commands_dir / "_lib" / "helper.md").write_text("# helper\n")
        (commands_dir / "_scripts" / "build.md").write_text("# build\n")
        (commands_dir / "README.md").write_text("# README\n")
        (commands_dir / "public" / "run.md").write_text("# run\n")

        generator = _load_generator_module()
        monkeypatch.setattr(generator, "COMMANDS_DIR", commands_dir)

        assert [entry["name"] for entry in generator.discover_commands()] == [
            "public:run"
        ]

    def test_discover_commands_includes_namespaced(self, tmp_path, monkeypatch):
        commands_dir = tmp_path / ".claude" / "commands"
        (commands_dir / "qa").mkdir(parents=True)
        (commands_dir / "qa" / "trace.md").write_text("# QA trace\n")

        generator = _load_generator_module()
        monkeypatch.setattr(generator, "COMMANDS_DIR", commands_dir)

        assert generator.discover_commands()[0]["name"] == "qa:trace"

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"model": "opus", "effort": "high"}, 3),
            ({"model": "sonnet"}, 2),
            ({"effort": "medium"}, 2),
            ({"model": "opus", "effort": "low"}, 1),
            ({"effort": "high"}, 1),
            ({}, 2),
        ],
    )
    def test_discover_commands_tier_inference(self, fields, expected):
        generator = _load_generator_module()
        assert generator._infer_tier(fields) == expected

    def test_frontmatter_multiline_description_is_preserved(self):
        generator = _load_generator_module()
        fields = generator.parse_frontmatter(
            "---\ndescription: >-\n  Primeira linha\n  e segunda linha\n---\n# Body\n"
        )
        assert fields["description"] == "Primeira linha e segunda linha"


class TestWrapperRendering:
    """Generated wrappers retain the executable contract, not only filenames."""

    @pytest.mark.parametrize(
        ("reason", "argument_hint"),
        [("safe", ""), ("full", "--task path")],
    )
    def test_render_contains_canonical_contract(self, reason, argument_hint):
        generator = _load_generator_module()
        content = generator.render(
            {
                "path": "qa/trace",
                "name": "qa:trace",
                "tier": 3,
                "reason": reason,
            },
            "Trace command",
            argument_hint,
            {"verification_required": "true"},
            2000,
        )

        for required in (
            "<COMMAND_FILE_PATH>\n.claude/commands/qa/trace.md",
            "<ANTI_HALLUCINATION_CONTRACT>",
            "<FORBIDDEN>",
            "<LANGUAGE>",
            "<LISTENER_FINALIZATION_CONTRACT>",
            "[WRAPPER_ANCHOR:",
        ):
            assert required in content
        assert "{command_path}" not in content
        assert "{description}" not in content
        if reason == "full":
            assert "<ARG_HANDSHAKE>" in content
            assert "<PRE_FLIGHT>" in content


class TestWrapperToCommandParity:
    """Axis 2: every wrapper points to existing command OR is in allowlist."""

    def test_wrapper_to_command_parity(self):
        commands = _discover_invocable_commands()
        wrappers = _discover_wrappers()
        denylist = _load_denylist()
        allowlist = {e["wrapper"] for e in denylist.get("wrappers_without_command", [])}

        orphans = []
        for wname in sorted(wrappers):
            if wname in commands:
                continue
            if wname in allowlist:
                continue
            orphans.append(wname)

        assert not orphans, (
            f"{len(orphans)} wrappers without command and not in allowlist. "
            f"First 10: {orphans[:10]}"
        )

    def test_wrapper_command_file_path_matches_filename(self):
        commands = _discover_invocable_commands()
        denylist = _load_denylist()
        allowlist = {
            e["wrapper"] for e in denylist.get("wrappers_without_command", [])
        }

        mismatches = []
        for wrapper in sorted(_discover_wrappers() - allowlist):
            if wrapper not in commands:
                continue
            expected = f".claude/commands/{wrapper.replace(':', '/')}.md"
            actual = _wrapper_command_path(wrapper)
            if actual != expected:
                mismatches.append((wrapper, actual, expected))

        assert not mismatches, (
            "Wrappers with invalid COMMAND_FILE_PATH: "
            f"{mismatches[:10]}"
        )


class TestDenylistIntegrity:
    """Denylist quality checks."""

    def test_denylist_growth_requires_justification(self):
        denylist = _load_denylist()
        entries = denylist.get("commands_without_wrapper", [])
        empty_reasons = [
            e["command"] for e in entries if not e.get("reason", "").strip()
        ]
        assert not empty_reasons, (
            f"{len(empty_reasons)} denylist entries without justification: "
            f"{empty_reasons[:5]}"
        )

    def test_allowlist_entries_have_justification(self):
        denylist = _load_denylist()
        entries = denylist.get("wrappers_without_command", [])
        empty_reasons = [
            e["wrapper"] for e in entries if not e.get("reason", "").strip()
        ]
        assert not empty_reasons, (
            f"{len(empty_reasons)} allowlist entries without justification: "
            f"{empty_reasons[:5]}"
        )

    def test_slash_executor_in_allowlist(self):
        denylist = _load_denylist()
        allowlist = {e["wrapper"] for e in denylist.get("wrappers_without_command", [])}
        assert "slash-executor" in allowlist, (
            "slash-executor must be in wrappers_without_command allowlist (D015-c)"
        )

    def test_denylist_commands_and_allowlist_wrappers_exist(self):
        denylist = _load_denylist()
        commands = _discover_invocable_commands()
        wrappers = _discover_wrappers()
        denied = {
            e["command"] for e in denylist.get("commands_without_wrapper", [])
        }
        allowlisted = {
            e["wrapper"] for e in denylist.get("wrappers_without_command", [])
        }
        assert not (denied - commands), (
            f"Stale denylist commands: {sorted(denied - commands)}"
        )
        assert not (allowlisted - wrappers), (
            f"Missing allowlist wrappers: {sorted(allowlisted - wrappers)}"
        )


class TestGeneratorCheckMode:
    """Verify the generator --check mode reports bidirectional parity."""

    def test_check_mode_exits_zero_when_parity_holds(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"gen-kimi-wrappers.py --check exited {result.returncode}.\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )

    def test_check_mode_exits_nonzero_when_unjustified_gap(
        self, tmp_path, monkeypatch, capsys
    ):
        generator = _load_generator_module()
        commands_dir = tmp_path / ".claude" / "commands"
        skills_dir = tmp_path / ".agents" / "skills"
        codex_dir = tmp_path / ".codex" / "skills"
        commands_dir.mkdir(parents=True)
        skills_dir.mkdir(parents=True)
        codex_dir.mkdir(parents=True)
        (commands_dir / "missing-wrapper.md").write_text("# Missing wrapper\n")

        monkeypatch.setattr(generator, "COMMANDS_DIR", commands_dir)
        monkeypatch.setattr(generator, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(generator, "CODEX_SKILLS_DIR", codex_dir)
        commands = generator.discover_commands()

        with pytest.raises(SystemExit) as exc:
            generator._run_check(commands, commands, set(), set())

        assert exc.value.code == 1
        assert "MISSING: missing-wrapper" in capsys.readouterr().out

    def test_parity_report_is_disaggregated(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        output = result.stdout
        assert "Axis 1: command -> wrapper" in output, (
            "Report missing Axis 1 section"
        )
        assert "Axis 2: wrapper -> command" in output, (
            "Report missing Axis 2 section"
        )

    @pytest.mark.parametrize("tier", [1, 2, 3])
    def test_check_mode_composes_with_tier_filter(self, tier):
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR_PATH),
                "--check",
                "--tier",
                str(tier),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"--check --tier {tier} exited {result.returncode}.\n"
            f"stdout: {result.stdout[-1000:]}\n"
            f"stderr: {result.stderr[-1000:]}"
        )

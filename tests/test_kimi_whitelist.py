"""Pure-logic tests for the Claude→Kimi command adapter and whitelist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from workflow_app.command_queue.kimi_whitelist import (
    KIMI_COMPATIBLE_COMMANDS,
    KIMI_PROGRESS_PATH,
    KIMI_THRESHOLD,
    adapt_to_kimi,
    is_kimi_compatible,
)


def _repo_root() -> Path:
    """Walk up from this test file until we find the SystemForge repo root.

    Identified by the presence of `blacksmith/claude-to-kimi/progress.md`.
    Tests run from the workflow-app dir; progress.md lives 2 levels up.
    """
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / KIMI_PROGRESS_PATH).is_file():
            return parent
    raise RuntimeError(f"Could not locate {KIMI_PROGRESS_PATH} above {cur}")


def _load_progress_scores() -> dict[str, int]:
    """Parse `% Kimi` scores from progress.md. Returns {command_name: score}."""
    path = _repo_root() / KIMI_PROGRESS_PATH
    text = path.read_text(encoding="utf-8")
    # Row format: | N | `/cmd ...` | Cat | %Kimi | Eixo | Justif | Class | Status |
    # ID column accepts numeric ("1", "71"), single-letter prefix ("B1", "B35"),
    # or multi-letter prefix ("DL1", "DL5") — appendices use these naming schemes.
    row_re = re.compile(
        r"^\|\s*[A-Za-z]*\d+\s*\|\s*`(/[^` ]+)[^`]*`\s*\|\s*[^|]+\|\s*(\d+)\s*\|",
        re.MULTILINE,
    )
    return {cmd: int(score) for cmd, score in row_re.findall(text)}


class TestWhitelist:
    def test_whitelist_size_matches_progress_md(self):
        # 29 (canonical loop, score >=79) + 6 (brief, score >=80)
        # + 8 (brief, score 78 após threshold ajustado para 78)
        # + 1 (daily-loop:do, score 86)
        # + 1 (test-autoflow-auto, score 85) = 45
        # + 1 (/dcp:matrix-mark-loops, score 95) = 81
        # + 1 (/dcp:matrix-filter-modules, score 72) = 82
        # + 1 (/legacy:enqueue-all-modules, score 73) = 83
        # + 1 (/cmd:autocast-put, score 91) = 84
        # + 1 (/loop-rocksmash:compare, score 85) = 85
        # + 2 (Option D atomization: /blog:stockpile-finalize-package, score 88;
        #      /blog:stockpile-validate, score 90) = 87
        assert len(KIMI_COMPATIBLE_COMMANDS) == 87

    def test_known_compatible_commands(self):
        for cmd in ("/secrets-scan", "/qa:prep", "/env-creation", "/sync:github"):
            assert is_kimi_compatible(cmd), f"{cmd} should be Kimi-compatible"

    def test_known_incompatible_commands(self):
        # Comandos KEEP_CLAUDE de progress.md
        for cmd in (
            "/review-executed-module",
            "/qa:trace",
            "/validate-roles",
            "/validate-billing",
            "/execute-task",
            "/back-end-build",
            "/front-end-build",
            "/build-verify",
            "/gate:frontend-runtime",
            "/commit:simple",
        ):
            assert not is_kimi_compatible(cmd), f"{cmd} should NOT be Kimi-compatible"

    def test_dropped_below_threshold_commands_are_excluded(self):
        # 8 comandos removidos da whitelist na transicao "KIMI_OK uniao KIMI_PREFERRED"
        # -> ">= 79%". Eles vivem na faixa 70-77% no progress.md.
        for cmd in (
            "/create-task",            # 72
            "/sync:mcp",               # 71
            "/db-migration-create",    # 74
            "/front-end-obvious",      # 77
            "/infra-smoke-check",      # 74
            "/frontend:mobile-check",  # 70
            "/frontend:assets-check",  # 74
            "/dependency-audit",       # 71
        ):
            assert not is_kimi_compatible(cmd), (
                f"{cmd} esta abaixo do threshold {KIMI_THRESHOLD} — nao deveria"
                " estar na whitelist Kimi"
            )


class TestHardeningProgressMdSync:
    """Guard against drift between kimi_whitelist.py and progress.md.

    Reparses progress.md at test time and fails loudly if any whitelisted
    command falls below KIMI_THRESHOLD or disappears from the source of truth.
    """

    def test_progress_md_is_readable(self):
        scores = _load_progress_scores()
        assert scores, "progress.md should yield at least one scored row"
        assert len(scores) >= 60, (
            f"Suspicious — only {len(scores)} rows parsed from progress.md;"
            " regex may be broken"
        )

    def test_every_whitelisted_command_appears_in_progress_md(self):
        scores = _load_progress_scores()
        missing = [c for c in KIMI_COMPATIBLE_COMMANDS if c not in scores]
        assert not missing, (
            f"Whitelist references commands absent from progress.md: {missing}."
            " Either re-score them in progress.md or remove from whitelist."
        )

    def test_every_whitelisted_command_meets_threshold(self):
        scores = _load_progress_scores()
        offenders = [
            (cmd, scores[cmd])
            for cmd in KIMI_COMPATIBLE_COMMANDS
            if cmd in scores and scores[cmd] < KIMI_THRESHOLD
        ]
        assert not offenders, (
            f"Whitelist contains commands below threshold {KIMI_THRESHOLD}: "
            f"{offenders}. Drop them or update KIMI_THRESHOLD."
        )

    def test_no_above_threshold_command_is_orphaned(self):
        """Inverse drift check — if progress.md re-scores something to >=
        KIMI_THRESHOLD and it's not in the whitelist, surface it.

        Soft warning: marks xfail rather than hard fail, because the human may
        still have a deliberate reason to keep a high-score command off Kimi
        (e.g. it gained a verification_required gate after the score was set).
        """
        scores = _load_progress_scores()
        candidates = [
            (cmd, score)
            for cmd, score in scores.items()
            if score >= KIMI_THRESHOLD and cmd not in KIMI_COMPATIBLE_COMMANDS
        ]
        if candidates:
            pytest.xfail(
                f"Commands meet threshold but are not whitelisted: {candidates}."
                " Add to KIMI_COMPATIBLE_COMMANDS or document why they are excluded."
            )


class TestCompatibilityHelper:
    def test_compatibility_ignores_args(self):
        assert is_kimi_compatible("/qa:prep --module 1")
        assert is_kimi_compatible("/seed-data-create .claude/projects/foo.json")

    def test_empty_input_is_incompatible(self):
        assert not is_kimi_compatible("")
        assert not is_kimi_compatible("   ")


class TestAdapter:
    """Adapter rewrites Claude slash-commands into Kimi /skill: invocations.

    Kimi auto-discovers skills in .agents/skills/{name}.md when
    `merge_all_available_skills = true` is set in ~/.kimi/config.toml.
    Each skill points at the underlying .claude/commands spec, so the adapter
    just rewrites the head and forwards args verbatim.
    """

    def test_simple_command_no_args(self):
        assert adapt_to_kimi("/secrets-scan") == "/skill:secrets-scan"

    def test_command_with_namespace_colon(self):
        # ":" preservado — Kimi skills usam ":" literal no filename
        assert adapt_to_kimi("/qa:prep") == "/skill:qa:prep"

    def test_command_with_args(self):
        out = adapt_to_kimi("/qa:prep --module 1 .claude/projects/foo.json")
        assert out == "/skill:qa:prep --module 1 .claude/projects/foo.json"

    def test_command_preserves_config_path(self):
        out = adapt_to_kimi("/seed-data-create .claude/projects/foo.json")
        assert out == "/skill:seed-data-create .claude/projects/foo.json"

    def test_command_with_double_namespace(self):
        out = adapt_to_kimi("/backend:scan --module 2")
        assert out == "/skill:backend:scan --module 2"

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            adapt_to_kimi("")
        with pytest.raises(ValueError):
            adapt_to_kimi("   ")
        with pytest.raises(ValueError):
            adapt_to_kimi("not-a-slash-command")


class TestSkillFilesExist:
    """Hardening: every whitelisted command must have a matching skill file in
    .agents/skills/{name}.md — otherwise Kimi can't resolve /skill:NAME and
    will reply with the literal invocation as plain text.
    """

    def test_skill_files_exist_for_whitelist(self):
        repo = _repo_root()
        skills_dir = repo / ".agents" / "skills"
        assert skills_dir.is_dir(), f"missing skills dir: {skills_dir}"

        missing = []
        for cmd in KIMI_COMPATIBLE_COMMANDS:
            skill_name = cmd.lstrip("/")
            skill_file = skills_dir / f"{skill_name}.md"
            if not skill_file.is_file():
                missing.append(str(skill_file))

        assert not missing, (
            "Whitelisted Kimi commands without matching .agents/skills/*.md "
            f"({len(missing)}): {missing}. Either create the skill file "
            "(see .agents/skills/create-task.md for the canonical template) "
            "or remove the command from KIMI_COMPATIBLE_COMMANDS."
        )

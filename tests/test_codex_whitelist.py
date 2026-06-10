"""Pure-logic tests for the Codex worker whitelist.

Sibling of test_kimi_whitelist.py. The Codex whitelist mirrors the Kimi one
(regra 1) but inverts the Eixo 6 axis (regra 3): strong codex/adversarial
wiring raises the Codex score. These tests also enforce regra 5 mechanically —
every whitelisted command must declare a non-empty `codex_publish_format` in
progress.md and resolve to a `.claude/commands/*.md` file (the slash-executor
publish target).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from workflow_app.command_queue.codex_whitelist import (
    CODEX_COMPATIBLE_COMMANDS,
    CODEX_PROGRESS_PATH,
    CODEX_THRESHOLD,
    IMAGE_GENERATION_COMMANDS,
    IMAGE_GENERATION_SCORE,
    is_codex_compatible,
    is_image_generation_command,
)


def _repo_root() -> Path:
    """Walk up from this test file until we find the SystemForge repo root.

    Identified by the presence of `blacksmith/claude-to-codex/progress.md`.
    Tests run from the workflow-app dir; progress.md lives 2 levels up.
    """
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / CODEX_PROGRESS_PATH).is_file():
            return parent
    raise RuntimeError(f"Could not locate {CODEX_PROGRESS_PATH} above {cur}")


def _load_progress_rows() -> dict[str, tuple[int, str]]:
    """Parse progress.md. Returns {command_name: (score, codex_publish_format)}.

    Row format:
    | N | `/cmd ...` | Cat | %Codex | Eixo | codex_publish_format | Justif | Class | Status |
    The ID column accepts numeric or letter-prefixed numeric ids.
    """
    path = _repo_root() / CODEX_PROGRESS_PATH
    text = path.read_text(encoding="utf-8")
    row_re = re.compile(
        r"^\|\s*[A-Za-z]*\d+\s*\|\s*`(/[^` ]+)[^`]*`\s*\|\s*[^|]+\|\s*(\d+)\s*\|"
        r"\s*[^|]*\|\s*([^|]*?)\s*\|",
        re.MULTILINE,
    )
    out: dict[str, tuple[int, str]] = {}
    for cmd, score, fmt in row_re.findall(text):
        out[cmd] = (int(score), fmt.strip())
    return out


def _command_md_path(repo: Path, command_name: str) -> Path:
    """Map a slash-command head to its .claude/commands/{path}.md file.

    Mirrors the resolution done by `_build_codex_slash_executor_prompt`:
    strip the leading '/', turn ':' namespaces into '/', append '.md'.
    """
    slug = command_name.lstrip("/").replace(":", "/")
    return repo / ".claude" / "commands" / f"{slug}.md"


class TestWhitelist:
    def test_whitelist_size_matches_progress_md(self):
        # 13 comandos C2 Review (wiring Codex/adversarial) + 1 comando C3 Assets
        # (/pictures-create) com eixo distinto: capacidade EXCLUSIVA de geracao
        # de imagem (so o Codex tem gpt-image-1). codex_publish_format=slash-executor.
        assert len(CODEX_COMPATIBLE_COMMANDS) == 14

    def test_known_compatible_commands(self):
        for cmd in (
            "/cmd:review",
            "/mcp:cmd-best-practices",
            "/python:py-review",
            "/pictures-create",
        ):
            assert is_codex_compatible(cmd), f"{cmd} should be Codex-compatible"

    def test_known_incompatible_commands(self):
        # Deterministicos puros -> destino Kimi/Claude, nunca Codex.
        for cmd in (
            "/env-creation",
            "/secrets-scan",
            "/create-overview",
            "/seed-data-create",
            "/c4-diagram-create",
            "/execute-task",
        ):
            assert not is_codex_compatible(cmd), f"{cmd} should NOT be Codex-compatible"


class TestCompatibilityHelper:
    def test_compatibility_ignores_args(self):
        assert is_codex_compatible("/cmd:review .claude/commands/foo.md")
        assert is_codex_compatible("/python:py-review --module 2")

    def test_empty_input_is_incompatible(self):
        assert not is_codex_compatible("")
        assert not is_codex_compatible("   ")

    def test_namespace_colon_preserved_in_matching(self):
        assert is_codex_compatible("/study:debate")
        assert not is_codex_compatible("/study")


class TestHardeningProgressMdSync:
    """Guard against drift between codex_whitelist.py and progress.md."""

    def test_progress_md_is_readable(self):
        rows = _load_progress_rows()
        assert rows, "progress.md should yield at least one scored row"
        assert len(rows) >= 13, (
            f"Suspicious — only {len(rows)} rows parsed from progress.md;"
            " regex may be broken"
        )

    def test_every_whitelisted_command_appears_in_progress_md(self):
        rows = _load_progress_rows()
        missing = [c for c in CODEX_COMPATIBLE_COMMANDS if c not in rows]
        assert not missing, (
            f"Whitelist references commands absent from progress.md: {missing}."
            " Either re-score them in progress.md or remove from whitelist."
        )

    def test_every_whitelisted_command_meets_threshold(self):
        rows = _load_progress_rows()
        offenders = [
            (cmd, rows[cmd][0])
            for cmd in CODEX_COMPATIBLE_COMMANDS
            if cmd in rows and rows[cmd][0] < CODEX_THRESHOLD
        ]
        assert not offenders, (
            f"Whitelist contains commands below threshold {CODEX_THRESHOLD}: "
            f"{offenders}. Drop them or update CODEX_THRESHOLD."
        )

    def test_every_whitelisted_command_has_publish_format(self):
        """Regra 5 (criterio mecanico): cada comando whitelisted declara um
        `codex_publish_format` nao-vazio. Comando sem o campo nunca entra no
        frozenset — falha aqui se entrar.
        """
        rows = _load_progress_rows()
        offenders = [
            cmd
            for cmd in CODEX_COMPATIBLE_COMMANDS
            if cmd in rows and not rows[cmd][1].strip("- ")
        ]
        assert not offenders, (
            "Whitelisted commands without a non-empty codex_publish_format "
            f"(regra 5): {offenders}. Define o formato de publicacao em "
            "progress.md ou remova da whitelist."
        )

    def test_no_above_threshold_command_is_orphaned(self):
        """Inverse drift — a command scored >= threshold with a publish format
        but absent from the whitelist. Soft (xfail): the human may keep it off
        Codex deliberately.
        """
        rows = _load_progress_rows()
        candidates = [
            (cmd, score)
            for cmd, (score, fmt) in rows.items()
            if score >= CODEX_THRESHOLD
            and fmt.strip("- ")
            and cmd not in CODEX_COMPATIBLE_COMMANDS
        ]
        if candidates:
            pytest.xfail(
                f"Commands meet threshold + have publish format but are not "
                f"whitelisted: {candidates}. Add them or document the exclusion."
            )


class TestSlashExecutorTargetExists:
    """Hardening: every whitelisted command must resolve to a
    `.claude/commands/{slug}.md` file — `_build_codex_slash_executor_prompt`
    returns None (aborting the dispatch) when the markdown is missing.
    """

    def test_command_md_files_exist_for_whitelist(self):
        repo = _repo_root()
        commands_dir = repo / ".claude" / "commands"
        assert commands_dir.is_dir(), f"missing commands dir: {commands_dir}"

        missing = [
            str(_command_md_path(repo, cmd))
            for cmd in CODEX_COMPATIBLE_COMMANDS
            if not _command_md_path(repo, cmd).is_file()
        ]
        assert not missing, (
            "Whitelisted Codex commands without a matching "
            f".claude/commands/*.md ({len(missing)}): {missing}. The Codex "
            "slash-executor cannot resolve them. Create the command file or "
            "remove the command from CODEX_COMPATIBLE_COMMANDS."
        )


class TestImageGenerationRule:
    """Regra de capacidade exclusiva: comandos que CRIAM imagem no repositorio
    recebem `% Codex = 100` automaticamente (so o Codex gera pixel). Guarda a
    regra contra drift: subconjunto da whitelist + score 100 em progress.md.
    """

    def test_image_gen_is_subset_of_codex_whitelist(self):
        # Todo comando de geracao de imagem e necessariamente Codex-compativel.
        orphan = IMAGE_GENERATION_COMMANDS - CODEX_COMPATIBLE_COMMANDS
        assert not orphan, (
            f"image-gen commands fora da whitelist Codex: {orphan}. "
            "Adicione-os a CODEX_COMPATIBLE_COMMANDS."
        )

    def test_image_gen_commands_score_exactly_100(self):
        # Regra automatica: score == IMAGE_GENERATION_SCORE (100) em progress.md.
        rows = _load_progress_rows()
        offenders = [
            (cmd, rows[cmd][0])
            for cmd in IMAGE_GENERATION_COMMANDS
            if cmd in rows and rows[cmd][0] != IMAGE_GENERATION_SCORE
        ]
        assert not offenders, (
            f"image-gen commands com score != {IMAGE_GENERATION_SCORE}: {offenders}. "
            "Regra de capacidade exclusiva exige 100 na hora (so o Codex gera imagem)."
        )

    def test_image_gen_commands_present_in_progress_md(self):
        rows = _load_progress_rows()
        missing = [c for c in IMAGE_GENERATION_COMMANDS if c not in rows]
        assert not missing, (
            f"image-gen commands ausentes de progress.md: {missing}."
        )

    def test_is_image_generation_command_helper(self):
        assert is_image_generation_command("/pictures-create")
        assert is_image_generation_command("/pictures-create --module 2")
        assert not is_image_generation_command("/cmd:review")
        assert not is_image_generation_command("")
        # Coerencia: todo image-gen e codex-compativel.
        for cmd in IMAGE_GENERATION_COMMANDS:
            assert is_codex_compatible(cmd)

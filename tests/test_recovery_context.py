"""Pure unit tests for the recovery-context snapshot writer.

No Qt — exercises workflow_app.metrics_bar.recovery_context directly.

Contract (TASK 06 of loop 06-01-listener-recovery-command):
- write to blacksmith/recovery/context/{TS}-{channel}-{reason}.md
- TS = strftime("%Y%m%dT%H%M%SZ") UTC (sortable)
- sanitize channel/reason to [A-Za-z0-9._-]; corrupted channel -> BLOCKED
- atomic write (temp + os.replace), UTF-8, no overwrite (-2/-3 suffix)
- first line = disclaimer; minimum fields always present (INDISPONIVEL when
  absent); output masked {first10}***{last4}
- blacksmith/recovery/ must stay covered by .gitignore
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from workflow_app.metrics_bar.recovery_context import (
    DISCLAIMER,
    UNAVAILABLE,
    RecoveryContext,
    RecoveryContextBlocked,
    llm_for_channel,
    mask_output,
    sanitize_token,
    write_recovery_context,
)

# Repo root: tests/ -> workflow-app/ -> ai-forge/ -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[3]

_FIXED = datetime(2026, 6, 1, 9, 41, 7, tzinfo=timezone.utc)


def _make(channel="workspace", reason="BLOCKED", **kw) -> RecoveryContext:
    return RecoveryContext(channel=channel, reason=reason, **kw)


# ── ASSERT 1: writes under context/ subdir, never the recovery root ──────── #


def test_writes_into_context_subdir_not_root(tmp_path: Path):
    target = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    rel = target.relative_to(tmp_path)
    assert rel.parts[:3] == ("blacksmith", "recovery", "context")
    # the file is NOT directly inside blacksmith/recovery/ (reserved for reports)
    assert target.parent == tmp_path / "blacksmith" / "recovery" / "context"


# ── ASSERT 2: filename matches {TS}-{channel}-{reason}.md, sortable TS ───── #


def test_filename_pattern_and_sortable_ts(tmp_path: Path):
    target = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    assert target.name == "20260601T094107Z-workspace-BLOCKED.md"
    assert re.match(r"^\d{8}T\d{6}Z-[A-Za-z0-9._-]+-[A-Za-z0-9._-]+\.md$",
                    target.name)


# ── ASSERT 3: first line is exactly the disclaimer ───────────────────────── #


def test_first_line_is_disclaimer(tmp_path: Path):
    target = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    first_line = target.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == DISCLAIMER


# ── ASSERT 4: all minimum fields present; absent ones -> INDISPONIVEL ────── #


def test_minimum_fields_present_with_unavailable_sentinel(tmp_path: Path):
    target = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    text = target.read_text(encoding="utf-8")
    for field_label in (
        "timestamp:", "channel:", "llm:", "reason:",
        "autocast_state:", "last_command:", "output_excerpt:",
        "detected_paths:",
    ):
        assert field_label in text, f"missing field {field_label}"
    # nothing was provided beyond channel/reason -> sentinels present
    assert f"autocast_state: {UNAVAILABLE}" in text
    assert f"last_command: {UNAVAILABLE}" in text
    assert f"output_excerpt: {UNAVAILABLE}" in text
    assert f"- {UNAVAILABLE}" in text  # detected_paths placeholder


# ── ASSERT 5: llm_for_channel binding + unmapped -> INDISPONIVEL ──────────── #


def test_llm_for_channel_binding(tmp_path: Path):
    assert llm_for_channel("workspace") == "kimi"
    assert llm_for_channel("workspace_xterm") == "codex"
    assert llm_for_channel("interactive") == "claude"
    assert llm_for_channel("interactive", "kimi") == "kimi"
    assert llm_for_channel("garbage-channel") == UNAVAILABLE


# ── ASSERT 6: output excerpt masked as {first10}***{last4} ──────────────── #


def test_output_excerpt_masked(tmp_path: Path):
    secret = "sk-ABCDEFGHIJ-very-long-secret-token-WXYZ"
    target = write_recovery_context(
        _make(output_excerpt=secret), repo_root=tmp_path, when=_FIXED
    )
    text = target.read_text(encoding="utf-8")
    assert f"output_excerpt: {secret[:10]}***{secret[-4:]}" in text
    # raw secret middle must not leak
    assert "very-long-secret-token" not in text
    # short snippet fully masked
    assert mask_output("short") == "***"


# ── ASSERT 7: sanitization of channel/reason to [A-Za-z0-9._-] ──────────── #


def test_sanitization_of_tokens(tmp_path: Path):
    target = write_recovery_context(
        _make(channel="work space/../x", reason="VERIFY FAILED!!"),
        repo_root=tmp_path,
        when=_FIXED,
    )
    # filename is a single safe component: no separator, no spaces, only the
    # allowed charset. Dots survive (they are in [A-Za-z0-9._-]); since the
    # separator is stripped, a mid-token ".." cannot traverse directories.
    assert "/" not in target.name
    assert " " not in target.name
    assert re.fullmatch(r"[A-Za-z0-9._-]+", target.stem)
    assert target.parent == tmp_path / "blacksmith" / "recovery" / "context"
    assert sanitize_token("a b/c!d") == "a_b_c_d"
    # pure-traversal tokens neutralize to empty (channel -> BLOCKED upstream)
    assert sanitize_token("../..") == ""


# ── ASSERT 8: corrupted channel -> RecoveryContextBlocked (failure/BLOCKED) ─ #


def test_corrupted_channel_raises_blocked(tmp_path: Path):
    with pytest.raises(RecoveryContextBlocked):
        write_recovery_context(
            _make(channel="///"), repo_root=tmp_path, when=_FIXED
        )
    with pytest.raises(RecoveryContextBlocked):
        write_recovery_context(
            _make(channel=""), repo_root=tmp_path, when=_FIXED
        )


# ── ASSERT 9: no-overwrite (suffix -2) + blacksmith/recovery/ gitignored ── #


def test_no_overwrite_and_gitignore_coverage(tmp_path: Path):
    first = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    second = write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    assert first != second
    assert second.name == "20260601T094107Z-workspace-BLOCKED-2.md"
    assert first.exists() and second.exists()

    # blacksmith/recovery/ is covered by .gitignore in the real repo
    probe = "blacksmith/recovery/context/probe.md"
    result = subprocess.run(
        ["git", "check-ignore", probe],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{probe} is NOT gitignored (stdout={result.stdout!r})"
    )


# ── extra: atomic write leaves no .tmp residue ───────────────────────────── #


def test_no_temp_residue(tmp_path: Path):
    write_recovery_context(_make(), repo_root=tmp_path, when=_FIXED)
    ctx_dir = tmp_path / "blacksmith" / "recovery" / "context"
    residue = [p.name for p in ctx_dir.iterdir() if p.name.startswith(".ctx-")]
    assert residue == []


# ── extra: naive datetime is treated as UTC ──────────────────────────────── #


def test_naive_datetime_treated_as_utc(tmp_path: Path):
    naive = datetime(2026, 6, 1, 9, 41, 7)
    target = write_recovery_context(_make(), repo_root=tmp_path, when=naive)
    assert target.name.startswith("20260601T094107Z-")

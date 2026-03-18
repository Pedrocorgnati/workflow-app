"""Tests for claude_md_hasher and VersionChecker (module-05/TASK-4)."""

from __future__ import annotations

from unittest.mock import MagicMock

from workflow_app.templates.claude_md_hasher import compute_hash, find_claude_md
from workflow_app.templates.template_manager import TemplateManager
from workflow_app.templates.version_checker import VersionChecker, VersionCheckResult

# ─── compute_hash ───────────────────────────────────────────────────────────── #


class TestComputeHash:
    def test_returns_64_char_hex_string(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("# CLAUDE.md\n\nConteúdo de teste.")
        result = compute_hash(str(p))
        assert result is not None
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_content_same_hash(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("conteudo fixo")
        h1 = compute_hash(str(p))
        h2 = compute_hash(str(p))
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        p1 = tmp_path / "A.md"
        p1.write_text("versao A")
        p2 = tmp_path / "B.md"
        p2.write_text("versao B diferente")
        assert compute_hash(str(p1)) != compute_hash(str(p2))

    def test_returns_none_for_nonexistent_file(self):
        assert compute_hash("/caminho/inexistente/CLAUDE.md") is None

    def test_returns_none_for_empty_path(self):
        assert compute_hash("") is None

    def test_returns_none_for_none(self):
        assert compute_hash(None) is None

    def test_normalizes_crlf(self, tmp_path):
        """CRLF and LF produce the same hash."""
        p_lf = tmp_path / "lf.md"
        p_lf.write_bytes(b"line1\nline2\n")
        p_crlf = tmp_path / "crlf.md"
        p_crlf.write_bytes(b"line1\r\nline2\r\n")
        assert compute_hash(str(p_lf)) == compute_hash(str(p_crlf))


# ─── find_claude_md ─────────────────────────────────────────────────────────── #


class TestFindClaudeMd:
    def test_finds_in_current_dir(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# test")
        result = find_claude_md(str(tmp_path))
        assert result is not None
        assert result.endswith("CLAUDE.md")

    def test_finds_in_parent_dir(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# test")
        child = tmp_path / "sub" / "deep"
        child.mkdir(parents=True)
        result = find_claude_md(str(child))
        assert result is not None
        assert result.endswith("CLAUDE.md")

    def test_returns_none_if_not_found(self, tmp_path):
        child = tmp_path / "empty" / "deep"
        child.mkdir(parents=True)
        result = find_claude_md(str(child))
        assert result is None


# ─── VersionChecker ─────────────────────────────────────────────────────────── #


class TestVersionChecker:
    def test_suppressed_returns_not_outdated(self):
        manager = MagicMock(spec=TemplateManager)
        checker = VersionChecker(manager=manager)
        checker.suppress_for_session()
        result = checker.check_factory_templates()
        assert result.is_outdated is False
        manager.list_templates.assert_not_called()

    def test_detects_outdated_templates(self, tmp_db_manager, tmp_path):
        """When CLAUDE.md hash differs from stored sha256, templates are outdated."""
        # Seed factory templates with a known hash
        from workflow_app.templates.factory_templates import seed_factory_templates

        seed_factory_templates(tmp_db_manager, sha256="old_hash_value")

        # Create a CLAUDE.md with different content
        claude_path = tmp_path / "CLAUDE.md"
        claude_path.write_text("New CLAUDE.md content that produces a different hash")

        tm = TemplateManager(database_manager=tmp_db_manager)
        checker = VersionChecker(manager=tm)
        result = checker.check_factory_templates(claude_md_path=str(claude_path))

        assert result.is_outdated is True
        assert len(result.outdated_names) == 9
        assert result.current_hash is not None
        assert len(result.current_hash) == 64

    def test_not_outdated_when_hash_matches(self, tmp_db_manager, tmp_path):
        """When CLAUDE.md hash matches stored sha256, no templates are outdated."""
        claude_path = tmp_path / "CLAUDE.md"
        claude_path.write_text("Matching content")
        matching_hash = compute_hash(str(claude_path))

        # Use refresh to set the correct sha256 (seed is idempotent, won't update existing)
        from workflow_app.templates.factory_templates import refresh_factory_templates

        refresh_factory_templates(tmp_db_manager, new_hash=matching_hash)

        tm = TemplateManager(database_manager=tmp_db_manager)
        checker = VersionChecker(manager=tm)
        result = checker.check_factory_templates(claude_md_path=str(claude_path))

        assert result.is_outdated is False
        assert len(result.outdated_names) == 0

    def test_no_claude_md_returns_not_outdated(self):
        """When CLAUDE.md is not found, version checking is disabled."""
        manager = MagicMock(spec=TemplateManager)
        checker = VersionChecker(manager=manager)
        result = checker.check_factory_templates(
            claude_md_path="/nonexistent/CLAUDE.md"
        )
        assert result.is_outdated is False


# ─── VersionCheckResult ─────────────────────────────────────────────────────── #


def test_version_check_result_defaults():
    r = VersionCheckResult()
    assert r.is_outdated is False
    assert r.current_hash is None
    assert r.outdated_names == []

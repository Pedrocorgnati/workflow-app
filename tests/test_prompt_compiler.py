"""Tests for the prompt compiler module.

Covers the minimum acceptance criteria from task 007:

- Top-level command resolution
- Namespaced command resolution (colon -> directory separator)
- Literal argument passing (no variable substitution)
- Hash divergence when the target file content changes
- Path resolved outside the repo root is refused (security)
"""

from __future__ import annotations

import hashlib
import textwrap

import pytest

from workflow_app.prompt_compiler import (
    CommandNotFoundError,
    CompiledPrompt,
    PathTraversalError,
    PromptCompiler,
    _strip_frontmatter,
    _parse_frontmatter_raw,
    _normalise_name,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path):
    """Create a minimal repo layout with .claude/commands/."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    return tmp_path


def _write_command(repo, relative_path, content):
    """Write a command markdown file under .claude/commands/."""
    target = repo / ".claude" / "commands" / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ------------------------------------------------------------------
# Top-level command resolution
# ------------------------------------------------------------------


class TestTopLevelCommand:
    def test_resolve_simple_command(self, repo):
        _write_command(repo, "adr-create.md", "# ADR\nCreate an ADR.")
        compiler = PromptCompiler(repo)
        path = compiler.resolve_command_path("/adr-create")
        assert path == (repo / ".claude/commands/adr-create.md").resolve()

    def test_compile_returns_body_without_frontmatter(self, repo):
        content = textwrap.dedent("""\
            ---
            description: Create an ADR
            model: opus
            ---
            # ADR
            Create an Architecture Decision Record.
        """)
        _write_command(repo, "adr-create.md", content)
        compiler = PromptCompiler(repo)
        result = compiler.compile("/adr-create")

        assert isinstance(result, CompiledPrompt)
        assert "# ADR" in result.prompt_text
        assert "Create an Architecture Decision Record." in result.prompt_text
        assert "description: Create an ADR" not in result.prompt_text
        assert "model: opus" not in result.prompt_text

    def test_command_name_normalised(self, repo):
        _write_command(repo, "daily.md", "# Daily")
        compiler = PromptCompiler(repo)
        result = compiler.compile("daily")
        assert result.command_name == "/daily"

    def test_leading_slashes_stripped(self, repo):
        _write_command(repo, "daily.md", "# Daily")
        compiler = PromptCompiler(repo)
        path = compiler.resolve_command_path("///daily")
        assert path.name == "daily.md"

    def test_command_not_found(self, repo):
        compiler = PromptCompiler(repo)
        with pytest.raises(CommandNotFoundError, match="not found"):
            compiler.resolve_command_path("/nonexistent-command")


# ------------------------------------------------------------------
# Namespaced command resolution (D-32)
# ------------------------------------------------------------------


class TestNamespacedCommand:
    def test_single_namespace(self, repo):
        _write_command(repo, "android/accessibility.md", "# A11y audit")
        compiler = PromptCompiler(repo)
        path = compiler.resolve_command_path("/android:accessibility")
        assert path == (repo / ".claude/commands/android/accessibility.md").resolve()

    def test_deep_namespace(self, repo):
        _write_command(repo, "loop/iteraction/execute-task.md", "# Execute")
        compiler = PromptCompiler(repo)
        path = compiler.resolve_command_path("/loop:iteraction:execute-task")
        expected = repo / ".claude/commands/loop/iteraction/execute-task.md"
        assert path == expected.resolve()

    def test_compile_namespaced_body(self, repo):
        content = textwrap.dedent("""\
            ---
            description: Accessibility audit
            ---
            Audit and fix accessibility issues.
        """)
        _write_command(repo, "android/accessibility.md", content)
        compiler = PromptCompiler(repo)
        result = compiler.compile("/android:accessibility")

        assert "Audit and fix accessibility issues." in result.prompt_text
        assert "description:" not in result.prompt_text
        assert result.command_name == "/android:accessibility"

    def test_namespaced_not_found(self, repo):
        compiler = PromptCompiler(repo)
        with pytest.raises(CommandNotFoundError):
            compiler.resolve_command_path("/foo:bar:baz")


# ------------------------------------------------------------------
# Literal argument passing
# ------------------------------------------------------------------


class TestArgumentPassing:
    def test_arguments_appended_to_body(self, repo):
        _write_command(repo, "adr-create.md", "# ADR\nCreate an ADR.")
        compiler = PromptCompiler(repo)
        result = compiler.compile("/adr-create", ".claude/project-2.json")

        assert "# ADR" in result.prompt_text
        assert ".claude/project-2.json" in result.prompt_text

    def test_arguments_passed_literal_no_substitution(self, repo):
        """Arguments must NOT be interpolated into template variables."""
        content = "# Cmd\nUse {project_name} and {docs_root}."
        _write_command(repo, "test-cmd.md", content)
        compiler = PromptCompiler(repo)
        args = "--kimi --codex"
        result = compiler.compile("/test-cmd", args)

        # The body keeps its original {placeholders} untouched
        assert "{project_name}" in result.prompt_text
        assert "{docs_root}" in result.prompt_text
        # Arguments appear literally after the body
        assert "--kimi --codex" in result.prompt_text

    def test_empty_arguments_no_trailing_whitespace(self, repo):
        _write_command(repo, "daily.md", "# Daily report")
        compiler = PromptCompiler(repo)
        result = compiler.compile("/daily", "")
        assert result.prompt_text.rstrip() == "# Daily report"
        assert result.arguments == ""

    def test_arguments_stored_in_result(self, repo):
        _write_command(repo, "daily.md", "# Daily")
        compiler = PromptCompiler(repo)
        result = compiler.compile("/daily", "--force --verbose")
        assert result.arguments == "--force --verbose"


# ------------------------------------------------------------------
# Hash divergence
# ------------------------------------------------------------------


class TestContentHash:
    def test_hash_matches_file_content(self, repo):
        content = "# ADR\nCreate an ADR."
        _write_command(repo, "adr-create.md", content)
        compiler = PromptCompiler(repo)
        result = compiler.compile("/adr-create")

        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert result.content_hash == expected

    def test_hash_diverges_when_file_changes(self, repo):
        """When the file content changes, the hash must differ."""
        cmd_path = _write_command(repo, "adr-create.md", "version 1")
        compiler = PromptCompiler(repo)
        result_v1 = compiler.compile("/adr-create")

        # Mutate the file
        cmd_path.write_text("version 2", encoding="utf-8")
        result_v2 = compiler.compile("/adr-create")

        assert result_v1.content_hash != result_v2.content_hash

    def test_hash_is_sha256_hex(self, repo):
        _write_command(repo, "daily.md", "# Daily")
        compiler = PromptCompiler(repo)
        result = compiler.compile("/daily")
        assert len(result.content_hash) == 64
        assert all(c in "0123456789abcdef" for c in result.content_hash)


# ------------------------------------------------------------------
# Path traversal security
# ------------------------------------------------------------------


class TestPathTraversal:
    def test_dot_dot_in_namespace_refused(self, repo):
        """A namespace component with .. must not escape the repo root."""
        compiler = PromptCompiler(repo)
        # .claude/commands/ is 2 levels deep; need 3+ ".." to escape repo root
        with pytest.raises(PathTraversalError, match="escapes repo root"):
            compiler.resolve_command_path("/foo:..:..:..:..:etc:passwd")

    def test_absolute_path_injected_via_name(self, repo):
        """Absolute paths in the command name must be refused."""
        compiler = PromptCompiler(repo)
        with pytest.raises((PathTraversalError, CommandNotFoundError)):
            compiler.resolve_command_path("/../../etc/passwd")

    def test_resolved_path_inside_commands_dir(self, repo):
        """Normal commands resolve inside .claude/commands/."""
        _write_command(repo, "safe.md", "# Safe")
        compiler = PromptCompiler(repo)
        path = compiler.resolve_command_path("/safe")
        assert str(path).startswith(str((repo / ".claude/commands").resolve()))


# ------------------------------------------------------------------
# Frontmatter helpers
# ------------------------------------------------------------------


class TestFrontmatterHelpers:
    def test_strip_frontmatter_present(self):
        content = "---\nkey: value\n---\nBody here."
        assert _strip_frontmatter(content) == "Body here."

    def test_strip_frontmatter_absent(self):
        content = "# No frontmatter\nJust body."
        assert _strip_frontmatter(content) == content

    def test_parse_simple_frontmatter(self):
        content = "---\ndescription: Hello\nmodel: opus\n---\nBody."
        meta = _parse_frontmatter_raw(content)
        assert meta["description"] == "Hello"
        assert meta["model"] == "opus"

    def test_parse_empty_frontmatter(self):
        content = "---\n---\nBody."
        meta = _parse_frontmatter_raw(content)
        assert meta == {}

    def test_parse_no_frontmatter(self):
        meta = _parse_frontmatter_raw("Just body.")
        assert meta == {}

    def test_normalise_name(self):
        assert _normalise_name("daily") == "/daily"
        assert _normalise_name("/daily") == "/daily"
        assert _normalise_name("///daily") == "/daily"
        assert _normalise_name("/loop:iteraction:execute-task") == "/loop:iteraction:execute-task"

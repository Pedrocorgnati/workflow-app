"""Tests for the prompt compiler module.

Covers:

- Top-level command resolution
- Namespaced command resolution (colon -> directory separator)
- Literal argument passing (no variable substitution)
- Hash divergence when the target file content changes
- Path resolved outside the repo root is refused (security)
- Hybrid envelope contract (D-36): command_path and content_hash inside the
  prompt text, reading protocol, essential-slice selection, DA-01 and DA-02
- Measured size reduction against the real ``/qa:trace`` of this repo

Contract change (item 007 of loop 08-17-systemforge-multillm-gaps-refactor):
the compiler no longer injects the whole body with the frontmatter stripped.
Tests that asserted the old contract were rewritten in place, naming the
revocation in their own docstring. No test was deleted.
"""

from __future__ import annotations

import hashlib
import textwrap

import pytest

from pathlib import Path

from workflow_app.prompt_compiler import (
    CommandNotFoundError,
    CompiledPrompt,
    PathTraversalError,
    PromptCompiler,
    _essential_slices,
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

    def test_compile_carries_full_frontmatter_in_envelope(self, repo):
        """REVOKED CONTRACT (D-36, item 007).

        This test used to be ``test_compile_returns_body_without_frontmatter``
        and asserted ``"description: Create an ADR" not in prompt_text`` plus
        ``"model: opus" not in prompt_text``. Both assertions invert under
        D-36: the hybrid envelope carries the **complete frontmatter** inside
        the prompt text. It also used to assert the body was present; under
        DA-01 a command with no essential section injects no body at all.
        """
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
        # Frontmatter now travels inside the envelope (contract inverted).
        assert "description: Create an ADR" in result.prompt_text
        assert "model: opus" in result.prompt_text
        # DA-01: no essential section -> no body injected.
        assert "Create an Architecture Decision Record." not in result.prompt_text
        # The file is still reachable: path and hash are in the text.
        assert result.command_path in result.prompt_text
        assert result.content_hash in result.prompt_text

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

    def test_compile_namespaced_envelope(self, repo):
        """REVOKED CONTRACT (D-36, item 007).

        This test used to be ``test_compile_namespaced_body`` and asserted
        ``"description:" not in prompt_text``. That assertion inverts for the
        same reason as the top-level one: the frontmatter is part of the
        envelope. What survives unchanged is the command-name normalisation
        the test also protected.
        """
        content = textwrap.dedent("""\
            ---
            description: Accessibility audit
            ---
            ## Resolucao de Escopo
            Audit and fix accessibility issues.
        """)
        _write_command(repo, "android/accessibility.md", content)
        compiler = PromptCompiler(repo)
        result = compiler.compile("/android:accessibility")

        # Essential slice (arguments family) is injected integrally.
        assert "Audit and fix accessibility issues." in result.prompt_text
        # Frontmatter now travels inside the envelope (contract inverted).
        assert "description: Accessibility audit" in result.prompt_text
        assert result.command_name == "/android:accessibility"

    def test_namespaced_not_found(self, repo):
        compiler = PromptCompiler(repo)
        with pytest.raises(CommandNotFoundError):
            compiler.resolve_command_path("/foo:bar:baz")


# ------------------------------------------------------------------
# Literal argument passing
# ------------------------------------------------------------------


class TestArgumentPassing:
    def test_arguments_carried_in_envelope(self, repo):
        """Fixture adjusted for DA-01 (item 007).

        The original fixture was a body with no essential section, so under
        D-36 nothing of it is injected and the old ``"# ADR" in prompt_text``
        assertion no longer holds. The intent the test protected - the literal
        argument reaches the prompt - is preserved, now with a command that
        declares an arguments section.
        """
        _write_command(
            repo,
            "adr-create.md",
            "# ADR\n\n## Argumentos\nCreate an ADR.\n",
        )
        compiler = PromptCompiler(repo)
        result = compiler.compile("/adr-create", ".claude/project-2.json")

        assert "## Argumentos" in result.prompt_text
        assert "Create an ADR." in result.prompt_text
        assert ".claude/project-2.json" in result.prompt_text

    def test_arguments_passed_literal_no_substitution(self, repo):
        """Arguments must NOT be interpolated into template variables.

        Fixture adjusted for DA-01 (item 007): the placeholders now live
        inside an arguments section, so they are part of the essential slice.
        The contract under test is unchanged - no interpolation happens.
        """
        content = "# Cmd\n\n## Argumentos\nUse {project_name} and {docs_root}.\n"
        _write_command(repo, "test-cmd.md", content)
        compiler = PromptCompiler(repo)
        args = "--kimi --codex"
        result = compiler.compile("/test-cmd", args)

        # The injected slice keeps its original {placeholders} untouched
        assert "{project_name}" in result.prompt_text
        assert "{docs_root}" in result.prompt_text
        # Arguments appear literally in the envelope
        assert "--kimi --codex" in result.prompt_text

    def test_empty_arguments_no_trailing_whitespace(self, repo):
        """REVOKED CONTRACT (D-36, item 007).

        This test asserted ``prompt_text.rstrip() == "# Daily report"``, i.e.
        that the prompt was the bare body. The envelope makes that false by
        construction. What it really protected - no whitespace garbage when
        ``arguments == ""`` and the empty argument preserved on the result -
        is asserted here instead.
        """
        _write_command(repo, "daily.md", "# Daily report")
        compiler = PromptCompiler(repo)
        result = compiler.compile("/daily", "")
        assert result.prompt_text == result.prompt_text.rstrip()
        assert not result.prompt_text.endswith("\n")
        assert "Argumentos: (nenhum)" in result.prompt_text
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


# ------------------------------------------------------------------
# Hybrid envelope (D-36, item 007 of loop 08-17)
# ------------------------------------------------------------------


_ESSENTIAL_FIXTURE = textwrap.dedent("""\
    ---
    description: Trace command
    model: opus
    ---
    # Trace

    Prose before any section.

    ## Configuracao Alternativa (Argumento Opcional)

    Pass --module N to scope the run.

    ## FASE PRE-0: Carregamento e Contexto

    Load the project json before anything else.

    ## Apendice volumoso

    NOT_ESSENTIAL_MARKER repeated filler that must never reach the envelope.

    ## FASE FINAL

    ```bash
    wf-notify.sh --status success --exit-code 0
    ```
""")


class TestHybridEnvelope:
    """Acceptance criteria of item 007 (D-36)."""

    def test_command_path_appears_in_prompt_text(self, repo):
        """1st acceptance criterion: command_path travels as substring."""
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace", "--module 3")
        assert result.command_path in result.prompt_text

    def test_content_hash_appears_in_prompt_text(self, repo):
        """1st acceptance criterion: content_hash travels as substring."""
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace", "--module 3")
        assert result.content_hash in result.prompt_text
        assert len(result.content_hash) == 64

    def test_reading_protocol_declares_hash_divergence_behaviour(self, repo):
        """3rd acceptance criterion: protocol present and divergence declared."""
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace")
        text = result.prompt_text

        assert "PROTOCOLO DE LEITURA" in text
        assert "Recalcule o SHA-256" in text
        assert "Se os hashes divergirem, PARE." in text
        assert "erro observavel, nunca silencio" in text

    def test_arguments_section_injected_integrally(self, repo):
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace")
        assert "## Configuracao Alternativa (Argumento Opcional)" in result.prompt_text
        assert "Pass --module N to scope the run." in result.prompt_text

    def test_non_essential_section_not_injected(self, repo):
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace")
        assert "NOT_ESSENTIAL_MARKER" not in result.prompt_text
        assert "## Apendice volumoso" not in result.prompt_text

    def test_fase_zero_section_injected_integrally(self, repo):
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace")
        assert "## FASE PRE-0: Carregamento e Contexto" in result.prompt_text
        assert "Load the project json before anything else." in result.prompt_text

    def test_da01_no_essential_section_injects_no_body(self, repo):
        """DA-01: nothing matches -> envelope with no body, declared as such."""
        _write_command(repo, "adr-create.md", "# ADR\nCreate an ADR.\n")
        result = PromptCompiler(repo).compile("/adr-create")
        assert "Create an ADR." not in result.prompt_text
        assert "--- TRECHOS ESSENCIAIS (nenhum) ---" in result.prompt_text
        # The envelope still gives the target everything it needs to read on.
        assert result.command_path in result.prompt_text
        assert result.content_hash in result.prompt_text

    def test_da02_fase_final_bash_not_injected(self, repo):
        """DA-02: the FASE FINAL handshake block never enters the envelope."""
        _write_command(repo, "qa/trace.md", _ESSENTIAL_FIXTURE)
        result = PromptCompiler(repo).compile("/qa:trace")
        assert "wf-notify.sh" not in result.prompt_text
        assert "## FASE FINAL" not in result.prompt_text

    def test_headings_inside_fenced_block_are_not_sections(self, repo):
        content = textwrap.dedent("""\
            # Cmd

            ## Argumentos

            Real section.

            ```markdown
            ## Argumentos
            FENCED_MARKER example inside a code block.
            ```

            ## Apendice

            TAIL_MARKER after the fence.
        """)
        _write_command(repo, "fenced.md", content)
        result = PromptCompiler(repo).compile("/fenced")
        # The fenced heading does not open a new slice...
        assert "FENCED_MARKER" in result.prompt_text  # it is inside the real slice
        # ...and the fence does not swallow the following real heading either.
        assert "TAIL_MARKER" not in result.prompt_text

    def test_nested_essential_heading_not_duplicated(self, repo):
        content = textwrap.dedent("""\
            # Cmd

            ## FASE 0: setup

            Outer.

            ### Pre-requisito

            UNIQUE_NESTED_MARKER inner.
        """)
        _write_command(repo, "nested.md", content)
        result = PromptCompiler(repo).compile("/nested")
        assert result.prompt_text.count("UNIQUE_NESTED_MARKER") == 1

    def test_essential_slices_is_pure_and_ordered(self):
        body = textwrap.dedent("""\
            ## Apendice
            no
            ## Argumentos
            a
            ## Pre-requisito
            b
        """)
        slices = _essential_slices(body)
        assert [heading for heading, _ in slices] == [
            "## Argumentos",
            "## Pre-requisito",
        ]
        # Pure: same input, same output.
        assert _essential_slices(body) == slices


# ------------------------------------------------------------------
# Measured size reduction against the real /qa:trace (ST008)
# ------------------------------------------------------------------


def _find_repo_root() -> Path | None:
    """Walk up from this test file looking for the SystemForge repo root."""
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / ".claude" / "commands").is_dir() and (
            candidate / "CLAUDE.md"
        ).is_file():
            return candidate
    return None


class TestCompiledSizeReduction:
    def test_qa_trace_envelope_is_smaller_than_full_body(self):
        """Measured reduction against the real command, not a frozen constant.

        Baseline measured on 2026-08-18 with the full-body contract:
        ``prompt_text`` of ``compile("/qa:trace", "--module 3")`` was 28225
        characters (raw file 29454, frontmatter 1238, arguments appended to the
        body by the revoked contract). The same call under the hybrid envelope
        emits 11537 characters (59.1% reduction), reading protocol and complete
        frontmatter overhead already included.

        The assertion deliberately compares against the body read **at test
        time**, never against a frozen number: ``.claude/commands/qa/trace.md``
        grows over time, and that is exactly how the "about 13 thousand
        characters" quoted by the loop source became 28225.
        """
        repo_root = _find_repo_root()
        if repo_root is None:
            pytest.skip("SystemForge repo root not found from the test file")
        trace = repo_root / ".claude" / "commands" / "qa" / "trace.md"
        if not trace.is_file():
            pytest.skip(f"partial checkout: {trace} is absent")

        raw = trace.read_text(encoding="utf-8")
        full_body_len = len(_strip_frontmatter(raw).rstrip("\n"))

        result = PromptCompiler(repo_root).compile("/qa:trace", "--module 3")
        compiled_len = len(result.prompt_text)

        assert compiled_len < full_body_len, (
            f"envelope ({compiled_len}) must be smaller than the full body "
            f"({full_body_len}); the hybrid compilation regressed to integral "
            f"injection"
        )
        # The reduction must be substantial, not marginal. 50% is a floor
        # chosen below the 59.1% measured on 2026-08-18 so that ordinary
        # growth of the command file does not turn this red.
        assert compiled_len <= full_body_len * 0.5, (
            f"expected at least 50% reduction, got "
            f"{100 * (1 - compiled_len / full_body_len):.1f}% "
            f"({full_body_len} -> {compiled_len})"
        )
        # And the envelope still carries the verified reference.
        assert result.command_path in result.prompt_text
        assert result.content_hash in result.prompt_text

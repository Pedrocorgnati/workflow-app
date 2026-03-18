"""
Tests for SystemProgressWriter core (module-07/TASK-1/ST003).

Covers:
  - generate() creates SYSTEM-PROGRESS.md
  - generate() is idempotent (no duplication)
  - generate() adds new commands on second call
  - mark_completed() updates checkbox [ ] → [x]
  - mark_completed() does not affect other commands
  - mark_error() adds [!] with error message
  - mark_completed() on non-existent command does not crash
  - mark on non-existent file does not crash
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.domain import CommandSpec
from workflow_app.system_progress_writer import SystemProgressWriter

# ─── Helpers ────────────────────────────────────────────────────────────── #


def _cmd(name: str) -> CommandSpec:
    """Build minimal CommandSpec."""
    return CommandSpec(name=name)


# ─── TestGenerate ────────────────────────────────────────────────────────── #


class TestGenerate:
    def test_generate_creates_file(self, tmp_path):
        cmds = [_cmd("prd-create"), _cmd("hld-create")]
        SystemProgressWriter().generate(cmds, str(tmp_path), "TestProj")
        target = tmp_path / "SYSTEM-PROGRESS.md"
        assert target.exists()
        content = target.read_text()
        assert "/prd-create" in content
        assert "/hld-create" in content

    def test_generate_includes_project_name(self, tmp_path):
        SystemProgressWriter().generate([_cmd("prd-create")], str(tmp_path), "MeuProjeto")
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "MeuProjeto" in content

    def test_generate_marks_all_commands_as_pending(self, tmp_path):
        cmds = [_cmd("prd-create"), _cmd("hld-create")]
        SystemProgressWriter().generate(cmds, str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert content.count("[ ]") == 2

    def test_generate_idempotent_does_not_duplicate(self, tmp_path):
        cmds = [_cmd("prd-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.generate(cmds, str(tmp_path))  # segunda chamada
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert content.count("/prd-create") == 1

    def test_generate_adds_new_commands_on_second_call(self, tmp_path):
        w = SystemProgressWriter()
        w.generate([_cmd("prd-create")], str(tmp_path))
        w.generate([_cmd("prd-create"), _cmd("hld-create")], str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/hld-create" in content

    def test_generate_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "docs" / "sub"
        SystemProgressWriter().generate([_cmd("prd-create")], str(nested))
        assert (nested / "SYSTEM-PROGRESS.md").exists()


# ─── TestMarkCompleted ───────────────────────────────────────────────────── #


class TestMarkCompleted:
    def test_mark_completed_updates_checkmark(self, tmp_path):
        """mark_completed changes [ ] to [x] for the target command."""
        cmds = [_cmd("prd-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_completed("prd-create", str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        # Format: [x]\n/model Sonnet\n/prd-create
        assert "[x]" in content
        assert "/prd-create" in content
        # Original pending marker replaced
        lines = content.splitlines()
        # Find the command line and verify the marker line above it is [x]
        for i, line in enumerate(lines):
            if line.strip() == "/prd-create":
                # Go back to find the closest marker line
                for j in range(i - 1, max(i - 3, -1), -1):
                    if lines[j].strip() in ("[ ]", "[x]", "[!]"):
                        assert lines[j].strip() == "[x]", f"Expected [x], got {lines[j]}"
                        break
                break

    def test_mark_completed_does_not_affect_other_commands(self, tmp_path):
        cmds = [_cmd("prd-create"), _cmd("hld-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_completed("prd-create", str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "[ ]" in content   # hld-create ainda pendente
        assert "[x]" in content   # prd-create marcado

    def test_mark_nonexistent_command_does_not_crash(self, tmp_path):
        cmds = [_cmd("prd-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_completed("nonexistent-cmd", str(tmp_path))  # não deve levantar

    def test_mark_on_nonexistent_file_does_not_crash(self, tmp_path):
        w = SystemProgressWriter()
        w.mark_completed("prd-create", str(tmp_path))  # arquivo não existe — não deve levantar


# ─── TestMarkError ───────────────────────────────────────────────────────── #


class TestMarkError:
    def test_mark_error_adds_error_marker(self, tmp_path):
        cmds = [_cmd("hld-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_error("hld-create", "Timeout após 30s", str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "[!]" in content
        assert "/hld-create" in content

    def test_mark_error_includes_error_message(self, tmp_path):
        cmds = [_cmd("hld-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_error("hld-create", "Timeout após 30s", str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "Timeout após 30s" in content

    def test_mark_error_does_not_affect_other_commands(self, tmp_path):
        cmds = [_cmd("prd-create"), _cmd("hld-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_error("hld-create", "Erro", str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "[!]" in content
        assert "[ ]" in content   # prd-create ainda pendente

    def test_mark_error_on_nonexistent_file_does_not_crash(self, tmp_path):
        w = SystemProgressWriter()
        w.mark_error("prd-create", "Erro", str(tmp_path))  # sem arquivo — não deve levantar

    def test_mark_error_nonexistent_command_does_not_crash(self, tmp_path):
        cmds = [_cmd("prd-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_error("nonexistent-cmd", "Erro", str(tmp_path))  # não deve levantar


# ─── TestGetStatus ──────────────────────────────────────────────────────── #


class TestGetStatus:
    def test_get_status_pending(self, tmp_path):
        w = SystemProgressWriter()
        w.generate([_cmd("prd-create")], str(tmp_path))
        assert w.get_status("prd-create", str(tmp_path)) == "pending"

    def test_get_status_completed(self, tmp_path):
        w = SystemProgressWriter()
        w.generate([_cmd("prd-create")], str(tmp_path))
        w.mark_completed("prd-create", str(tmp_path))
        assert w.get_status("prd-create", str(tmp_path)) == "completed"

    def test_get_status_error(self, tmp_path):
        w = SystemProgressWriter()
        w.generate([_cmd("hld-create")], str(tmp_path))
        w.mark_error("hld-create", "Timeout", str(tmp_path))
        assert w.get_status("hld-create", str(tmp_path)) == "error"

    def test_get_status_nonexistent_command(self, tmp_path):
        w = SystemProgressWriter()
        w.generate([_cmd("prd-create")], str(tmp_path))
        assert w.get_status("nonexistent", str(tmp_path)) is None

    def test_get_status_nonexistent_file(self, tmp_path):
        w = SystemProgressWriter()
        assert w.get_status("prd-create", str(tmp_path)) is None

    def test_get_status_does_not_affect_other_commands(self, tmp_path):
        cmds = [_cmd("prd-create"), _cmd("hld-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        w.mark_completed("prd-create", str(tmp_path))
        assert w.get_status("prd-create", str(tmp_path)) == "completed"
        assert w.get_status("hld-create", str(tmp_path)) == "pending"


# ─── TestPhaseGrouping ──────────────────────────────────────────────────── #


class TestPhaseGrouping:
    def test_generate_groups_by_phase(self, tmp_path):
        cmds = [
            CommandSpec(name="prd-create", phase="F2"),
            CommandSpec(name="hld-create", phase="F2"),
            CommandSpec(name="ci-cd-create", phase="F11"),
        ]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F2" in content
        assert "## F11" in content
        assert "/prd-create" in content
        assert "/ci-cd-create" in content

    def test_generate_uses_default_phase_when_missing(self, tmp_path):
        cmds = [CommandSpec(name="prd-create")]
        w = SystemProgressWriter()
        w.generate(cmds, str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F?" in content


# ─── TestPermissionError ────────────────────────────────────────────────── #


class TestPermissionError:
    def test_generate_permission_error_raises(self, tmp_path, monkeypatch):
        """PermissionError during write should propagate (signal_bus emits before raise)."""

        # Make Path.write_text raise PermissionError
        _original_write = Path.write_text

        def _raise_perm(*args, **kwargs):
            raise PermissionError("mocked")

        w = SystemProgressWriter()
        # File doesn't exist, so generate() will try to create it
        monkeypatch.setattr(Path, "write_text", _raise_perm)
        with pytest.raises(PermissionError):
            w.generate([_cmd("prd-create")], str(tmp_path))


# ─── TestMultiLineFormat ────────────────────────────────────────────────── #


class TestMultiLineFormat:
    def test_update_mark_preserves_model_line(self, tmp_path):
        """mark_completed should preserve the /model line between marker and command."""
        w = SystemProgressWriter()
        w.generate([_cmd("prd-create")], str(tmp_path))
        content_before = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/model" in content_before  # model line exists

        w.mark_completed("prd-create", str(tmp_path))
        content_after = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/model" in content_after  # model line preserved
        assert "[x]" in content_after

        # Verify structure: [x] then /model then /prd-create
        lines = content_after.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "/prd-create":
                assert "/model" in lines[i - 1]
                assert "[x]" == lines[i - 2].strip()
                break

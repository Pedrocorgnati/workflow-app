"""
Tests for SystemProgressWriter expand operations (module-07/TASK-2/ST003).

Covers:
  - expand_progress() adds F5, F6, F7 sections
  - expand_progress() includes module paths in sections
  - expand_progress() is idempotent (no section duplication)
  - expand_progress() preserves existing content (completed markers)
  - add_deploy_section() adds F11 section
  - add_deploy_section() includes deploy commands
  - add_deploy_section() is idempotent
  - Both methods no-op gracefully when file does not exist
"""
from __future__ import annotations

from workflow_app.domain import CommandSpec
from workflow_app.system_progress_writer import SystemProgressWriter

# ─── Helpers ────────────────────────────────────────────────────────────── #


def _cmd(name: str) -> CommandSpec:
    return CommandSpec(name=name)


def _generate_base(w: SystemProgressWriter, tmp_path) -> None:
    w.generate([_cmd("prd-create")], str(tmp_path))


# ─── TestExpandProgress ──────────────────────────────────────────────────── #


class TestExpandProgress:
    def test_expand_adds_f5_section(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.expand_progress(["module-01-setup"], str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F5" in content

    def test_expand_adds_f7_section(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.expand_progress(["module-01-setup"], str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F7" in content

    def test_expand_adds_f6_section(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.expand_progress(["module-01-setup"], str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F6" in content

    def test_expand_includes_module_slugs(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.expand_progress(
            ["module-01-setup", "module-02-foundations"],
            str(tmp_path),
            wbs_root="output/wbs",
            project_slug="test-project",
        )
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "module-01-setup" in content
        assert "module-02-foundations" in content

    def test_expand_uses_auto_flow_execute_in_f7(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.expand_progress(
            ["module-01-setup"],
            str(tmp_path),
            wbs_root="output/wbs",
            project_slug="my-proj",
        )
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/auto-flow execute" in content
        assert "output/wbs/my-proj/modules/module-01-setup" in content

    def test_expand_idempotent_f5(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        mods = ["module-01-setup"]
        w.expand_progress(mods, str(tmp_path))
        w.expand_progress(mods, str(tmp_path))  # segunda chamada
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert content.count("## F5") == 1

    def test_expand_idempotent_f7(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        mods = ["module-01-setup"]
        w.expand_progress(mods, str(tmp_path))
        w.expand_progress(mods, str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert content.count("## F7") == 1

    def test_expand_preserves_completed_markers(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.mark_completed("prd-create", str(tmp_path))
        w.expand_progress(["module-01-setup"], str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "[x]" in content   # prd-create marked as done
        assert "/prd-create" in content

    def test_expand_on_nonexistent_file_does_not_crash(self, tmp_path):
        w = SystemProgressWriter()
        w.expand_progress(["module-01-setup"], str(tmp_path))  # no file — silent


# ─── TestAddDeploySection ────────────────────────────────────────────────── #


class TestAddDeploySection:
    def test_add_deploy_section_adds_f11(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.add_deploy_section(str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "## F11" in content

    def test_add_deploy_section_includes_pre_deploy(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.add_deploy_section(str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/pre-deploy-testing" in content

    def test_add_deploy_section_includes_ci_cd(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.add_deploy_section(str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "/ci-cd-create" in content

    def test_add_deploy_section_idempotent(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.add_deploy_section(str(tmp_path))
        w.add_deploy_section(str(tmp_path))  # segunda chamada
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert content.count("## F11") == 1

    def test_add_deploy_section_on_nonexistent_file_does_not_crash(self, tmp_path):
        w = SystemProgressWriter()
        w.add_deploy_section(str(tmp_path))  # no file — silent

    def test_add_deploy_section_preserves_existing_content(self, tmp_path):
        w = SystemProgressWriter()
        _generate_base(w, tmp_path)
        w.mark_completed("prd-create", str(tmp_path))
        w.add_deploy_section(str(tmp_path))
        content = (tmp_path / "SYSTEM-PROGRESS.md").read_text()
        assert "[x]" in content
        assert "/prd-create" in content
        assert "## F11" in content

"""
Tests for QueueExpander (module-12/TASK-5).

Covers:
  - /deploy-flow adds /post-deploy-verify and /changelog-create
  - /deploy-flow skips commands already in queue
  - /modules:review-created globs TASK-*.md and creates specs
  - /auto-flow also triggers module expansion
  - Unknown command returns empty list
  - Existing commands are not duplicated
"""
from __future__ import annotations

from workflow_app.pipeline.queue_expander import QueueExpander

# ─────────────────────────────────────────────── deploy-flow ─────── #

class TestDeployFlowExpansion:
    def test_expand_deploy_adds_post_deploy_verify(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/deploy-flow", [])
        names = [s.name for s in specs]
        assert "/post-deploy-verify" in names

    def test_expand_deploy_adds_changelog_create(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/deploy-flow", [])
        names = [s.name for s in specs]
        assert "/changelog-create" in names

    def test_expand_deploy_adds_two_commands(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/deploy-flow", [])
        assert len(specs) == 2

    def test_expand_deploy_skips_existing_post_deploy(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        existing = ["/post-deploy-verify"]
        specs = expander.check_and_expand("/deploy-flow", existing)
        names = [s.name for s in specs]
        assert "/post-deploy-verify" not in names
        assert "/changelog-create" in names

    def test_expand_deploy_returns_empty_when_all_exist(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        existing = ["/post-deploy-verify", "/changelog-create"]
        specs = expander.check_and_expand("/deploy-flow", existing)
        assert specs == []


# ─────────────────────────────────────── modules:review-created ─── #

class TestModulesReviewExpansion:
    def test_expand_from_modules_globs_tasks(self, tmp_path):
        """modules:review-created globs TASK-*.md under modules/."""
        mod = tmp_path / "modules" / "module-01-setup"
        mod.mkdir(parents=True)
        (mod / "TASK-1.md").touch()
        (mod / "TASK-2.md").touch()

        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/modules:review-created", [])
        assert len(specs) == 2

    def test_expand_from_modules_command_names_reference_tasks(self, tmp_path):
        """Spec names contain task path info."""
        mod = tmp_path / "modules" / "module-01-setup"
        mod.mkdir(parents=True)
        (mod / "TASK-1.md").touch()

        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/modules:review-created", [])
        assert len(specs) == 1
        assert "TASK-1.md" in specs[0].name

    def test_expand_from_modules_skips_existing(self, tmp_path):
        """Tasks already in queue are not duplicated."""
        mod = tmp_path / "modules" / "module-01-setup"
        mod.mkdir(parents=True)
        (mod / "TASK-1.md").touch()
        (mod / "TASK-2.md").touch()

        expander = QueueExpander(str(tmp_path))
        # Pre-expand once to get the cmd names
        first = expander.check_and_expand("/modules:review-created", [])
        existing = [s.name for s in first]
        # Second expansion should be empty
        second = expander.check_and_expand("/modules:review-created", existing)
        assert second == []

    def test_expand_from_modules_returns_empty_when_no_modules_dir(self, tmp_path):
        """Returns [] when modules/ directory doesn't exist."""
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/modules:review-created", [])
        assert specs == []

    def test_auto_flow_trigger_also_expands(self, tmp_path):
        """/auto-flow trigger behaves same as /modules:review-created."""
        mod = tmp_path / "modules" / "module-02-auth"
        mod.mkdir(parents=True)
        (mod / "TASK-1.md").touch()

        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/auto-flow", [])
        assert len(specs) == 1


# ─────────────────────────────────────────── unknown commands ─────── #

class TestUnknownCommandExpansion:
    def test_unknown_command_returns_empty(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/prd-create", [])
        assert specs == []

    def test_empty_command_returns_empty(self, tmp_path):
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("", [])
        assert specs == []


# ─────────────────────────────────────────── spec attributes ─────── #

class TestQueueExpanderSpecAttributes:
    def test_deploy_specs_have_model_and_interaction(self, tmp_path):
        """Deploy expansion specs have valid model and interaction_type."""
        from workflow_app.domain import InteractionType, ModelName
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/deploy-flow", [])
        for spec in specs:
            assert isinstance(spec.model, ModelName)
            assert isinstance(spec.interaction_type, InteractionType)

    def test_module_specs_use_sonnet(self, tmp_path):
        """Module expansion specs default to Sonnet model."""
        from workflow_app.domain import ModelName
        mod = tmp_path / "modules" / "module-01-setup"
        mod.mkdir(parents=True)
        (mod / "TASK-1.md").touch()
        expander = QueueExpander(str(tmp_path))
        specs = expander.check_and_expand("/modules:review-created", [])
        assert specs[0].model == ModelName.SONNET

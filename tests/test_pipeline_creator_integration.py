"""Integration tests for module-04 (module-04/TASK-4)."""

from __future__ import annotations

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.interview.interview_engine import InterviewEngine


class TestInterviewGeneratesCommands:
    def test_engine_returns_commands_for_novo_nextjs(self) -> None:
        engine = InterviewEngine()
        answers = {
            "project_type": "novo",
            "stack": "nextjs",
            "has_frontend": "sim",
            "active_phases": ["f1", "f2", "f4", "f7"],
        }
        commands = engine.generate_command_list(answers)
        assert len(commands) > 5
        names = [c.name for c in commands]
        assert "/project-json" in names
        assert "/prd-create" in names

    def test_engine_returns_commands_for_feature_pyside6(self) -> None:
        engine = InterviewEngine()
        answers = {
            "project_type": "feature",
            "stack": "pyside6",
            "has_frontend": "não",
            "active_phases": ["f1", "f2"],
        }
        commands = engine.generate_command_list(answers)
        names = [c.name for c in commands]
        # Feature não tem HLD
        assert "/hld-create" not in names
        # pyside6 sem frontend não tem /front-end-build
        assert "/front-end-build" not in names

    def test_novo_with_no_frontend_excludes_frontend_commands(self) -> None:
        engine = InterviewEngine()
        answers = {
            "project_type": "novo",
            "stack": "pyside6",
            "active_phases": ["f1", "f2", "f7"],
        }
        commands = engine.generate_command_list(answers)
        names = [c.name for c in commands]
        assert "/front-end-build" not in names
        assert "/create-assets" not in names

    def test_active_phases_filter_commands(self) -> None:
        engine = InterviewEngine()
        answers = {
            "project_type": "novo",
            "stack": "nextjs",
            "active_phases": ["f1"],  # only F1 + mandatory
        }
        commands = engine.generate_command_list(answers)
        names = [c.name for c in commands]
        # F1 commands present
        assert "/project-json" in names
        # F9 commands absent
        assert "/qa:prep" not in names


class TestPipelineCreatorWidget:
    def test_dialog_instantiates_without_crash(self, qapp) -> None:
        from workflow_app.interview.pipeline_creator_widget import PipelineCreatorWidget
        dialog = PipelineCreatorWidget()
        assert dialog is not None
        assert dialog.windowTitle() == "Criar Nova Fila de Comandos"
        dialog.reject()

    def test_initial_page_is_choice(self, qapp) -> None:
        from workflow_app.interview.pipeline_creator_widget import (
            PAGE_CHOICE,
            PipelineCreatorWidget,
        )
        dialog = PipelineCreatorWidget()
        assert dialog._stack.currentIndex() == PAGE_CHOICE
        dialog.reject()

    def test_pipeline_ready_signal_emitted_on_confirm(self, qapp) -> None:
        from workflow_app.interview.pipeline_creator_widget import PipelineCreatorWidget

        dialog = PipelineCreatorWidget()
        received: list[CommandSpec] = []
        dialog.pipeline_ready.connect(lambda cmds: received.extend(cmds))

        spec = CommandSpec(
            name="/prd-create",
            model=ModelName.OPUS,
            interaction_type=InteractionType.AUTO,
            position=1,
            is_optional=False,
        )
        dialog._load_review_page([spec])
        dialog._on_confirm()

        assert len(received) == 1
        assert received[0].name == "/prd-create"

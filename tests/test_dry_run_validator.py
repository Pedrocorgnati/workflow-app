"""
Tests for DryRunValidator (module-06/TASK-1/ST003 + TASK-3/ST003).

Covers:
  - Empty queue → error
  - F7 without F2 → warning
  - F7 without create-task → warning
  - Consecutive duplicates → warning
  - Valid queue → no errors
  - Suggestion objects populated when /review-prd-flow missing
  - Suggestion position is after last F2 command
  - Re-validation after suggestion insertion removes suggestion
"""
from __future__ import annotations

from workflow_app.domain import CommandSpec
from workflow_app.dry_run.dry_run_validator import DryRunValidator, Suggestion

# ─── Helpers ─────────────────────────────────────────────────────────────── #


def _cmd(name: str) -> CommandSpec:
    """Build a minimal CommandSpec with default model/interaction."""
    return CommandSpec(name=name)


# ─── TASK-1/ST003: Core validation rules ─────────────────────────────────── #


def test_empty_queue_returns_error():
    report = DryRunValidator().validate([])
    assert not report.is_valid
    assert len(report.errors) == 1
    assert "vazia" in report.errors[0].lower()


def test_empty_queue_has_no_warnings():
    report = DryRunValidator().validate([])
    assert report.warnings == []


def test_no_f2_returns_error():
    """Any queue without F2 documentation commands is invalid (is_valid=False)."""
    cmds = [_cmd("/execute-task")]
    report = DryRunValidator().validate(cmds)
    assert not report.is_valid
    assert len(report.errors) >= 1
    assert any("F2" in e or "documentação" in e for e in report.errors)


def test_no_f2_without_f7_also_invalid():
    """Queue with only F1/F3 commands (no F2, no F7) is also invalid."""
    cmds = [_cmd("/project-json"), _cmd("/create-flow")]
    report = DryRunValidator().validate(cmds)
    assert not report.is_valid
    assert any("F2" in e or "documentação" in e for e in report.errors)


def test_fdd_create_recognized_as_f2():
    """fdd-create should be recognized as F2 documentation command."""
    cmds = [_cmd("/fdd-create")]
    report = DryRunValidator().validate(cmds)
    assert not any("F2" in e or "documentação" in e for e in report.errors)


def test_front_end_build_recognized_as_f7():
    """front-end-build should be recognized as F7 and trigger F2-missing error."""
    cmds = [_cmd("/front-end-build")]
    report = DryRunValidator().validate(cmds)
    assert not report.is_valid
    assert any("F2" in e or "documentação" in e for e in report.errors)


def test_f7_without_create_task_returns_warning():
    cmds = [_cmd("/prd-create"), _cmd("/execute-task")]
    report = DryRunValidator().validate(cmds)
    assert any("create-task" in w for w in report.warnings)


def test_f7_with_f2_no_error_about_f2():
    cmds = [_cmd("/prd-create"), _cmd("/execute-task")]
    report = DryRunValidator().validate(cmds)
    assert not any("F2" in e or "documentação" in e for e in report.errors)


def test_consecutive_duplicates_returns_warning():
    cmds = [_cmd("/prd-create"), _cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    assert any("consecutivamente" in w for w in report.warnings)
    assert any("posições 1 e 2" in w for w in report.warnings)


def test_no_consecutive_duplicate_warning_when_spaced():
    cmds = [_cmd("/prd-create"), _cmd("/hld-create"), _cmd("/prd-create")]
    report = DryRunValidator().validate(cmds)
    assert not any("consecutivamente" in w for w in report.warnings)


def test_valid_queue_no_errors():
    cmds = [
        _cmd("/prd-create"),
        _cmd("/hld-create"),
        _cmd("/review-prd-flow"),
        _cmd("/create-task"),
        _cmd("/execute-task"),
    ]
    report = DryRunValidator().validate(cmds)
    assert report.is_valid
    assert report.errors == []


def test_valid_queue_no_warnings():
    cmds = [
        _cmd("/prd-create"),
        _cmd("/hld-create"),
        _cmd("/review-prd-flow"),
        _cmd("/create-task"),
        _cmd("/execute-task"),
    ]
    report = DryRunValidator().validate(cmds)
    assert report.warnings == []


def test_suggestion_added_when_review_missing():
    cmds = [_cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    assert len(report.suggestions) == 1
    assert "review-prd-flow" in report.suggestions[0]


def test_no_suggestion_when_review_present():
    cmds = [_cmd("/prd-create"), _cmd("/hld-create"), _cmd("/review-prd-flow")]
    report = DryRunValidator().validate(cmds)
    assert report.suggestions == []
    assert report._suggestion_objects == []


def test_no_suggestion_with_only_one_f2_command():
    """Single F2 doc without review-prd-flow should not generate suggestion."""
    cmds = [_cmd("/prd-create")]
    report = DryRunValidator().validate(cmds)
    assert report.suggestions == []


# ─── TASK-3/ST003: Suggestion objects and insertion behavior ─────────────── #


def test_suggestion_objects_populated_when_review_missing():
    cmds = [_cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    objs = report._suggestion_objects
    assert len(objs) >= 1
    assert any(s.command_to_add == "/review-prd-flow" for s in objs)


def test_suggestion_objects_empty_on_valid_queue():
    cmds = [
        _cmd("/prd-create"),
        _cmd("/hld-create"),
        _cmd("/review-prd-flow"),
        _cmd("/create-task"),
        _cmd("/execute-task"),
        _cmd("/qa:prep"),
    ]
    report = DryRunValidator().validate(cmds)
    assert report._suggestion_objects == []


def test_suggestion_position_is_after_last_f2():
    """Last F2 command is at index 1 (0-based); insertion should be at index 2."""
    cmds = [_cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    objs = report._suggestion_objects
    review_sug = next(s for s in objs if s.command_to_add == "/review-prd-flow")
    # prd-create at index 0, hld-create at index 1 → insert at 2
    assert review_sug.recommended_position == 2


def test_suggestion_position_respects_last_f2_index():
    """With extra non-F2 commands before F2, position tracks last F2."""
    # F2 commands at indices 1 and 2, last F2 at index 2 → insert at 3
    cmds = [
        _cmd("/create-task"),
        _cmd("/prd-create"),
        _cmd("/hld-create"),
    ]
    report = DryRunValidator().validate(cmds)
    objs = report._suggestion_objects
    review_sug = next(s for s in objs if s.command_to_add == "/review-prd-flow")
    assert review_sug.recommended_position == 3


def test_insert_suggestion_removes_it_on_revalidation():
    """After inserting the suggested command, re-validation should not suggest it again."""
    cmds = [_cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    objs = report._suggestion_objects
    review_sug = next(s for s in objs if s.command_to_add == "/review-prd-flow")

    # Simulate insertion at recommended position
    cmds.insert(review_sug.recommended_position, _cmd("/review-prd-flow"))
    report2 = DryRunValidator().validate(cmds)
    assert not any("/review-prd-flow" in s for s in report2.suggestions)
    assert report2._suggestion_objects == []


def test_suggestion_is_suggestion_dataclass():
    cmds = [_cmd("/prd-create"), _cmd("/hld-create")]
    report = DryRunValidator().validate(cmds)
    for obj in report._suggestion_objects:
        assert isinstance(obj, Suggestion)
        assert obj.text
        assert obj.command_to_add
        assert isinstance(obj.recommended_position, int)
        assert isinstance(obj.reason, str)  # reason can be empty string


# ─── TASK-5: Regra 3 com precedência e sugestão QA ───────────────────────── #


def test_create_task_after_execute_task_triggers_warning():
    """create-task after execute-task violates precedence — should warn."""
    cmds = [_cmd("/prd-create"), _cmd("/execute-task"), _cmd("/create-task")]
    report = DryRunValidator().validate(cmds)
    assert any("create-task" in w for w in report.warnings)


def test_create_task_before_execute_task_no_warning():
    """create-task before execute-task is correct precedence — no warning."""
    cmds = [_cmd("/prd-create"), _cmd("/create-task"), _cmd("/execute-task")]
    report = DryRunValidator().validate(cmds)
    assert not any("create-task" in w for w in report.warnings)


def test_suggestion_reason_has_default():
    """Suggestion.reason should have a default value of empty string."""
    sug = Suggestion(
        text="Test",
        command_to_add="/test",
        recommended_position=0,
    )
    assert sug.reason == ""


def test_qa_suggestion_when_f7_present():
    """When F7 is present without QA commands, suggest /qa:prep."""
    cmds = [_cmd("/prd-create"), _cmd("/create-task"), _cmd("/execute-task")]
    report = DryRunValidator().validate(cmds)
    assert any("qa:prep" in s for s in report.suggestions)


def test_no_qa_suggestion_when_qa_present():
    """When QA command is already in queue, no QA suggestion needed."""
    cmds = [_cmd("/prd-create"), _cmd("/execute-task"), _cmd("/qa:prep")]
    report = DryRunValidator().validate(cmds)
    assert not any("qa:prep" in s for s in report.suggestions)

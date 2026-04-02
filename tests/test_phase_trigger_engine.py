from __future__ import annotations

from workflow_app.pipeline.phase_trigger_engine import PhaseTriggerEngine


def _write_contract(path):
    path.write_text(
        """
{
  "phase_triggers": {
    "f2_post_review": {
      "on_command_success": "/review-prd-flow",
      "auto_actions": [
        "/pipeline:run-scorecard --phase f2",
        "/cmd:backlog-from-lessons --phase f2"
      ]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_trigger_expands_actions(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers=set(),
        config_path=".claude/projects/demo.json",
    )

    assert trigger_id == "f2_post_review"
    assert [s.name for s in specs] == [
        "/pipeline:run-scorecard --phase f2",
        "/cmd:backlog-from-lessons --phase f2",
    ]
    assert all(s.config_path == ".claude/projects/demo.json" for s in specs)


def test_trigger_respects_fired_triggers(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=[],
        fired_triggers={"f2_post_review"},
        config_path="",
    )

    assert trigger_id is None
    assert specs == []


def test_trigger_dedupes_existing_actions(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    trigger_id, specs = engine.check_and_expand(
        "/review-prd-flow",
        existing_commands=["/pipeline:run-scorecard --phase f2"],
        fired_triggers=set(),
        config_path="",
    )

    assert trigger_id == "f2_post_review"
    assert [s.name for s in specs] == ["/cmd:backlog-from-lessons --phase f2"]


def test_compile_time_injection_inserts_after_checkpoint(tmp_path):
    contract = tmp_path / "PHASE-CONTRACTS.json"
    _write_contract(contract)
    engine = PhaseTriggerEngine(contract)

    from workflow_app.domain import CommandSpec

    queue = [
        CommandSpec(name="/project-json"),
        CommandSpec(name="/review-prd-flow"),
        CommandSpec(name="/auto-flow modules"),
    ]

    out = engine.inject_phase_actions_into_queue(queue)
    names = [c.name for c in out]
    idx = names.index("/review-prd-flow")
    assert names[idx + 1] == "/pipeline:run-scorecard --phase f2"
    assert names[idx + 2] == "/cmd:backlog-from-lessons --phase f2"
